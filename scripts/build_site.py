"""Build the public site from approved Markdown. No network or model calls."""

from __future__ import annotations

import datetime as dt
import html
import json
import re
import shutil
import string
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

import yaml
from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
MAX_REPORT = 256 * 1024
DATE_FILE = re.compile(r"(\d{4}-\d{2}-\d{2})\.md")
MARKER = ".cowrie-reports-build"
ASSET_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


class BuildError(ValueError):
    pass


def read(path: Path, limit: int) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise BuildError(f"{path.name}: missing, linked, or too large")
    return path.read_text(encoding="utf-8")


def text(value, field, maximum, *, required=False):
    if value is None and not required:
        return ""
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
        or any(ord(c) < 32 for c in value)
    ):
        raise BuildError(f"Invalid {field}")
    return value.strip()


@dataclass
class Report:
    date: dt.date
    title: str
    summary: str
    author: str
    markdown: str
    body: str

    @property
    def day(self):
        return self.date.isoformat()

    @property
    def display_date(self):
        return f"{self.date.day} {self.date.strftime('%b %Y')}"


def load_report(path: Path) -> Report:
    match = DATE_FILE.fullmatch(path.name)
    if not match:
        raise BuildError("Report filenames must be YYYY-MM-DD.md")
    date = dt.date.fromisoformat(match[1])
    markdown = read(path, MAX_REPORT)
    lines = markdown.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise BuildError(f"{path.name}: YAML front matter is required")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise BuildError(f"{path.name}: unclosed front matter")
    front = "".join(lines[1:end])
    if len(front.encode()) > 4096:
        raise BuildError(f"{path.name}: front matter is too large")
    if any(
        isinstance(t, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken))
        for t in yaml.scan(front)
    ):
        raise BuildError(f"{path.name}: YAML aliases are not supported")
    node = yaml.compose(front, Loader=yaml.SafeLoader)
    if isinstance(node, yaml.MappingNode):
        keys = [key.value for key, _ in node.value]
        if any(not isinstance(key, str) for key in keys) or len(keys) != len(set(keys)):
            raise BuildError(f"{path.name}: duplicate or invalid front matter keys")
    metadata = yaml.safe_load(front)
    if not isinstance(metadata, dict) or set(metadata) - {
        "title",
        "date",
        "summary",
        "author",
    }:
        raise BuildError(f"{path.name}: unsupported front matter fields")
    if "date" in metadata and str(metadata["date"]) != date.isoformat():
        raise BuildError(f"{path.name}: date must match the filename")
    body = "".join(lines[end + 1 :]).strip()
    if not body:
        raise BuildError(f"{path.name}: report body is empty")
    return Report(
        date,
        text(metadata.get("title"), "title", 160, required=True),
        text(metadata.get("summary"), "summary", 280),
        text(metadata.get("author", "Hermes"), "author", 80, required=True),
        markdown,
        body,
    )


def render(report: Report, known_days: set[str], assets: set[str]) -> str:
    parser = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table")
    tokens = parser.parse(report.body)
    anchors = set()
    for index, token in enumerate(tokens):
        alignment = token.attrGet("style")
        if isinstance(alignment, str) and re.fullmatch(
            r"text-align:(left|right|center)", alignment
        ):
            token.attrs.pop("style")
            token.attrSet("class", "align-" + alignment.split(":")[1])
        if token.type == "heading_open":
            if token.tag == "h1":
                raise BuildError(
                    f"{report.day}: use ## for sections; title comes from front matter"
                )
            label = tokens[index + 1].content
            slug = (
                re.sub(
                    r"[^\w-]+", "-", unicodedata.normalize("NFKC", label).lower()
                ).strip("-")
                or "section"
            )
            candidate, suffix = slug, 2
            while candidate in anchors:
                candidate, suffix = f"{slug}-{suffix}", suffix + 1
            anchors.add(candidate)
            token.attrSet("id", candidate)
        for child in token.children or []:
            if child.type == "link_open":
                href = str(child.attrGet("href") or "")
                part = urlsplit(href)
                if part.scheme:
                    if part.scheme not in {"https", "http", "mailto"}:
                        raise BuildError(f"{report.day}: unsupported link scheme")
                    child.attrSet("rel", "noreferrer")
                elif part.netloc or (part.path and not DATE_FILE.fullmatch(part.path)):
                    raise BuildError(
                        f"{report.day}: local links must be YYYY-MM-DD.md or #section"
                    )
                elif part.path:
                    day = part.path[:-3]
                    if day not in known_days:
                        raise BuildError(f"{report.day}: linked report does not exist")
                    child.attrSet(
                        "href",
                        f"../{day}/" + (f"#{part.fragment}" if part.fragment else ""),
                    )
            if child.type == "image":
                src = unquote(str(child.attrGet("src") or ""))
                if src not in assets:
                    raise BuildError(
                        f"{report.day}: images must reference an existing assets/ file"
                    )
                child.attrSet("src", "../../" + quote(src, safe="/"))
    result = parser.renderer.render(tokens, parser.options, {})
    return result.replace("<table>", '<div class="table-scroll"><table>').replace(
        "</table>", "</table></div>"
    )


def asset_files(root):
    directory = root / "assets"
    if not directory.exists():
        return []
    if directory.is_symlink():
        raise BuildError("assets must not be a symlink")
    files = []
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise BuildError("Asset symlinks are not supported")
        if not path.is_file():
            continue
        if path.suffix.lower() not in ASSET_TYPES or path.stat().st_size > 4 * 1024**2:
            raise BuildError("Assets must be PNG, JPEG, WebP or GIF, at most 4 MiB")
        files.append(path)
    if sum(p.stat().st_size for p in files) > 16 * 1024**2:
        raise BuildError("Asset collection exceeds 16 MiB")
    return files


def build(root=ROOT):
    root = Path(root).resolve()
    reports_dir = root / "reports"
    if reports_dir.is_symlink():
        raise BuildError("reports must not be a symlink")
    reports = sorted(
        (load_report(p) for p in reports_dir.glob("*.md")),
        key=lambda r: r.date,
        reverse=True,
    )
    assets = asset_files(root)
    names = {p.relative_to(root).as_posix() for p in assets}
    days = {r.day for r in reports}
    index = read(root / "site/index.html", 65536)
    template = string.Template(read(root / "site/report.html", 65536))
    rows = []
    ollama_rows = []
    output = root / "_site"
    if output.is_symlink() or (output.exists() and not (output / MARKER).is_file()):
        raise BuildError("Refusing to replace an unmanaged _site directory")
    # Validate/render everything before replacing a previous successful build.
    with tempfile.TemporaryDirectory(prefix=".report-build-", dir=root) as temporary:
        staging = Path(temporary) / "output"
        staging.mkdir()
        for name in ["style.css", "favicon.svg"]:
            read(root / "site" / name, 65536)
            shutil.copyfile(root / "site" / name, staging / name)
        about = staging / "about"
        about.mkdir()
        (about / "index.html").write_text(
            read(root / "site/about.html", 65536), encoding="utf-8"
        )
        for report in reports:
            body = render(report, days, names)
            headings = MarkdownIt("commonmark").parse(report.body)
            has_ollama = any(token.type == "heading_open" and token.tag == "h2"
                and headings[index + 1].content.strip().lower() == "ollama api"
                for index, token in enumerate(headings[:-1]))
            if has_ollama:
                ollama_rows.append(f'<li class="report-row"><time datetime="{report.day}">{report.display_date}</time><div><h3><a href="../reports/{report.day}/#ollama-api">{html.escape(report.title)}</a></h3></div></li>')
            destination = staging / "reports" / report.day
            destination.mkdir(parents=True)
            title, summary, author = (
                html.escape(v, quote=True)
                for v in (report.title, report.summary, report.author)
            )
            page = template.substitute(
                title=title,
                description=summary or title,
                date=report.day,
                display_date=report.display_date,
                author=author,
                summary=f'<p class="report-summary">{summary}</p>' if summary else "",
                body=body,
            )
            (destination / "index.html").write_text(page, encoding="utf-8")
            (staging / "reports" / f"{report.day}.md").write_text(
                report.markdown, encoding="utf-8"
            )
            rows.append(
                f'<li class="report-row"><time datetime="{report.day}">{report.display_date}</time><div><h3><a href="reports/{report.day}/">{title}</a></h3>'
                + (f"<p>{summary}</p>" if summary else "")
                + "</div></li>"
            )
        listing = (
            '<ul class="report-rows">' + "".join(rows) + "</ul>"
            if rows
            else '<p class="empty-state">No reports yet.</p>'
        )
        ollama_page = read(root / "site/ollama.html", 65536)
        ollama_listing = '<ul class="report-rows">' + ''.join(ollama_rows) + '</ul>' if ollama_rows else '<p class="empty-state">No Ollama summaries yet.</p>'
        ollama_page, ollama_count = re.subn(r"<!-- ollama:start -->.*?<!-- ollama:end -->", lambda _: ollama_listing, ollama_page, flags=re.DOTALL)
        if ollama_count != 1:
            raise BuildError("Expected one Ollama report list marker")
        (staging / "ollama").mkdir()
        (staging / "ollama/index.html").write_text(ollama_page, encoding="utf-8")
        marker = r"<!-- reports:start -->.*?<!-- reports:end -->"
        index, count = re.subn(marker, lambda _: listing, index, flags=re.DOTALL)
        if count != 1:
            raise BuildError("Expected one report list marker in the index template")
        (staging / "index.html").write_text(index, encoding="utf-8")
        for path in assets:
            target = staging / path.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        (staging / MARKER).write_text("Generated by scripts/build_site.py\n")
        (staging / ".nojekyll").touch()
        if output.exists():
            shutil.rmtree(output)
        staging.rename(output)
    return {"reports": len(reports), "output": "_site"}


if __name__ == "__main__":
    try:
        print(json.dumps(build()))
    except (ValueError, OSError, yaml.YAMLError) as error:
        # YAML errors can contain source snippets: keep diagnostics bounded.
        print(
            str(error)
            if isinstance(error, BuildError)
            else "Site build failed: invalid report input.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None

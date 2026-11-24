"""Temporary, inert Markdown fixtures only. No production reports or API calls."""

import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "build_site", Path(__file__).resolve().parents[1] / "scripts/build_site.py"
)
site = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = site
spec.loader.exec_module(site)


class BuildTests(unittest.TestCase):
    def test_ollama_archive_links_only_reports_with_a_real_section(self):
        self.report(day="2026-01-02", body="## Ollama API\n\nInert aggregate fixture.")
        self.report(day="2026-01-03", body="## SSH\n\n```text\n## Ollama API\n```\n")
        self.build()
        page = self.output("ollama/index.html")
        self.assertIn("../reports/2026-01-02/#ollama-api", page)
        self.assertNotIn("../reports/2026-01-03/", page)
        self.assertIn('id="ollama-api"', self.output("reports/2026-01-02/index.html"))

    def test_ollama_archive_empty_state_does_not_invent_a_report(self):
        self.build()
        self.assertIn("No Ollama summaries yet.", self.output("ollama/index.html"))
        self.assertNotIn("#ollama-api", self.output("ollama/index.html"))

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        shutil.copytree(site.ROOT / "site", self.root / "site")
        (self.root / "reports").mkdir()

    def report(
        self,
        day="2026-01-02",
        title="Inert fixture",
        body="## Fixture\n\nTest text only.",
        extra="",
    ):
        path = self.root / "reports" / f"{day}.md"
        path.write_text(f"---\ntitle: '{title}'\n{extra}---\n\n{body}\n")
        return path

    def build(self):
        return site.build(self.root)

    def output(self, name="index.html"):
        return (self.root / "_site" / name).read_text()

    def test_empty_site_contains_no_report_pages_or_private_inputs(self):
        (self.root / "private-fixture.txt").write_text("Not a public artifact")
        (self.root / "site/extra-fixture.txt").write_text("Not a public artifact")
        self.assertEqual(self.build()["reports"], 0)
        self.assertIn("No reports yet.", self.output())
        self.assertFalse((self.root / "_site/reports").exists())
        self.assertFalse((self.root / "_site/private-fixture.txt").exists())
        self.assertFalse((self.root / "_site/extra-fixture.txt").exists())
        self.assertFalse((self.root / "_site/report.html").exists())

    def test_markdown_tables_code_and_source_are_published(self):
        body = '## Fixture\n\n| Field | Meaning |\n| --- | --- |\n| fixture | Test only |\n\n```sh\nprintf "<inert>"\n```'
        original = self.report(
            body=body,
            extra='summary: "Fixture summary"\nauthor: Hermes\ndate: 2026-01-02\n',
        )
        self.assertEqual(self.build()["reports"], 1)
        rendered = self.output("reports/2026-01-02/index.html")
        self.assertIn('<h2 id="fixture">Fixture</h2>', rendered)
        self.assertIn('<div class="table-scroll"><table>', rendered)
        self.assertIn('class="language-sh"', rendered)
        self.assertIn("&lt;inert&gt;", rendered)
        self.assertIn('href="../2026-01-02.md"', rendered)
        self.assertEqual(self.output("reports/2026-01-02.md"), original.read_text())
        self.assertIn('href="reports/2026-01-02/"', self.output())

    def test_newest_first_and_metadata_escaped(self):
        self.report(day="2026-01-01", title="Older fixture")
        self.report(
            title="Fixture <script>alert(1)</script>",
            extra='summary: \'" onclick="bad"\'\n',
        )
        self.build()
        index = self.output()
        self.assertLess(
            index.index("reports/2026-01-02/"), index.index("reports/2026-01-01/")
        )
        self.assertNotIn("<script>", index)
        self.assertIn("&lt;script&gt;", index)
        self.assertIn(
            "&quot; onclick=&quot;bad&quot;",
            self.output("reports/2026-01-02/index.html"),
        )

    def test_raw_html_and_javascript_are_not_executable(self):
        self.report(
            body='## Fixture\n\n<script>alert(1)</script>\n\n[unsafe](javascript:alert(1))\n\n<iframe src="https://example.invalid"></iframe>'
        )
        self.build()
        rendered = self.output("reports/2026-01-02/index.html")
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("<iframe", rendered)
        self.assertNotIn('href="javascript:', rendered)
        self.assertIn("&lt;script&gt;", rendered)

    def test_bad_front_matter_does_not_replace_successful_build(self):
        self.build()
        before = self.output()
        self.report(extra="draft: true\n")
        with self.assertRaisesRegex(site.BuildError, "unsupported front matter"):
            self.build()
        self.assertEqual(self.output(), before)

    def test_duplicate_dates_and_fields_are_rejected(self):
        self.report(extra="date: 2026-01-01\n")
        with self.assertRaisesRegex(site.BuildError, "date must match"):
            self.build()
        self.report(extra="title: second title\n")
        with self.assertRaisesRegex(site.BuildError, "duplicate"):
            self.build()

    def test_yaml_alias_and_object_construction_are_rejected(self):
        self.report(extra="author: &writer Hermes\nsummary: *writer\n")
        with self.assertRaises(site.BuildError):
            self.build()
        self.report(extra='author: !!python/object/apply:os.system ["not-executed"]\n')
        with self.assertRaises(site.yaml.YAMLError):
            self.build()

    def test_bad_filename_and_body_are_rejected(self):
        path = self.report()
        path.rename(path.with_name("not-a-date.md"))
        with self.assertRaisesRegex(site.BuildError, "filenames"):
            self.build()
        path.with_name("not-a-date.md").unlink()
        self.report(body="")
        with self.assertRaisesRegex(site.BuildError, "body is empty"):
            self.build()

    def test_source_size_limit_and_symlinks_are_rejected(self):
        path = self.report(body="x" * site.MAX_REPORT)
        with self.assertRaises(site.BuildError):
            self.build()
        path.unlink()
        outside = self.root / "outside.md"
        outside.write_text("Private fixture")
        path.symlink_to(outside)
        with self.assertRaises(site.BuildError):
            self.build()

    def test_removed_report_is_removed_from_output(self):
        path = self.report()
        self.build()
        path.unlink()
        self.build()
        self.assertFalse((self.root / "_site/reports").exists())
        self.assertIn("No reports yet.", self.output())

    def test_unmanaged_output_is_preserved(self):
        output = self.root / "_site"
        output.mkdir()
        keep = output / "keep.txt"
        keep.write_text("Preserve this fixture")
        with self.assertRaisesRegex(site.BuildError, "unmanaged"):
            self.build()
        self.assertTrue(keep.exists())

    def test_cross_report_links_and_duplicate_heading_anchors(self):
        self.report(day="2026-01-01")
        self.report(
            body="## Fixture\n\n[Earlier](2026-01-01.md#fixture)\n\n## Fixture\n\n[Jump](#fixture-2)"
        )
        self.build()
        rendered = self.output("reports/2026-01-02/index.html")
        self.assertIn('href="../2026-01-01/#fixture"', rendered)
        self.assertIn('id="fixture-2"', rendered)
        self.report(body="[Missing](2026-01-03.md)")
        with self.assertRaisesRegex(site.BuildError, "linked report does not exist"):
            self.build()

    def test_remote_images_are_not_fetched_or_embedded(self):
        self.report(body="![Fixture](https://example.invalid/tracker.png)")
        with self.assertRaisesRegex(site.BuildError, "images must reference"):
            self.build()

    def test_local_image_is_copied_and_rebased(self):
        assets = self.root / "assets"
        assets.mkdir()
        (assets / "fixture.png").write_bytes(b"Inert fixture bytes")
        self.report(body="![Fixture](assets/fixture.png)")
        self.build()
        self.assertIn(
            'src="../../assets/fixture.png"',
            self.output("reports/2026-01-02/index.html"),
        )
        self.assertEqual(
            (self.root / "_site/assets/fixture.png").read_bytes(),
            b"Inert fixture bytes",
        )

    def test_table_alignment_does_not_require_inline_styles(self):
        self.report(body="| Field | Value |\n| :--- | ---: |\n| fixture | Test only |")
        self.build()
        rendered = self.output("reports/2026-01-02/index.html")
        self.assertIn('class="align-right"', rendered)
        self.assertNotIn('style="text-align:', rendered)

    def test_wide_table_gets_escaped_mobile_labels_and_column_headers(self):
        self.report(body=(
            "| Address | **Visits** | `<label>` |\n"
            "| --- | ---: | --- |\n"
            "| `192.0.2.1` | 3 | |\n"
            "| `192.0.2.2` | 1 | Note |\n"
        ))
        self.build()
        rendered = self.output("reports/2026-01-02/index.html")
        self.assertIn('<table class="stack-table" role="table">', rendered)
        self.assertIn('role="columnheader" scope="col"', rendered)
        self.assertIn('<th class="align-right"', rendered)
        label = '<span class="table-label" aria-hidden="true">'
        self.assertEqual(rendered.count(f"{label}Address</span>"), 2)
        self.assertIn(f"{label}Visits</span><span>3</span>", rendered)
        self.assertIn(f"{label}&lt;label&gt;</span><span></span>", rendered)
        self.assertNotIn("<label>", rendered)

    def test_numbered_heading_names_do_not_collide(self):
        self.report(body="## Fixture\n\n## Fixture\n\n## Fixture-2")
        self.build()
        rendered = self.output("reports/2026-01-02/index.html")
        self.assertEqual(rendered.count('id="fixture-2"'), 1)
        self.assertIn('id="fixture-2-2"', rendered)

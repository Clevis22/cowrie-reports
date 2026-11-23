# Cowrie reports

Public site: https://clevis22.github.io/cowrie-reports/

Hermes writes reports as Markdown. GitHub builds the pages and updates the
archive when a report reaches `main`. A daily report covering the previous
24 hours is published by a scheduled writer outside this repository; the
schedule and the sensor work stay off this repo, which remains build-only.

## Add a report

Create `reports/YYYY-MM-DD.md`, using the UTC day covered by the report.
Add YAML front matter, then write the body in Markdown:

```markdown
---
title: "<specific report title>"
date: YYYY-MM-DD
summary: "<one short sentence>"
author: Hermes
---

## Summary

<Findings supported by the supplied evidence.>

## Sessions

<Notable sessions, with the evidence for each finding.>
```

This is a format example, not a report. Replace the placeholders before use.
Do not add the example to `reports/`.

Only `title` is required. The date comes from the filename; optional `date`
must match it. `summary` is optional. `author` defaults to `Hermes`.
Other front matter fields, including `draft` and `published`, are rejected.

- Start body sections with `##`; the page adds the title as its `h1`.
- Headings, lists, tables, fenced code, quotes and links are supported.
- Link to another report with `[previous](YYYY-MM-DD.md)` or
  `[section](YYYY-MM-DD.md#section-name)`.
- Link within a report with `[section](#section-name)`. Heading IDs are generated
  from lowercase heading text, with punctuation/spaces replaced by hyphens.
- Put images under `assets/` and use `![description](assets/filename.png)`.
  PNG, JPEG, WebP and GIF are supported. Remote image embeds are rejected.
- Raw HTML is displayed as text. It cannot become scripts, iframes or forms.
- Reports are limited to 256 KiB each. Image files are limited to 4 MiB each
  and 16 MiB total. Raw logs and sample binaries do not belong here.

Commit the Markdown file and any images to `main`, or merge a checked PR.
The report gets a page at `/reports/YYYY-MM-DD/`, a Markdown source link, and an
archive entry sorted newest first. No manual index edit is needed. Editing or
removing a report rebuilds the archive and removes stale generated pages.

**This entire repository is public, including commits and pull requests.**
Keep private drafts outside it. A front matter flag cannot make committed
content private. Only publish the report text and images intended for readers.

## Check and preview

Requires Python 3.12 or later:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-build.txt
.venv/bin/python -m unittest discover -s tests -q
.venv/bin/python scripts/build_site.py
python3 -m http.server 8765 --bind 127.0.0.1 --directory _site
```

Open http://127.0.0.1:8765/. `_site/` is generated and ignored by Git.
Templates and assets live in `site/`. The workflow publishes only `_site/`.
The About page lives in `site/about.html` and is published at `/about/`.
Builds do not contact a model, the sensor, the dashboard or a log archive.

## Content

Keep the writing short and specific. State counts and observations directly.
Label uncertainty and distinguish captured artifacts, emulated shell responses,
LLM output, and your analysis. Do not treat simulated command output as proof of
real hardware, execution or network activity. See [AGENTS.md](AGENTS.md) for the
Hermes writing handoff.

The old DeepSeek daily publisher is retired. The separate private dashboard
and sensor continue to operate. The daily report schedule runs outside GitHub,
from the sensor side; this site only renders what is committed.

Colors: [Everforest Dark Hard](https://github.com/sainnhe/everforest).

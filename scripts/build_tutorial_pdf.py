"""Render a tutorial Markdown file as a print-quality PDF.

    uv run --with weasyprint --with markdown python scripts/build_tutorial_pdf.py \
        docs/tutorials/plaud-ubuntu.md docs/tutorials/plaud-ubuntu.pdf

The Markdown is the single source of truth: the same file is published on the
documentation site. This script adds a cover page and print styling on top of it.
Web fonts are fetched when the network allows and fall back to system faces
otherwise, so an offline build still produces a correct document.
"""

import argparse
import re
import sys
from pathlib import Path

import markdown
from weasyprint import HTML

REPO_ROOT = Path(__file__).resolve().parent.parent
COVER_IMAGE = REPO_ROOT / "docs" / "assets" / "open-transcribe-hero.jpg"

STYLESHEET = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');

:root {
  --ink: #14182c;
  --muted: #5c6480;
  --rule: #dfe3ee;
  --teal: #0f7f92;
  --violet: #8a35a8;
  --night: #0d1020;
  --wash: #f6f8fc;
}

@page {
  size: A4;
  margin: 22mm 20mm 20mm 20mm;
  @bottom-center {
    content: counter(page);
    font-family: Inter, 'DejaVu Sans', sans-serif;
    font-size: 8.5pt;
    color: #8b93ab;
  }
  @bottom-right {
    content: 'OpenTranscribe MCP';
    font-family: Inter, 'DejaVu Sans', sans-serif;
    font-size: 8pt;
    color: #b3b9cc;
  }
}

@page cover {
  margin: 0;
  @bottom-center { content: none; }
  @bottom-right { content: none; }
}

html, body { margin: 0; padding: 0; }

body {
  font-family: Inter, 'DejaVu Sans', sans-serif;
  font-size: 10.2pt;
  line-height: 1.62;
  color: var(--ink);
  hyphens: none;
}

/* ---------- cover ---------- */

.cover {
  page: cover;
  break-after: page;
  background: var(--night);
  color: #ffffff;
  height: 297mm;
  position: relative;
}

.cover-art { width: 210mm; display: block; }

.cover-text { padding: 14mm 20mm 0 20mm; }

.cover-eyebrow {
  font-size: 9pt;
  font-weight: 600;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: #4fd4e4;
  margin: 0 0 7mm 0;
}

.cover-title {
  font-size: 30pt;
  font-weight: 700;
  line-height: 1.12;
  letter-spacing: -0.02em;
  margin: 0 0 6mm 0;
  color: #ffffff;
}

.cover-subtitle {
  font-size: 13pt;
  font-weight: 400;
  line-height: 1.45;
  color: #b9c0d8;
  margin: 0;
  max-width: 130mm;
}

.cover-rule {
  width: 28mm;
  height: 3px;
  background: linear-gradient(90deg, #4fd4e4, #c05ce0);
  margin: 10mm 0;
}

.cover-foot {
  position: absolute;
  bottom: 18mm;
  left: 20mm;
  right: 20mm;
  font-size: 9pt;
  color: #7d86a3;
  border-top: 1px solid #262b45;
  padding-top: 4mm;
}

/* ---------- headings ---------- */

h1 {
  font-size: 19pt;
  font-weight: 700;
  letter-spacing: -0.015em;
  line-height: 1.2;
  margin: 0 0 6mm 0;
  color: var(--ink);
}

h2 {
  font-size: 14pt;
  font-weight: 650;
  letter-spacing: -0.01em;
  margin: 7.5mm 0 3.5mm 0;
  padding-bottom: 2mm;
  border-bottom: 2px solid var(--teal);
  color: var(--ink);
  break-after: avoid;
}

h3 {
  font-size: 11.4pt;
  font-weight: 650;
  margin: 6mm 0 2.5mm 0;
  color: var(--teal);
  break-after: avoid;
}

p { margin: 0 0 3.2mm 0; orphans: 2; widows: 2; }

a { color: var(--teal); text-decoration: none; border-bottom: 1px solid #b9dde3; }

strong { font-weight: 650; }

hr {
  border: none;
  border-top: 1px solid var(--rule);
  margin: 5.5mm 0;
}

/* ---------- lists ---------- */

ul, ol { margin: 0 0 3.5mm 0; padding-left: 6mm; }
li { margin-bottom: 1.6mm; padding-left: 1mm; }
li::marker { color: var(--teal); font-weight: 600; }

/* ---------- code ---------- */

code {
  font-family: 'JetBrains Mono', 'DejaVu Sans Mono', monospace;
  font-size: 8.7pt;
  background: #eef1f8;
  padding: 0.4mm 1.1mm;
  border-radius: 2px;
  color: #2b3150;
}

pre {
  background: #f7f9fc;
  border: 1px solid var(--rule);
  border-left: 3px solid var(--teal);
  border-radius: 3px;
  padding: 3.4mm 4mm;
  margin: 0 0 4mm 0;
  break-inside: avoid;
  white-space: pre-wrap;
  word-break: break-word;
}

pre code {
  background: none;
  padding: 0;
  font-size: 8.4pt;
  line-height: 1.5;
  color: #1f2540;
}

/* ---------- tables ---------- */

table {
  width: 100%;
  border-collapse: collapse;
  margin: 0 0 5mm 0;
  font-size: 9.2pt;
  break-inside: avoid;
}

/* A long table may span pages, but never mid-row, and its header repeats. */
table.long { break-inside: auto; }
thead { display: table-header-group; }
tr { break-inside: avoid; }

thead th {
  background: var(--night);
  color: #ffffff;
  font-weight: 600;
  text-align: left;
  padding: 2.4mm 3mm;
  font-size: 8.8pt;
  letter-spacing: 0.01em;
}

tbody td {
  padding: 2.4mm 3mm;
  border-bottom: 1px solid var(--rule);
  vertical-align: top;
}

tbody tr:nth-child(even) { background: var(--wash); }

/* ---------- admonitions ---------- */

.admonition {
  break-inside: avoid;
  margin: 0 0 4.5mm 0;
  padding: 3.2mm 4mm 2.2mm 4mm;
  border-radius: 3px;
  border-left: 3px solid var(--teal);
  background: #f1f7f9;
  font-size: 9.6pt;
}

.admonition p { margin-bottom: 2mm; }
.admonition p:last-child { margin-bottom: 0; }

.admonition-title {
  font-weight: 650;
  font-size: 9.4pt;
  margin-bottom: 1.6mm !important;
  color: var(--teal);
}

.admonition.tip { border-left-color: var(--violet); background: #f8f2fa; }
.admonition.tip .admonition-title { color: var(--violet); }

.admonition.warning { border-left-color: #c2681a; background: #fdf5ec; }
.admonition.warning .admonition-title { color: #a9560f; }
"""

COVER_TEMPLATE = """
<section class="cover">
  <img class="cover-art" src="{image}" alt="">
  <div class="cover-text">
    <p class="cover-eyebrow">OpenTranscribe MCP</p>
    <h1 class="cover-title">{title}</h1>
    <div class="cover-rule"></div>
    <p class="cover-subtitle">{subtitle}</p>
  </div>
  <div class="cover-foot">{foot}</div>
</section>
"""

FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def split_front_matter(text: str) -> tuple[dict[str, str], str]:
    match = FRONT_MATTER.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip().strip("\"'")
    return meta, text[match.end() :]


def drop_leading_h1(text: str) -> str:
    """The cover carries the title, so the first body heading would repeat it."""
    return re.sub(r"\A\s*#\s+.*\n", "", text, count=1)


LONG_TABLE_ROWS = 6


def mark_long_tables(html: str) -> str:
    """Short tables stay whole; only a table too tall for one page may split."""

    def replace(match: re.Match[str]) -> str:
        table = match.group(0)
        if table.count("<tr>") <= LONG_TABLE_ROWS:
            return table
        return table.replace("<table>", '<table class="long">', 1)

    return re.sub(r"<table>.*?</table>", replace, html, flags=re.DOTALL)


def build(source: Path, destination: Path) -> None:
    raw = source.read_text(encoding="utf-8")
    meta, body = split_front_matter(raw)
    title = meta.get("title", source.stem.replace("-", " ").title())
    subtitle = meta.get("subtitle", "")

    html_body = markdown.markdown(
        drop_leading_h1(body),
        extensions=["admonition", "tables", "fenced_code", "attr_list", "sane_lists"],
    )
    html_body = mark_long_tables(html_body)
    cover = COVER_TEMPLATE.format(
        image=COVER_IMAGE.as_uri(),
        title=title,
        subtitle=subtitle,
        foot="Apache-2.0 · github.com/fbossiere/open-transcribe-mcp",
    )
    document = (
        f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        f"<title>{title}</title><style>{STYLESHEET}</style></head>"
        f"<body>{cover}<main>{html_body}</main></body></html>"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=document, base_url=str(REPO_ROOT)).write_pdf(destination)
    print(f"Wrote {destination} ({destination.stat().st_size / 1024:.0f} kB)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if not args.source.is_file():
        sys.exit(f"No such file: {args.source}")
    build(args.source, args.destination)


if __name__ == "__main__":
    main()

"""Set the documentation in docs/ as PDFs.

    python tools/make_pdfs.py              # into docs/pdf/
    python tools/make_pdfs.py --into ~/Desktop

Markdown is for the repository; a PDF is what you hand to somebody. The files
under docs/ stay the source — nothing here is ever written back into them.

**Chrome does the typesetting, not Qt.** PySide6 is already a dependency and
its QTextDocument renders markdown straight to PDF, tables included, so it
looks like the obvious route. It has no page numbers and no control over page
breaks, which is fine for a note and not fine for a forty-page manual that
somebody prints. Headless Chrome applies real CSS, and the stylesheet below
is where the look lives.

Chrome is the only thing this needs that the project does not already have,
and it is on both target platforms. Where it is missing the script says so
and falls back to Qt rather than producing nothing.
"""

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"

#: Where Chrome usually is. The first one that exists wins.
CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
)

#: Print styling. A4, a serif face for running text because these are read on
#: paper, and monospace kept small enough that a parameter name never breaks
#: a table column. Tables get a repeating header row: a parameter list that
#: runs over a page boundary is unreadable without one.
STYLESHEET = """
@page {
    size: A4;
    margin: 22mm 20mm 20mm 20mm;
    @bottom-center { content: counter(page); }
}
body {
    font-family: "Palatino", "Palatino Linotype", Georgia, serif;
    font-size: 10.5pt;
    line-height: 1.5;
    color: #1a1a1a;
    hyphens: auto;
}
h1 {
    font-size: 21pt; font-weight: normal; letter-spacing: -0.01em;
    margin: 0 0 0.2em; padding-bottom: 0.25em;
    border-bottom: 2px solid #2f6f4f;
}
h2 {
    font-size: 15pt; font-weight: normal; color: #2f6f4f;
    margin: 1.8em 0 0.5em; page-break-after: avoid;
}
h3 {
    font-size: 12pt; font-weight: bold;
    margin: 1.3em 0 0.4em; page-break-after: avoid;
}
h2 + p, h3 + p { margin-top: 0; }
p { margin: 0 0 0.7em; text-align: justify; }
ul, ol { margin: 0 0 0.8em 1.2em; padding: 0; }
li { margin-bottom: 0.3em; }

/* A table that runs over a page boundary keeps its header. Without this a
   parameter list on page two is a grid of numbers with no column names. */
table {
    border-collapse: collapse;
    width: 100%;
    margin: 0.8em 0 1.2em;
    font-size: 9.5pt;
    page-break-inside: auto;
}
thead { display: table-header-group; }
tr { page-break-inside: avoid; }
th {
    background: #eef3f0;
    border-bottom: 1.5px solid #2f6f4f;
    text-align: left; padding: 5px 8px;
    font-weight: bold;
}
td { border-bottom: 0.5px solid #d4d4d4; padding: 5px 8px; vertical-align: top; }

code {
    font-family: "SF Mono", Menlo, Consolas, monospace;
    font-size: 0.87em;
    background: #f2f2ef;
    padding: 0.1em 0.3em;
    border-radius: 2px;
}
pre {
    background: #f7f7f5;
    border-left: 3px solid #2f6f4f;
    padding: 9px 12px;
    margin: 0.8em 0 1.2em;
    page-break-inside: avoid;
    overflow-wrap: break-word;
}
pre code { background: none; padding: 0; font-size: 8.5pt; line-height: 1.4; }

blockquote {
    margin: 1em 0; padding: 0.6em 1em;
    background: #fbf7ec;
    border-left: 3px solid #c9a227;
    page-break-inside: avoid;
}
blockquote p:last-child { margin-bottom: 0; }

a { color: #1f5c8b; text-decoration: none; }
hr { border: none; border-top: 0.5px solid #cfcfcf; margin: 1.6em 0; }

/* The footer of every document: where it came from, so a printed page that
   has been lying around for a year can still be placed. */
.provenance {
    margin-top: 2.5em; padding-top: 0.6em;
    border-top: 0.5px solid #cfcfcf;
    font-size: 8.5pt; color: #6a6a6a;
}
"""


def chrome() -> Path | None:
    for candidate in CHROME_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            return path
    found = shutil.which("google-chrome") or shutil.which("chromium")
    return Path(found) if found else None


def version() -> str:
    source = REPO / "src" / "biofermentation" / "__init__.py"
    for line in source.read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip('"')
    return "0.0"


def to_html(source: Path) -> str:
    """One markdown file as a complete HTML document.

    Links between the documents are rewritten to their PDF names — target and
    visible text both. A reader who has this folder has all of them, and a
    link that reads "architecture.md" points at a file they do not have.

    Only inside an anchor, though. The prose names the markdown files on
    purpose in a few places: they are the source, and someone who wants to
    change something changes them, not the PDF.
    """
    import re

    import markdown

    text = source.read_text(encoding="utf-8")
    body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "sane_lists", "attr_list"],
        output_format="html5",
    )
    stems = {other.name: other.stem for other in DOCS.glob("*.md")}

    def to_pdf(match: re.Match) -> str:
        name = match.group("target")
        stem = stems.get(name.rsplit("/", 1)[-1])
        if stem is None:
            return match.group(0)
        inner = match.group("text").replace(name.rsplit("/", 1)[-1], f"{stem}.pdf")
        return f'<a href="{stem}.pdf">{inner}</a>'

    body = re.sub(
        r'<a href="(?P<target>[^"]+\.md)">(?P<text>.*?)</a>', to_pdf, body, flags=re.S
    )
    title = source.stem.replace("_", " ").capitalize()
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{title}</title>
<style>{STYLESHEET}</style></head><body>
{body}
<p class="provenance">Biofermentation Simulation {version()} —
aus <code>docs/{source.name}</code>, erzeugt mit
<code>tools/make_pdfs.py</code>. Die Markdown-Datei ist die Quelle; wer etwas
ändern will, ändert sie und erzeugt neu.</p>
</body></html>"""


def render_with_chrome(browser: Path, html: str, target: Path) -> bool:
    with tempfile.TemporaryDirectory() as work:
        page = Path(work) / "page.html"
        page.write_text(html, encoding="utf-8")
        result = subprocess.run(
            [
                str(browser),
                "--headless",
                "--disable-gpu",
                "--no-pdf-header-footer",
                f"--print-to-pdf={target}",
                page.as_uri(),
            ],
            capture_output=True,
            text=True,
            check=False,
            # A browser that hangs must not hang the build.
            timeout=120,
        )
    if target.is_file() and target.stat().st_size > 0:
        return True
    print(f"  Chrome reported: {(result.stderr or result.stdout).strip()[:200]}")
    return False


def render_with_qt(source: Path, target: Path) -> bool:
    """The fallback: no page numbers, but a PDF.

    Qt parses the markdown itself (QTextDocument.setMarkdown), so this path
    needs nothing that is not already a dependency of the application.
    """
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QMarginsF
    from PySide6.QtGui import QPageSize, QPdfWriter, QTextDocument
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    document = QTextDocument()
    document.setMarkdown(source.read_text(encoding="utf-8"))
    writer = QPdfWriter(str(target))
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setPageMargins(QMarginsF(18, 18, 18, 18))
    document.setPageSize(
        writer.pageLayout().paintRectPixels(writer.resolution()).size().toSizeF()
    )
    document.print_(writer)
    return target.is_file()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--into", type=Path, default=DOCS / "pdf", help="output folder")
    arguments = parser.parse_args()
    target_dir = arguments.into.expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)

    browser = chrome()
    if browser is None:
        print("No Chrome found — falling back to Qt, so without page numbers.")
    else:
        print(f"Typesetting with {browser.name}")

    sources = sorted(DOCS.glob("*.md"))
    if not sources:
        print(f"No markdown files in {DOCS}")
        return 1

    written = 0
    for source in sources:
        target = target_dir / f"{source.stem}.pdf"
        ok = (
            render_with_chrome(browser, to_html(source), target)
            if browser is not None
            else render_with_qt(source, target)
        )
        if ok:
            written += 1
            print(f"  {target.name:34} {target.stat().st_size // 1024:5} KB")
        else:
            print(f"  {target.name:34} FAILED")

    print(f"\n{written} of {len(sources)} files in {target_dir}")
    return 0 if written == len(sources) else 1


if __name__ == "__main__":
    raise SystemExit(main())

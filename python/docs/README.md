# Documentation

Five documents, one per question.

| You want to… | Read |
|---|---|
| **operate** the application | [`manual.md`](manual.md) |
| **install** or distribute it | [`installation.md`](installation.md) |
| know how it is **built** | [`architecture.md`](architecture.md) |
| **develop it further** | [`development.md`](development.md) |
| know whether the **numbers hold up** | [`verification_escherichia_coli.md`](verification_escherichia_coli.md) |

And, one level up: [`../CLAUDE.md`](../CLAUDE.md) — *why* the application is
built the way it is. Every rule with its reason and every measurement with its
number. It is the file an AI assistant reads first, and the one new findings
belong in. It is the only file here still written in German.

## Ten minutes to get started

1. [`installation.md`](installation.md) → start the application
2. [`manual.md`](manual.md), section 2 → create a first project, inoculate it,
   let it run
3. [`manual.md`](manual.md), section 4 → understand the five controllers

Anyone who wants to carry on from there takes
[`development.md`](development.md) — it also holds the finished starter prompt
for a version 4 with Claude Code.

## As PDF

For everyone who would rather read on paper or in a reader:

```bash
pip install -e ".[docs]"
python tools/make_pdfs.py
```

That creates `docs/pdf/` — one typeset PDF each, with page numbers, 31 pages
together. Typesetting is done with Chrome in the background; if it is missing,
the tool falls back to Qt and says so. The PDFs are not in the repository: they
can be regenerated at any time, and as binaries in the history they would only
be noise.

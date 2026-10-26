# Proofing a book

A build that compiles is not a finished book.  Proof it the way a
production editor would: read the report, then look at every page.

## Contents

- [1. The report](#1-the-report)
- [2. Contact sheets](#2-contact-sheets)
- [3. Pages at reading size](#3-pages-at-reading-size)
- [4. Fixes by symptom](#4-fixes-by-symptom)
- [5. Before you hand it over](#5-before-you-hand-it-over)

## 1. The report

`book.py build` ends with a summary and writes `book-build/report.json`:

| item | aim | what to do |
|---|---|---|
| overfull lines | 0 | see "Text runs into the margin" below |
| missing glyphs | none | add a font with `fallback_fonts` (CJK, Devanagari …) |
| undefined references | none | a link or `\ref` target that is not in the book; fix the source link, or accept plain text |
| unknown directives | each decided | `directives:` in book.yaml (drop / keep / code / aside) |
| warnings | read them all | images not found, unmatched `$`, empty chapters, assumed copyright |

`python scripts/proof.py BOOK.pdf` repeats the counts and adds font
embedding (every font must be embedded, none Type 3) and blank pages
(versos before chapters and parts are expected; others are not).

## 2. Contact sheets

`proof.py BOOK.pdf` writes sheet-01.png, sheet-02.png … (24 pages each)
next to the PDF.  Open every sheet with the Read tool.  Look for:

- the cover, half-title, title page, copyright page, contents: complete,
  spelt right, nothing overlapping, no empty subtitle line;
- chapter openers on right-hand pages, part pages alone;
- pages that are mostly empty in the middle of a chapter (a figure or a
  long unbreakable box pushed to the next page);
- boxes or tables that stick out of the text block;
- stray raw markup: `\begin{…}`, `:::`, `{.class}`, `{{ }}`, `:role:`,
  `.. directive::`, HTML tags, unresolved `[label]`;
- grey "Image not available" boxes;
- the index: entries that are noise (common words), duplicated entries,
  entries without pages.

## 3. Pages at reading size

`proof.py BOOK.pdf --pages 23,57,120 --dpi 100` renders single pages;
`--find "phrase"` tells you where something is.  Check a few of each kind
of page the book has: prose, code, outputs and tables, maths, API entries,
figures, admonitions, the first index page.

## 4. Fixes by symptom

Fix through book.yaml first; never edit the user's sources unless they ask.

**Text runs into the margin (overfull lines).**  The report names the
chapter.  Long URLs and identifiers in prose break by themselves; what is
left is usually a table with long unbreakable cells (pandoc gives wide
tables wrapping columns automatically; a grid table in the source with
narrow fixed widths can still overflow), or a very long formula (display
maths is scaled to fit; inline maths is not: rarely worth fixing), or an
image given an absolute width in the source (images are capped at the text
width).  Under 3pt is invisible in print; leave it.

**A directive printed as code or as text.**  The report lists it under
"directives without a book equivalent".  Decide what it is for: a build-time
code runner whose output you cannot reproduce → `drop`; a box or callout →
`aside:Label`; example code → `code:python`; a wrapper → `keep`.

**A chapter that should not be there** (search page, list of links,
"edit on GitHub" stub, tag index): remove it from book.yaml.  An empty
chapter is left out automatically.

**Boilerplate sections at the end of every chapter** ("Contribute",
"Edit this page", "Next steps" link lists): `drop_sections: ["^Contribute$"]`.

**Titles numbered twice** ("Chapter 3 · 03 Basics"): numbering is stripped
from titles by default; for unusual patterns set `title:` on the entry.

**Running head too long**: chapter heads over ~46 characters are
shortened automatically; give a `title:` if the cut is awkward.

**Wrong or missing title, author, subtitle**: set them in book.yaml.  The
copyright line is generated when none is given and the report says so:
confirm it with the user or set `copyright:`.

**Notebook plots look soft**: offer `scripts/figures.py`
(references/vector-figures.md).

**Missing outputs** (a notebook or Quarto book shows code but no results):
the sources were saved without outputs.  Executing them is the user's
call: it needs their environment and data.

**API entries say "not found in the source"**: set `code_roots:` to the
folder that holds the package (the folder containing `mypkg/`, often
`../src`).  Names created at run time cannot be found statically.

## 5. Before you hand it over

- 0 overfull lines (or only sub-3pt ones), 0 missing glyphs, all fonts embedded.
- Every unknown directive decided; every warning read.
- Every contact sheet looked at, and the pages that looked wrong fixed and
  looked at again.
- Tell the user what you assumed (copyright line, titles you changed,
  chapters you left out, directives you dropped) and what the book does
  not contain (unexecuted outputs, API entries that could not be found).

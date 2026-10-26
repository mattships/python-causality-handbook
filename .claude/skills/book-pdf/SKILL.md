---
name: book-pdf
description: Typeset documentation, notebooks, manuscripts or a code base as a publisher-quality PDF book (cover, title and copyright pages, contents, numbered chapters and parts, running heads, highlighted code, booktabs tables, notes, index, colophon), with pandoc and LuaLaTeX. Use this whenever someone wants a PDF, book, print edition, e-book PDF or "nicely typeset" document from Jupyter notebooks or a Jupyter Book, Sphinx or Read the Docs docs (reStructuredText or MyST), MkDocs/Material, Docusaurus, VitePress, mdBook or GitBook sites, Quarto or bookdown books, Markdown, R Markdown, HTML, Word (.docx), OpenDocument, EPUB, LaTeX, Org files, or a folder or repository of source code (a code book of listings). Also use it for "make a PDF of this repo/docs/notebooks", "turn this into a book", "a printable version", "typeset like a publisher" and for improving or re-styling a PDF this skill made, even when the user does not say "book".
---

# book-pdf

Turns any source into the same standard of book: the design of a good
technical publisher, applied to whatever the user has.  The scripts do the
conversion and the typesetting; your job is the editor's: choose what goes
in the book and in what order, decide what the converter could not, and
proof the result before you hand it over.

Everything runs from this skill's folder (`scripts/`, `assets/`).  Below,
`$SKILL` stands for that folder's path.

## 1. Check the toolchain

```bash
python3 $SKILL/scripts/book.py doctor
```

It needs pandoc 3.1+, LuaLaTeX with latexmk and makeindex, the TeX fonts
(XCharter, Fira Sans, Inconsolata), and pyyaml, pillow, beautifulsoup4,
lxml and pypdf.  On Debian/Ubuntu that is
`apt-get install pandoc texlive-luatex texlive-latex-extra texlive-fonts-extra texlive-science latexmk librsvg2-bin poppler-utils fonts-dejavu-core`
and `pip install pyyaml pillow beautifulsoup4 lxml pypdf`; doctor prints
the commands for what is missing.  Installing TeX Live takes a few minutes
and about 2 GB: tell the user before you start.

## 2. Propose the book

```bash
python3 $SKILL/scripts/book.py init PATH -o book.yaml
```

PATH is a project folder, a docs folder or a single file.  init recognises
Jupyter Book, Quarto, bookdown, MkDocs, mdBook/GitBook and Sphinx projects
(also in `docs/` or a subfolder), otherwise lays out a folder of documents
or, for a code repository, a code book.  It writes book.yaml (keep it next
to where the PDF should go, not inside the user's sources unless they want
it there) and prints notes.

Then read book.yaml as an editor would, and fix it:

- **Metadata.** Title, subtitle (write one if the project has a one-line
  description; it is on the cover), author.  If `copyright:` was guessed,
  say so to the user.
- **Order and scope.** Chapters in reading order; front matter (preface,
  introduction) under `front:`; reference material and changelogs under
  `appendix:`.  Leave out what a reader of a printed book does not need:
  site-only pages (link lists, "edit this page", search, tag indexes),
  release-note archives the user did not ask for, generated or vendored
  code, test fixtures.
- **Parts.** Use parts only when there are at least two real groups.
- For a single long document `split: true` is set; check that the
  resulting chapters make sense after the first build.

The full list of keys is in `references/config.md`; what each source
format supports, and what it cannot do, is in `references/formats.md`.
Read the section for your input before deciding.

## 3. Build

```bash
python3 $SKILL/scripts/book.py build book.yaml              # whole book
python3 $SKILL/scripts/book.py build book.yaml --only 3,A   # chapters 3 and A -> *-preview.pdf
python3 $SKILL/scripts/book.py build book.yaml --no-pdf     # conversion only (fast)
```

A 300-page book takes 3 to 6 minutes (LuaLaTeX runs several passes); run
long builds in the background and use `--no-pdf` and `--only` while you
iterate.  Build files go to `book-build/` (the LaTeX is readable there if
you need to see what a page was made from).

The build ends with a report: page count, overfull lines by chapter,
missing glyphs, undefined references, directives it could not map, and
warnings (images not found, an unmatched `$`, empty chapters left out,
assumed copyright).  Deal with every item, mostly through book.yaml:

| report item | usual fix |
|---|---|
| unknown directive | `directives: {name: drop \| keep \| code:lang \| aside:Label}`; drop build-time code runners whose output cannot be reproduced |
| boilerplate section in every chapter | `drop_sections: ["^Contribute$"]` |
| API object "not found in the source" | `code_roots:` pointing at the folder that contains the package |
| missing glyphs | `fallback_fonts: [...]` (e.g. a Noto CJK font) |
| image not found | check the path; add `image_dirs:` |
| overfull lines | see references/qa.md; under 3 pt is invisible |

Do not edit the user's source files to make the book come out right unless
they ask you to; the configuration exists so that you do not have to.

## 4. Proof

```bash
python3 $SKILL/scripts/proof.py BOOK.pdf                      # checks + contact sheets
python3 $SKILL/scripts/proof.py BOOK.pdf --pages 1-8,57 --dpi 100
python3 $SKILL/scripts/proof.py BOOK.pdf --find "some phrase"
```

Look at every contact sheet with the Read tool, then at reading size at a
few pages of each kind (prose, code, tables, maths, figures, API entries,
the index).  You are looking for raw markup that leaked through, boxes that
stick out, mostly empty pages, wrong titles, noise in the index.  The
checklist and the fix for each symptom are in `references/qa.md`.  Fix,
rebuild, and look again at the pages you fixed.

## 5. Optional finishing

- **A curated index.** The automatic index (chapter topics with page
  ranges, defined terms, acronyms, recurring emphasised phrases, API names)
  is decent; a curated one is better for a book people will keep.  Run
  `python3 $SKILL/scripts/suggest_index.py book.yaml > index.yaml`, keep
  the 80 to 250 terms a reader would look up, merge variants with `match`,
  nest with `parent!child`, add `see:` cross-references, set
  `index: index.yaml` (format in references/config.md).
- **Vector plots for notebooks.** `scripts/figures.py` re-draws matplotlib
  PNGs as vector PDFs by re-executing the notebooks; it needs their
  dependencies and some time.  Offer it when print quality matters; see
  `references/vector-figures.md`.
- **Design knobs.** `trim` (7x10 default; 6x9, a4, letter, …), `fonts`
  (charter, libertinus, stix, lm), `accent` colour, `cover_image`,
  `language`.  The design itself is fixed: every book gets the same
  standard.  For a genuine house-style change see `references/design.md`.

## 6. Hand it over

Put the PDF where the user can open it, and tell them in a few lines: the
page count and structure, what you left out or renamed and why, what you
assumed (copyright line, titles), what the book cannot contain (outputs of
notebooks saved without them, API objects created at run time), and the
optional improvements (curated index, vector plots) if you did not do them.
Keep book.yaml with the PDF: rebuilding later is one command.

## Notes

- Sources are never executed: what is stored (notebook outputs, Quarto's
  `_freeze/`) is what is printed.
- Links to other chapters become internal links; links to files outside
  the book use `link_base` (set from the git remote) or become plain text;
  web links keep their wording and get the URL as a footnote.
- Cross-references print as the publisher would: "Chapter 3",
  "Appendix A", the section's title, "Figure 3.1", "(2.1)".
- The scripts are plain Python 3.9+ with no third-party dependency beyond
  those listed above; read them when behaviour surprises you
  (`references/design.md` maps the files).

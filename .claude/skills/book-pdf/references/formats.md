# Source formats

What `book.py` does with each kind of source, and what it cannot do.  Read
the section for the sources in front of you before reviewing book.yaml.

## Contents

- [Projects](#projects) — how `init` finds the structure
- [Jupyter notebooks](#jupyter-notebooks)
- [Markdown dialects](#markdown-dialects) — CommonMark/GFM, MyST, MkDocs, Docusaurus, VitePress
- [Quarto and R Markdown](#quarto-and-r-markdown)
- [reStructuredText and Sphinx](#restructuredtext-and-sphinx)
- [Word, OpenDocument, EPUB, HTML](#word-opendocument-epub-html)
- [LaTeX](#latex)
- [Source code (code books)](#source-code-code-books)
- [Other formats](#other-formats)

## Projects

`init` looks, in this order, for: `_toc.yml` (Jupyter Book), `_quarto.yml`
with `type: book`, `_bookdown.yml`/`index.Rmd`, `mkdocs.yml` (its `nav`),
`SUMMARY.md` (mdBook, GitBook), a Sphinx `conf.py` (the root document's
toctrees; a toctree's caption, or the heading above it, names the part).
It searches the folder, `docs/`, `doc/` and subfolders two levels down.
Without any of these it lays out a docs folder (README/index first, one
part per subfolder) or, when the folder is mostly code, a code book.

It moves changelogs, licences, contributing guides, FAQs and glossaries to
the appendix, drops pages that only exist on websites (genindex, search,
404), and leaves out a site's home page when it is only a logo and links.
Always read the proposed book.yaml: reorder, retitle, drop pages a reader
of the printed book does not need, and fill in the subtitle.

## Jupyter notebooks

- Markdown cells: MathJax maths is made TeX-safe (`$ x $`, `align` inside
  `$$`, `\require`), attachments are extracted, MyST syntax works.
- Code cells become listings in the kernel's language; outputs keep what
  the reader saw: plots (PNG, SVG, PDF), pandas/statsmodels HTML tables as
  booktabs tables (wide ones split into stacked parts), text and errors as
  output blocks (ANSI colours and progress bars cleaned), LaTeX outputs as
  maths.  stderr (warnings) is left out.
- Tags `remove-cell`, `remove-input`/`hide-input`, `remove-output` are honoured.
- Notebooks are not executed: what is stored is what is printed.  A notebook
  saved without outputs prints code only; run it first if results matter.
- Plots stored as PNG print soft.  `scripts/figures.py` re-draws them as
  vector PDFs (see references/vector-figures.md); it takes a kernel with the
  notebooks' dependencies and time, so offer it, do not assume it.

## Markdown dialects

All Markdown is read as CommonMark with tables, footnotes, attributes,
definition lists, task lists and dollar maths, after a text-level pass that
turns site syntax into book elements:

| syntax | becomes |
|---|---|
| GitHub alerts `> [!NOTE]` | note box |
| MyST ```` ```{note} ```` / `:::{warning}`, `{admonition} Title` | note box with the label |
| MyST roles `` {func}`x` ``, `` {ref}`label` ``, `` {doc}`page` `` | code, or a cross-reference ("Chapter 3", the section title) |
| MyST `{toctree}`, `{contents}`, `(label)=`, `% comments` | dropped / heading anchor / dropped |
| MyST `{code-cell}`, `{literalinclude}`, `{include}`, `{eval-rst}`, `{list-table}`, `{csv-table}`, `{figure}`, `{image}`, `{math}` | listing, included text, converted rST, tables, figures, maths |
| MkDocs `!!! note "Title"`, `??? tip` (collapsible), `=== "Tab"` | note boxes; tabs become bold labels with their content in sequence |
| MkDocs `--8<-- "file"` (snippets), `[TOC]`, `{: .class}`, `:material-icon:` | included file / dropped |
| mkdocstrings `::: package.module` | API reference generated from the source (see Sphinx) |
| Docusaurus/VitePress `:::tip Title`, `::: details`, `::: code-group`; MDX imports and `<Tabs>` | note boxes, listings; JSX wrappers removed |
| Quarto `::: {.callout-note}` | note box (title from `title=` or its first heading) |
| raw HTML `<img>`, `<details>`, `<kbd>`, `<br>` | image, bold summary + text, code, line break; other HTML is converted or dropped |

Images: local paths are resolved against the file, the project root and
`image_dirs`; SVG, GIF, WebP, EPS are converted; remote images are
downloaded; badges are dropped; size comes from width/height attributes or
the image's pixels (a 750 px web image fills the text width).  Alt text of
two or more words becomes a caption.

## Quarto and R Markdown

- `_quarto.yml` gives parts, chapters, appendices, title, author,
  bibliography.  Read with pandoc's own Markdown (so `{#sec-x}` ids,
  `[@cite]` and `^super^` work).
- Chunks ```` ```{python} ````, ```` ```{r} ```` become listings; `echo: false` /
  `include: false` chunks are hidden.  Chunks are not run.  If the project
  has `_freeze/` (from `quarto render` with `freeze: auto`), the frozen
  results, figures included, are used instead of the bare source.
- Cross-references `@sec-x`, `@fig-x`, `@tbl-x`, `@eq-x` and bookdown's
  `\@ref(x)` print as "Chapter 3", the section title, "Figure 3.1",
  "Table 2.1", "Equation (2.1)".  Figures and tables with an id are
  numbered; the others are not.
- bookdown `# (PART) Title {-}` headings are not turned into parts
  automatically; move them into book.yaml.

## reStructuredText and Sphinx

- pandoc reads core reST; the Sphinx layer is handled before it: admonitions,
  `versionadded`/`versionchanged`/`deprecated` (note boxes with the
  version), `code-block`, `literalinclude` (with `lines`, `start-after`,
  `end-before`, `dedent`), `include`, `only` (latex/print content kept,
  html dropped), `rubric`, toctrees (dropped; they define the structure),
  roles (`:func:`, `:class:`, `:ref:`, `:doc:`, `:term:`, `:pep:`, …).
- autodoc (`automodule`, `autoclass` with `:members:`, `autofunction`, …)
  and the hand-written `.. function::`/`.. class::` descriptions become API
  entries: signature in code type under a hairline, then the docstring with
  Google/NumPy sections and Sphinx `:param:` fields set as Parameters /
  Returns / Raises lists.  The package is read with `ast` from `code_roots`;
  nothing is imported.  Names created at run time (module `__getattr__`,
  decorators that build classes) cannot be found; the report lists them.
- Unknown directives: content is kept when it looks like prose, set as a
  listing when it looks like code, and listed in the report.  Decide each
  with `directives:` (e.g. a directive that runs code at build time and
  shows its output, like Click's `click:run`, should be dropped).
- Substitutions and custom roles defined in `conf.py` (`rst_epilog`,
  `extlinks`) are not evaluated.

## Word, OpenDocument, EPUB, HTML

- One file is one book: `init` proposes `split: true`, which cuts it into
  chapters at the top heading level (Heading 1 in Word).  Title, subtitle
  and author come from the document's properties or from the title block
  before the first heading.
- Word styles are mapped by pandoc: headings, lists, tables, footnotes,
  equations (OMML), images with their sizes (never wider than the text),
  bold/italic, code (Verbatim/Source Code styles).  Text boxes, comments,
  tracked changes and page layout are not carried over.
- HTML: the main content (`<main>`, `<article>`, Sphinx/MkDocs content
  divs) is kept and navigation, headers, footers and scripts are removed.
  A folder of HTML pages (a built site) works like a docs folder, but the
  site's sources give better results when available.

## LaTeX

- pandoc's LaTeX reader: `\part`/`\chapter`/`\section`, environments,
  maths (labelled equations stay numbered and `\eqref` works), figures and
  tables with `\label` are numbered and `\ref` resolves, `\newcommand`
  macros are expanded, `\input` files are read (relative to the main file).
- `\bibliography{refs}` / `\addbibresource{}` with the .bib next to the
  file: citations via citeproc; a hand-written `thebibliography`: numbered
  references.
- Not supported: TikZ pictures and other drawing code (convert them to PDF
  images first), custom document classes' page layout (the book design
  replaces it), packages that change text with macros pandoc does not know.

## Source code (code books)

- `{code: folder}` chapters list every source file of the folder (sub-
  folders with `recursive: true`), `__init__`/`index`/`main` first, then a
  Python package's modules in the order its `__init__` imports them (the
  order a reader meets them), then the rest in natural order; `files:`
  sets the order by hand.  Each file is a section "path" with
  "PYTHON · 1,204 LINES" under it and a numbered, highlighted listing that
  wraps long lines at commas, brackets, dots and operators (a hook arrow
  marks the continuation).
- Functions and classes (Python `def`/`class`, JavaScript `function`, Go
  `func`, Rust `fn`, `struct`, `enum`, …) are indexed at the line that
  defines them, "tokenize (textkit/tokenize.py)", when the book defines 8
  or more of them; private names and tests are left out.  Files over 400 KB, empty files, lock files and generated
  folders (node_modules, build, dist, venv, …) are skipped.
- `init` on a code repository proposes: README as the Introduction, one
  chapter per package folder ("Source" part), test folders in a "Tests"
  part, top-level configuration and the licence in the appendix.  Trim it:
  generated code, vendored libraries, fixtures and data files rarely
  belong in a book.
- 150+ languages are highlighted (pandoc's skylighting); unknown ones are
  set plain.

## Other formats

Read through pandoc: Org mode, Textile, MediaWiki, DokuWiki, DocBook, JATS,
RTF, Typst, FictionBook, OPML, man pages, Muse, txt2tags, Creole, Jira.
AsciiDoc needs `asciidoctor` (converted through DocBook).  Plain text
(LICENSE, NOTICE) is set as paragraphs, or as a listing when it is laid out
in columns.  Anything else: convert it to one of these first (PowerPoint →
not a book; PDF → not a source).

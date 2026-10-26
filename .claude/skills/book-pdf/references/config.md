# book.yaml reference

`book.py init SOURCE` writes a book.yaml with everything it could find out;
every key below is optional except a chapter list.  Paths in chapter entries
are relative to `root`; `root`, `output`, `build_dir`, `license_file`,
`vector_figures` and index files are relative to book.yaml itself.

## Contents

- [Metadata](#metadata) — title, author, copyright, the cover
- [Design knobs](#design-knobs) — trim size, fonts, colour, language
- [Structure](#structure) — front matter, parts, chapters, appendices
- [Chapter entries](#chapter-entries) — files, sections, split files, code
- [Processing](#processing) — index, directives, links, images, maths
- [Bibliographies](#bibliographies)

## Metadata

| key | what it does |
|---|---|
| `title` | Book title (cover, half-title, title page, PDF metadata). Default: the project's own title. |
| `title_line1`, `title_line2` | Split a long title over two lines; line 2 is set in the accent colour on the cover and title page (e.g. "Causal Inference" / "for the Brave and True"). |
| `subtitle` | Italic line under the title. Use `\n` for a line break. |
| `author` | String, or a list (joined with commas). |
| `publisher` | Small capitals at the foot of the title page. |
| `tagline` | One line under the subtitle on the cover. |
| `imprint` | Letter-spaced line at the foot of the cover ("Open-source edition"). |
| `cover_image` | Picture run across the middle of the cover, faded into the dark ground. Wide images work best. |
| `copyright` | Copyright line. Default "Copyright © YEAR AUTHOR." (reported as an assumption). |
| `year` | Year for the default copyright line. |
| `license` | Licence name, printed as "Released under the …". |
| `license_file` | Short licence text (under 2,600 characters) printed in full on the copyright page. |
| `source_url`, `online_url` | Printed on the copyright page. |
| `copyright_extra` | Any further line for the copyright page (ISBN, edition notes). |
| `dedication`, `epigraph` | Optional pages after the copyright page. |
| `colophon` | Text of the last page. Default names the fonts and the tools. |

## Design knobs

The design itself is fixed (that is the point: every book gets the same
publisher standard). These knobs adapt it:

| key | values | default |
|---|---|---|
| `trim` | `7x10` (technical books), `6x9`, `royal` (6.14×9.21), `7x9.19`, `7.5x9.25`, `8x10`, `b5`, `a5`, `a4`, `letter` | `7x10` |
| `fonts` | `charter` (XCharter, Fira Sans, Inconsolata), `libertinus`, `stix` (STIX Two, Source Sans/Code Pro), `lm` (Latin Modern) | `charter` |
| `accent` | hex colour of headings, rules, chapter numbers | `9A1F26` (oxblood) |
| `cover_accent` | hex colour of the second title line on the dark cover | the accent, lightened |
| `language` | babel language name: `english`, `american`, `british`, `brazilian`, `ngerman`, `french`, `spanish`, … (hyphenation and "Chapter"/"Contents" words) | `english` |
| `code_size` | listing size in pt | per trim |
| `keep_lines` | listings shorter than this never split across pages | 14 |
| `fallback_fonts` | extra fonts for glyphs the book's fonts lack, e.g. `[NotoSansCJKsc-Regular]` for Chinese | DejaVu + colour emoji |

Good accents: oxblood `9A1F26`, deep teal `0F5E63`, ink blue `1F4E79`,
forest `2E5E3A`, aubergine `5B2A5E`, burnt orange `A4471B`.  Keep it dark:
it is the colour of headings on white paper.

## Structure

```yaml
root: docs                 # where the sources are
output: My-Book.pdf
build_dir: book-build      # LaTeX, images and logs (keep it; rebuilds reuse nothing else)
front:                     # unnumbered chapters before chapter 1, roman page numbers
  - path: index.md
    title: Preface
parts:                     # or `chapters:` for a book without parts
  - title: Getting Started
    chapters: [quickstart.md, install.md]
  - title: Reference
    chapters: [api.md]
appendix:                  # lettered chapters: Appendix A, B, ...
  - changes.md
back:                      # unnumbered chapters after the appendices (glossary, notes)
  - glossary.md
appendix_title: Appendices # the appendices' part page (only in books with parts)
```

A part needs at least two named parts to make sense; with one, list the
chapters under `chapters:`.  A book gets "Brief Contents" plus "Contents in
Detail" when it has parts and more than eight chapters, or more than 14.

## Chapter entries

```yaml
- quickstart.md                       # a file; its first heading is the title
- path: 01-intro.ipynb
  title: Introduction                 # override the title
- path: guide/index.md
  sections: [guide/a.md, guide/b.md]  # more files folded in as sections
- path: thesis.docx
  split: true                         # one long file -> chapters at its top headings
  lead_title: Preface                 # name for text before the first heading (60+ words)
- code: src/mypkg                     # a chapter of source listings, one section per file
  title: The mypkg package
  recursive: false                    # true: include subfolders
  include: ["*.py"]                   # globs relative to the folder
  exclude: ["*_pb2.py"]
```

Split files: headings that start "Part …" become parts, "Appendix …"
appendices, "References"/"Bibliography" back matter, and "Abstract",
"Preface", "Foreword", "Acknowledgements" front matter.  A heading level that
occurs once at the very top is taken as the book's title.

Titles lose their numbering ("01 - Intro", "3. Methods", "Chapter 2:"),
because the design numbers chapters itself (`strip_numbers: false` keeps
it).  `title_case: true` capitalises plain titles.

## Processing

| key | what it does |
|---|---|
| `index` | `auto` (default): an index of chapter topics (with page ranges), defined terms, acronyms, emphasised phrases the book keeps using, and API names; none for books under ~12,000 words unless they document 15+ API objects. `auto-always`: index even short books. `none`. Or a file name (`index.yaml`, see below) for a curated index. |
| `drop_sections` | regexes; sections whose heading matches are left out, e.g. `["^Table of contents$", "^Edit this page"]`. |
| `directives` | what to do with a directive the report lists as unknown: `drop`, `keep` (content only), `code` / `code:python` (set the body as a listing), `aside` / `aside:Label` (a note box). E.g. `{"click:run": drop, "click:example": "code:python"}`. |
| `link_base` | URL prefix for links to files of the repository that are not in the book (`https://github.com/o/r/blob/main/`). Without it such links become plain text. |
| `fetch_images` | download remote images (default true); badges (shields.io and the like) are always left out. |
| `image_dirs` | extra folders to look in for images with root-relative paths. |
| `default_language` | language of reStructuredText literal blocks (`::`) and notebook code; `plain` for none. Markdown fences without a language are set plain. |
| `myst` | treat all `.md` files as MyST (Jupyter Book and Sphinx+myst_parser projects). |
| `code_roots` | folders where autodoc / mkdocstrings look for the documented Python package (relative to `root`). |
| `vector_figures` | folder written by `figures.py` (vector re-draws of notebook plots). |
| `assets` | a folder with edited copies of design files (see references/design.md); files missing there come from the skill. |

### Curated index (index.yaml)

```yaml
terms:
  - term: average treatment effect (ATE)      # as printed; "a!b" = sub-entry b of a
    match: [average treatment effect, ATE]    # phrases (any case, plurals match) and acronyms (exact)
    home: [ch03]                              # chapters devoted to it: slug, title or file name
  - term: bias!selection
    match: [selection bias]
  - term: instrumental variables (IV)
    match: [instrumental variable, IV]
    exclude: [weak instrument]                # longer phrases that are a different entry
see:
  diff-in-diff: difference-in-differences     # cross-references ("see ...")
```

`python scripts/suggest_index.py book.yaml > index.yaml` lists candidates
(with mention counts) to start from.  Outside its home chapters a term is
indexed at its first mention in each chapter.

## Bibliographies

```yaml
bibliography: references.bib     # or a list; BibTeX, CSL JSON or RIS
csl: chicago-author-date.csl     # optional citation style
bibliography_title: References
```

Citations (`[@key]` in Markdown/Quarto, `\cite{}` in LaTeX with
`\bibliography{}`) are formatted by pandoc's citeproc and one bibliography
is printed as back matter.  LaTeX sources with a hand-written
`thebibliography` get numbered references ([1], [2]) without any of this.

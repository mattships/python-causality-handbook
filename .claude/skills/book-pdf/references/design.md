# The design

Every book gets the same design: a technical-book page modelled on good
trade publishers.  Users choose content and a few knobs (references/config.md);
the design itself lives in `assets/` and should not be changed per book.

## What a book contains

1. Cover (C1): dark ground, author letter-spaced at the top, title in light
   sans (a second title line in the accent colour), a hairline, subtitle and
   tagline at the foot, optional cover image band; inside cover (C2) blank.
2. Half-title, title page, copyright page (licence text when short; "This
   edition was typeset on … from the …"; source revision for git sources),
   optional dedication and epigraph.
3. Brief Contents (books with parts and 9+ chapters, or 15+) and Contents in
   Detail (chapters and sections; chapters with very many sections, like
   changelogs, list the chapter only).
4. Front-matter chapters (unnumbered, roman folios).
5. Parts (a page each) and chapters: opener with "CHAPTER" label, large
   light numeral, hairline, title; sections in accent sans; running heads
   (chapter on the left, section on the right, letter-spaced capitals).
6. Appendices (lettered; their own part page when the book has parts).
7. Back matter: unnumbered chapters, bibliography, index (two columns,
   letter groups, page ranges for chapter topics).
8. Colophon on the last page.

## Typography

- 7×10 in trim with a 5.25 in text block (other trims scale it); 10 pt text on
  11 pt leading; protrusion and font expansion (microtype); no widows or
  orphans; ragged bottom.
- Charter (XCharter) for text, Fira Sans for headings, tables and captions,
  Inconsolata for code; DejaVu and colour emoji as glyph fallbacks.
- Listings: tinted box with an accent rule on the left, syntax colours from
  `book.theme`, long lines wrapped at sensible points with a hook arrow,
  short listings kept on one page, code books numbered.  Outputs: hairline
  on the left, no tint.
- Tables: booktabs rules, sans, right-aligned numbers with tabular figures;
  wide data frames split into stacked parts.
- Links: running-text links keep their wording and get the URL as a
  footnote; in reference lists the URL follows the entry.
- Notes, warnings and "new in version": a light accent box with a
  letter-spaced label.  API entries: signature in code type under a
  hairline, docstring indented.
- Figures never float: they stay where the author put them, shrinking
  slightly rather than leaving a hole at the foot of a page.  Captioned
  when the source gives a caption; numbered when it gives an identifier.

## Files

| file | role |
|---|---|
| `assets/book.sty` | the design: geometry, fonts, headings, boxes, tables, index, hyperref |
| `assets/book.lua` | pandoc filter: how each element is set (links, images, code, tables, asides, maths, index marks) |
| `assets/book.theme` | syntax-highlighting colours |
| `assets/cover.tex`, `titlepages.tex`, `colophon.tex` | the fixed pages, driven by `bookconfig.tex` |
| `assets/book.ist` | makeindex style |
| `scripts/book.py` | doctor / init / build; writes `bookconfig.tex`, `book.tex` |
| `scripts/markup.py`, `notebook.py`, `autodoc.py` | readers' preparation (dialects, notebooks, API docs) |
| `scripts/postprocess.py` | format-independent clean-up of each chapter's pandoc tree |
| `scripts/structure.py` | project detection for `init` |
| `scripts/suggest_index.py`, `proof.py`, `figures.py` | index, proofing, vector figures |

## Changing the design

If a user wants something the knobs do not offer (a different cover, a
house font, numbered sections), make the change in a copy: copy the files
you need from `assets/` into a folder next to their book.yaml, edit them
there, and set `assets: that-folder` in book.yaml.  Files found there are
used first, the skill's own for the rest.  Keep the skill's assets
untouched so other books stay consistent.

# Print edition (PDF)

**[Causal-Inference-for-the-Brave-and-True.pdf](Causal-Inference-for-the-Brave-and-True.pdf)**
is a book-typeset edition of the whole handbook: all 25 chapters, the 5
appendices and the preface, built straight from the notebooks in
`../causal-inference-for-the-brave-and-true`.

| | |
|---|---|
| Trim size | 7 × 10 in, two-sided, chapters open on a right-hand page |
| Type | XCharter and XCharter Math (text and maths), Fira Sans (headings, tables, figures), Inconsolata (code) |
| Front matter | cover, half-title, title and copyright pages, epigraph, brief and detailed contents, preface |
| Back matter | index, colophon |
| Figures | 116 of the 137 plots re-drawn as vector graphics; graphviz diagrams converted to vector PDF |
| PDF | bookmarks for every part, chapter and section; links in the contents and index; URLs as footnotes |

## Rebuilding

Requirements: pandoc ≥ 3.1, TeX Live with LuaLaTeX (the `latex-extra`,
`fonts-extra`, `science` and `pictures` collections cover everything),
`latexmk`, `rsvg-convert`, and Python 3 with `pyyaml`, `beautifulsoup4`,
`lxml`, `pillow` and `pypdf`. On Ubuntu:

```bash
sudo apt-get install pandoc latexmk librsvg2-bin texlive-luatex texlive-latex-extra \
    texlive-fonts-extra texlive-science texlive-pictures
pip install pyyaml beautifulsoup4 lxml pillow pypdf
python3 pdf/build.py                 # about two minutes; writes pdf/Causal-Inference-…pdf
python3 pdf/build.py --only 3,A      # just chapter 3 and appendix A, for proofing
```

`build.py` reads `_toc.yml`, turns every notebook into pandoc Markdown (code
cells become highlighted listings; DataFrame and statsmodels outputs become
booktabs tables; figures and text outputs are kept), runs pandoc with
`filters/book.lua`, and typesets the result with `tex/brave.sty` (the book
design, on the memoir class). The index terms live in
`filters/index_terms.lua`.

## Vector figures

The notebooks store their plots as 72 dpi PNGs. `figures.py` re-executes the
notebooks (with the library versions in `requirements-figures.txt`) to redraw
every plot as a PDF in the book's sans-serif face, and keeps a redrawn figure
only where it shows the same data as the stored one. Every pair was compared
by eye and the decisions are recorded in `figures.py` (`REVIEW`, keyed to a
fingerprint of the stored PNG, so a decision lapses if the notebook output
changes). The 21 plots that did not reproduce (unseeded randomness, cells
that no longer run) keep their original PNGs, so no figure can disagree with
the text around it. The results are committed in `figures/`, so rebuilding
the book does not require running the notebooks:

```bash
python3.11 -m venv venv && venv/bin/pip install -r pdf/requirements-figures.txt
venv/bin/python pdf/figures.py --jobs 3
```

## Editorial notes

- The "Contribute" appeal that closes every chapter online appears once, in
  the preface. Everything else in the notebooks is reproduced.
- Links in running text keep their wording and carry the URL in a footnote;
  in the reference lists the URL follows the link text.
- Prices in Brazilian reais (`R$ 6.52`) are typeset as text, not maths, and a
  stray `$` in chapter 23 is dropped.

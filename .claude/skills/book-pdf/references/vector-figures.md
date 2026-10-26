# Vector figures for notebook plots

Notebook plots are stored as PNGs at screen resolution (72 dpi before 2022,
about 100 dpi since), which print soft.  `scripts/figures.py` re-executes
the notebooks with matplotlib's inline backend emitting PDF too, in the
book's sans face, at the size the plots were first drawn, and swaps in the
vector version wherever it shows the same plot.

## When to offer it

- The book has many matplotlib/seaborn plots and the user cares about print
  quality (a printed or professionally shared edition).
- The notebooks can run: their packages are installable and their data is
  in the repository or downloadable.  Ask before running other people's code
  if it reaches the network or takes long.

## How

```bash
python3 -m venv fig-env
fig-env/bin/pip install -r requirements.txt nbclient ipykernel numpy pillow pypdf fonttools pyyaml
fig-env/bin/python scripts/figures.py book.yaml --jobs 3      # writes vector-figures/
```

Then set `vector_figures: vector-figures` in book.yaml and rebuild.

Pin the versions the notebooks were written with when you can (the repo's
lock file or the year of the last commit): newer pandas/matplotlib change
results and styles.  `PYTHONHASHSEED=0` is set so that set iteration order
is stable.

## Deciding the doubtful ones

Each re-drawn plot is compared with the stored PNG (blurred-thumbnail
colour correlation).  At 0.97 or more, and with the same aspect ratio, it is
accepted.  The rest get a side-by-side sheet in `vector-figures/review/`
(stored on the left, re-drawn on the right) and wait for a decision.  Look
at each sheet:

- same data, small style drift (legend position, tick labels, font, colours
  of a newer default cycle): use it;
- different data (unseeded random draws, a dataset that changed, a model
  that now fits differently): keep the stored figure, or the plot would
  contradict the text and numbers around it.

Record decisions in `vector-figures/review.yaml`:

```yaml
07-Beyond-Confounders:
  c041-0: {png: 59777bef91, use: false, note: histogram tail differs}
  c012-0: {png: 912a2b3951, use: true}
```

(the key, cell id and PNG hash are in `vector-figures/report.json`) and run
`figures.py --reuse` to apply them without executing again.  A decision
holds only while the stored PNG is unchanged.

matplotlib embeds OpenType-CFF fonts in a way strict PDF readers reject;
figures.py rewrites those fonts with TrueType outlines, so the book's PDF
stays valid.

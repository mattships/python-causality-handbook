#!/usr/bin/env python3
"""Typeset *Causal Inference for the Brave and True* as a print-quality PDF.

    python3 pdf/build.py                  # the whole book
    python3 pdf/build.py --only 1,5,A     # a few chapters, for quick proofs
    python3 pdf/build.py --no-pdf         # stop after writing the LaTeX

Pipeline: the notebooks listed in the book's _toc.yml become pandoc
Markdown (code cells as fenced Python; outputs as raw LaTeX tables and
figures, or as plain-text `output` blocks), pandoc turns each chapter into
LaTeX with filters/book.lua, and LuaLaTeX typesets tex/brave.sty around it.

Requirements: pandoc >= 3.1, a TeX Live with LuaLaTeX and the fonts named
in tex/brave.sty, rsvg-convert, and the Python packages pyyaml,
beautifulsoup4, lxml, pillow and pypdf.  The optional vector figures come
from figures.py, which has its own requirements.
"""

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml
from bs4 import BeautifulSoup
from PIL import Image
from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SRC = REPO / "causal-inference-for-the-brave-and-true"
TEX = HERE / "tex"
FILTER = HERE / "filters" / "book.lua"
BUILD = HERE / "build"
VECTOR = HERE / "figures"          # optional vector re-renders, see figures.py
PDF_NAME = "Causal-Inference-for-the-Brave-and-True.pdf"

TEXTWIDTH_PT = 379.0              # \linewidth set by tex/brave.sty
TEXTWIDTH_IN = 5.25

BOOK_TITLE = "Causal Inference for the Brave and True"
AUTHOR = "Matheus Facure Alves"

WARNINGS = []


def warn(msg):
    WARNINGS.append(msg)
    print("  warning:", msg, file=sys.stderr)


# ---------------------------------------------------------------------------
# Table of contents
# ---------------------------------------------------------------------------

class Chapter:
    def __init__(self, path, number, slug, appendix):
        self.path = path
        self.number = number          # "3" or "A"
        self.slug = slug              # "ch03" or "appA"
        self.appendix = appendix
        self.title = None


class Part:
    def __init__(self, caption, appendix, chapters):
        self.caption = caption
        self.appendix = appendix
        self.chapters = chapters

    @property
    def title(self):
        # "Part I - The Yang" -> "The Yang"
        return re.sub(r"^Part\s+[IVXLC]+\s*[-:–—]\s*", "", self.caption).strip()


def load_toc():
    toc = yaml.safe_load((SRC / "_toc.yml").read_text())
    parts, number, letters = [], 0, iter("ABCDEFGHIJKLMNOP")
    for part in toc["parts"]:
        files = [c["file"] for c in part["chapters"] if "file" in c]
        if not files:                 # the "Contribute" part only links to Patreon
            continue
        appendix = part["caption"].strip().lower().startswith("appendix")
        chapters = []
        for f in files:
            if appendix:
                num = next(letters)
                chapters.append(Chapter(SRC / f, num, f"app{num}", True))
            else:
                number += 1
                chapters.append(Chapter(SRC / f, str(number), f"ch{number:02d}", False))
        parts.append(Part(part["caption"], appendix, chapters))
    return parts


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

SMALL_WORDS = {"a", "an", "and", "as", "at", "but", "by", "for", "from", "in",
               "into", "nor", "of", "on", "or", "the", "to", "vs", "with"}


def title_case(title):
    words = title.split()
    out = []
    for i, w in enumerate(words):
        after_colon = out and out[-1].endswith(":")
        if i and not after_colon and w.lower() in SMALL_WORDS:
            out.append(w.lower())
        else:
            out.append(w)
    return " ".join(out)


def clean_title(raw):
    return title_case(re.sub(r"^\d+\s*-\s*", "", raw.strip()))


TEX_ESCAPES = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
    "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}", "<": r"\textless{}", ">": r"\textgreater{}",
}


def tex_escape(s):
    return "".join(TEX_ESCAPES.get(ch, ch) for ch in s)


def title_tex(title):
    return tex_escape(title).replace("/", r"\slash{}")


ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def clean_output_text(text):
    text = ANSI.sub("", text)
    lines = []
    for line in text.split("\n"):
        if "\r" in line:              # progress bars redraw with \r
            line = line.rstrip("\r").split("\r")[-1]
        lines.append(line.expandtabs(4).rstrip())
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def source(cell):
    s = cell.get("source", "")
    return "".join(s) if isinstance(s, list) else s


# ---------------------------------------------------------------------------
# Markdown cells
# ---------------------------------------------------------------------------

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def split_fences(text):
    """Split Markdown into (is_code, text) runs so code fences stay untouched."""
    runs, buf, in_code, fence = [], [], False, None
    for line in text.split("\n"):
        m = FENCE.match(line)
        if not in_code and m:
            if buf:
                runs.append((False, "\n".join(buf) + "\n"))
            buf, in_code, fence = [line], True, m.group(1)
        elif in_code and m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) \
                and not line.strip()[len(m.group(1)):].strip():
            buf.append(line)
            runs.append((True, "\n".join(buf) + "\n"))
            buf, in_code, fence = [], False, None
        else:
            buf.append(line)
    if buf:
        runs.append((in_code, "\n".join(buf)))
    return runs


def tokenize_math(par):
    """Split a paragraph into text and maths tokens (MathJax-style dollars)."""
    tokens, i, n, text = [], 0, len(par), []
    while i < n:
        c = par[i]
        if c == "`":                                   # inline code span
            j = i
            while j < n and par[j] == "`":
                j += 1
            k = par.find(par[i:j], j)
            if k < 0:
                text.append(par[i:j])
                i = j
            else:
                text.append(par[i:k + j - i])
                i = k + j - i
            continue
        if c == "\\" and i + 1 < n and par[i + 1] == "$":
            text.append("\\$")
            i += 2
            continue
        if c == "$":
            display = par.startswith("$$", i)
            delim = "$$" if display else "$"
            k = i + len(delim)
            while True:
                k = par.find(delim, k)
                if k < 0 or par[k - 1] != "\\":
                    break
                k += 1
            if k < 0 or (not display and par.startswith("$$", k) and k == i + 1):
                # A stray sign (a typo in the source) is dropped; anything
                # that looks like money is kept.
                money = re.match(r"\$\s?\d", par[i:i + 3])
                warn(f"{'kept' if money else 'dropped'} unmatched $ in: {par[max(0, i - 40):i + 40]!r}")
                if money:
                    text.append("\\$")
                i += 1
                continue
            if text:
                tokens.append(("text", "".join(text)))
                text = []
            tokens.append(("display" if display else "inline", par[i + len(delim):k]))
            i = k + len(delim)
            continue
        text.append(c)
        i += 1
    if text:
        tokens.append(("text", "".join(text)))
    return tokens


def fix_math_body(body):
    """MathJax lets align & co. sit inside $$; in TeX they become aligned."""
    body = body.strip()
    body = re.sub(r"\\(begin|end)\{(align|gather)\*?\}", r"\\\1{\2ed}", body)
    body = re.sub(r"\\(begin|end)\{eqnarray\*?\}", r"\\\1{aligned}", body)
    return body


CURRENCY = re.compile(r"(?<![A-Za-z\\$])R\$(?=\s?\d)|(?<=\d )R\$")


def normalize_math(text):
    """Make MathJax-style maths acceptable to pandoc and TeX.

    Jupyter accepts "$ x $" and "$" alone on a line around a display; pandoc
    needs "$x$" and "$$...$$".  A paragraph made only of maths is a display.
    Prices in reais ("R$ 6.52") are not maths.
    """
    text = CURRENCY.sub(r"R\\$", text)
    pieces = re.split(r"(\n[ \t]*\n)", text)
    out = []
    for par in pieces:
        if not par.strip() or re.fullmatch(r"\n[ \t]*\n", par):
            out.append(par)
            continue
        tokens = tokenize_math(par)
        math_only = all(t == "text" and not v.strip() or t != "text" for t, v in tokens) \
            and any(t != "text" for t, _ in tokens)
        res = []
        for kind, val in tokens:
            if kind == "text":
                res.append(val)
                continue
            body = fix_math_body(val)
            if math_only or kind == "display":
                res.append("$$" + body + "$$")
            else:
                res.append("$" + body + "$")
        out.append("".join(res))
    return "".join(out)


MD_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def meme_size(px_w, px_h):
    """Display size (inches) for an illustration from data/img.

    The online book shows images at their pixel width in a ~750px column;
    map that column onto the text block, then keep tall images in check.
    """
    w = min(TEXTWIDTH_IN, max(px_w / 140.0, min(1.5, TEXTWIDTH_IN)))
    h = w * px_h / px_w
    if h > 3.2:
        h, w = 3.2, 3.2 * px_w / px_h
    return w, h


def convert_images(text, ch):
    def repl(m):
        src = m.group(2)
        path = (ch.path.parent / src).resolve()
        if not path.exists():
            warn(f"{ch.slug}: missing image {src}")
            return m.group(0)
        rel = path.relative_to(SRC / "data" / "img") if (SRC / "data" / "img") in path.parents \
            else Path(path.name)
        dest = BUILD / "img" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists() or dest.stat().st_mtime < path.stat().st_mtime:
            shutil.copy2(path, dest)
        with Image.open(path) as im:
            w, h = meme_size(*im.size)
        return f"![](img/{rel.as_posix()}){{width={w / TEXTWIDTH_IN:.3f}\\linewidth height={h:.2f}in}}"
    return MD_IMAGE.sub(repl, text)


# ```{note} is a MyST admonition; one notebook writes it as ```note.
ADMONITION = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*\{?(note|tip|hint|important|warning|caution|"
                        r"attention|seealso)\}?\s*$")


def markdown_cell(src, ch):
    src = src.replace("\r\n", "\n").replace("\u202a", "").replace("\u202c", "")
    out = []
    for is_code, run in split_fences(src):
        lines = run.rstrip("\n").split("\n")
        m = ADMONITION.match(lines[0]) if is_code else None
        if m:
            body = "\n".join(lines[1:-1] if len(lines) > 1 and FENCE.match(lines[-1]) else lines[1:])
            body = normalize_math(convert_images(body, ch))
            out.append(f"\n::: {{.admonition kind={m.group(2)}}}\n{body}\n:::\n")
        elif is_code:
            out.append(run)
        else:
            out.append(normalize_math(convert_images(run, ch)))
    return "".join(out)


def split_title(src):
    lines = src.split("\n")
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        m = re.match(r"^#\s+(.+?)\s*#*\s*$", line)
        if m:
            return m.group(1), "\n".join(lines[:i] + lines[i + 1:])
        break
    return None, src


# ---------------------------------------------------------------------------
# Code cells and their outputs
# ---------------------------------------------------------------------------

CODE_COLUMNS = 80                  # characters per line in a code box
CODE_CONT = "\ue000"               # marks a wrapped line; becomes \codecont


def code_mask(line):
    """True for characters inside string literals or comments."""
    mask, i, n, quote = [False] * len(line), 0, len(line), None
    while i < n:
        c = line[i]
        if quote:
            mask[i] = True
            if c == "\\" and not raw:
                if i + 1 < n:
                    mask[i + 1] = True
                i += 2
                continue
            if line.startswith(quote, i):
                for k in range(len(quote)):
                    mask[i + k] = True
                i += len(quote)
                quote = None
                continue
            i += 1
            continue
        if c == "#":
            for k in range(i, n):
                mask[k] = True
            break
        if c in "\"'":
            quote = c * 3 if line.startswith(c * 3, i) else c
            j = i - 1
            prefix = ""
            while j >= 0 and line[j].isalpha():
                prefix = line[j] + prefix
                j -= 1
            raw = "r" in prefix.lower()
            for k in range(len(quote)):
                mask[i + k] = True
            i += len(quote)
            continue
        i += 1
    return mask


def wrap_code_line(line, limit=CODE_COLUMNS):
    """Break an over-long line of Python where a typesetter would.

    Continuation lines are indented four more columns and start with a
    marker that LaTeX draws as a hook arrow; the break never falls inside a
    string or comment (fvextra wraps those at spaces if it has to).
    """
    if len(line) <= limit:
        return [line]
    indent = len(line) - len(line.lstrip(" "))
    out, rest, lead = [], line, ""
    while len(lead) + len(rest) > limit:
        mask = code_mask(rest)
        room = limit - len(lead)
        lo = max(indent + 8, int(room * 0.45))
        best = None
        for p in range(min(room, len(rest) - 1), lo, -1):
            if mask[p] or mask[p - 1]:
                continue
            prev, ch = rest[p - 1], rest[p]
            if prev == "," and ch == " ":
                cls = 0
            elif ch == " " and prev != " ":
                cls = 2
            elif prev == ",":
                cls = 1
            elif ch == "." and prev not in " (" and not (prev.isdigit() and p + 1 < len(rest) and rest[p + 1].isdigit()):
                cls = 3
            elif prev in "([{" and ch not in ")]}":
                cls = 3.5
            else:
                continue
            score = cls + (room - p) * 0.12
            if best is None or score < best[0]:
                best = (score, p)
        if best is None:
            break
        p = best[1]
        out.append(lead + rest[:p].rstrip())
        lead = " " * (indent + 4) + CODE_CONT
        rest = rest[p:].lstrip()
    out.append(lead + rest)
    return out


def wrap_code(src):
    return "\n".join(part for line in src.split("\n") for part in wrap_code_line(line))


def fenced(text, info=""):
    fence = "```"
    while fence in text:
        fence += "`"
    return f"{fence}{info}\n{text}\n{fence}"


def raw_latex(tex):
    return fenced(tex, "{=latex}")


NUMERIC = re.compile(r"^[-+−]?(\d[\d,]*(\.\d*)?|\.\d+)([eE][-+]?\d+)?%?$")
NUMLIKE = {"", "NaN", "nan", "NaT", "None", "inf", "-inf", "True", "False",
           "...", "…", "<NA>", "-"}


def parse_html_table(table):
    """Return (rows, n_header_rows); rows are lists of cell dicts."""
    trs = table.find_all("tr")
    thead = table.find("thead")
    n_head = len(thead.find_all("tr")) if thead else 0
    grid, pending = [], {}
    for r, tr in enumerate(trs):
        row, c = [], 0
        cells = tr.find_all(["td", "th"], recursive=False)
        for cell in cells:
            while (r, c) in pending:
                row.append(pending.pop((r, c)))
                c += 1
            text = " ".join(cell.get_text(" ", strip=True).split())
            rs = int(cell.get("rowspan", 1) or 1)
            cs = int(cell.get("colspan", 1) or 1)
            th = cell.name == "th"
            row.append({"text": text, "th": th, "colspan": cs, "rowspan": rs})
            for _ in range(1, cs):
                row.append({"text": "", "th": th, "covered": True})
            for k in range(1, rs):
                for cc in range(cs):
                    pending[(r + k, c + cc)] = {"text": "", "th": th, "rowcont": True}
            c += cs
        while (r, c) in pending:
            row.append(pending.pop((r, c)))
            c += 1
        grid.append(row)
    if not thead and grid:
        # statsmodels SimpleTable: a first row of <th> labels is a header
        first = grid[0]
        if len(first) > 1 and all(x["th"] for x in first[1:]) and not any(x["th"] for x in grid[-1][1:]):
            n_head = 1
    return grid, n_head


def cell_text(s, numeric):
    s = s.strip()
    if s in ("...", "…"):
        return r"\dots"
    t = tex_escape(s)
    if numeric and re.match(r"^-(\d|\.\d|inf)", s):
        t = "−" + t[1:]                                    # true minus sign
    return t


def text_em(s):
    """Approximate width of table text in em (Fira Sans, tabular figures)."""
    return sum(0.512 if ch.isdigit() or ch in ".,-−+" else 0.47 for ch in s)


def table_width_pt(widths, size):
    return sum(w * size for w in widths) + 9.0 * (len(widths) - 1) + 12.0


def split_columns(widths, n_idx, ncols, size):
    """Cut the data columns into the fewest stacks that fit, of even width."""
    data = list(range(n_idx, ncols))
    idx_w = widths[:n_idx]
    total = sum(widths[c] for c in data)

    def fits(cols):
        return table_width_pt(idx_w + [widths[c] for c in cols], size) <= TEXTWIDTH_PT

    for k in range(2, len(data) + 1):
        target, chunks, cur, acc = total / k, [], [], 0.0
        for c in data:
            if cur and len(chunks) < k - 1 and acc + widths[c] / 2 > target * (len(chunks) + 1):
                chunks.append(cur)
                cur = []
            cur.append(c)
            acc += widths[c]
        chunks.append(cur)
        if all(fits(ch) for ch in chunks):
            return chunks
    return [[c] for c in data]


def render_table(grid, n_head, footer=None):
    if not grid:
        return None
    ncols = max(len(r) for r in grid)
    for r in grid:
        while len(r) < ncols:
            r.append({"text": "", "th": False})
    header, body = grid[:n_head], grid[n_head:]
    if not body:
        header, body = [], grid

    # Index columns: leading columns whose body cells are all <th>.
    n_idx = 0
    while n_idx < ncols and body and all(r[n_idx]["th"] for r in body):
        n_idx += 1

    # pandas puts index names on a second header row: fold it into the first.
    if len(header) == 2 and n_idx and all(not c["text"] for c in header[1][n_idx:]) \
            and all(not c["text"] for c in header[0][:n_idx]):
        merged = [dict(c) for c in header[0]]
        for k in range(n_idx):
            merged[k] = header[1][k]
        header = [merged]
    header = [h for h in header if any(c["text"] for c in h)]

    numeric = []
    for c in range(ncols):
        vals = [r[c]["text"] for r in body if not r[c].get("rowcont")]
        numeric.append(c >= n_idx and all(NUMERIC.match(v) or v in NUMLIKE for v in vals))
    align = ["l" if c < n_idx or not numeric[c] else "r" for c in range(ncols)]

    widths = []
    for c in range(ncols):
        lens = [text_em(r[c]["text"]) for r in body]
        lens += [text_em(h[c]["text"]) * 1.03 for h in header if h[c].get("colspan", 1) == 1]
        widths.append(max(lens + [0.5]))

    # Pick the largest size that fits; split very wide tables into stacks.
    chunks, size = [list(range(n_idx, ncols))], None
    for s in (9, 8.5, 8, 7.5):
        if table_width_pt(widths, s) <= TEXTWIDTH_PT:
            size = s
            break
    if size is None:
        size = 8
        chunks = split_columns(widths, n_idx, ncols, size)

    parts = []
    for chunk in chunks:
        cols = list(range(n_idx)) + chunk
        spec = "".join(align[c] for c in cols)
        if n_idx:
            spec = spec[:n_idx] + "@{\\hspace{12pt}}" + spec[n_idx:]
        lines = [r"\begin{adjustbox}{max width=\linewidth}",
                 rf"\dfsize{{{size}}}{{{size * 1.25:.1f}}}%",
                 rf"\begin{{tabular}}{{@{{}}{spec}@{{}}}}", r"\toprule"]
        for h in header:
            cells, rules, pos = [], [], 0
            i = 0
            while i < len(cols):
                c = cols[i]
                cell = h[c]
                if cell.get("covered"):
                    i += 1
                    pos += 1
                    continue
                span = 1
                while i + span < len(cols) and h[cols[i + span]].get("covered") \
                        and cols[i + span] == c + span:
                    span += 1
                txt = cell_text(cell["text"], False)
                txt = rf"\dfh{{{txt}}}" if txt else ""
                if span > 1:
                    cells.append(rf"\multicolumn{{{span}}}{{c}}{{{txt}}}")
                    if cell["text"]:
                        rules.append(rf"\cmidrule(lr){{{pos + 1}-{pos + span}}}")
                else:
                    cells.append(txt)
                pos += span
                i += span
            lines.append(" & ".join(cells) + r" \\")
            if rules and h is not header[-1]:
                lines.append(" ".join(rules))
        if header:
            lines.append(r"\midrule")
        for ri, r in enumerate(body):
            if ri and n_idx and r[0].get("rowspan", 1) > 1 and not r[0].get("rowcont"):
                lines.append(r"\addlinespace[3pt]")
            cells = []
            for c in cols:
                txt = cell_text(r[c]["text"], numeric[c])
                if c < n_idx and txt:
                    txt = rf"\dfi{{{txt}}}"
                cells.append(txt)
            lines.append(" & ".join(cells) + r" \\")
        lines += [r"\bottomrule", r"\end{tabular}", r"\end{adjustbox}"]
        parts.append("\n".join(lines))
    tex = "\n\\dfsplitgap\n".join(parts)
    if footer:
        tex += "\n" + rf"\dfnote{{{tex_escape(footer)}}}"
    return "\\begin{dfblock}\n" + tex + "\n\\end{dfblock}"


def html_to_tables(html):
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")
    if not tables:
        return None
    out = []
    for t in tables:
        footer = None
        nxt = t.find_next_sibling("p")
        if nxt is not None:
            footer = " ".join(nxt.get_text(" ", strip=True).split())
        grid, n_head = parse_html_table(t)
        tex = render_table(grid, n_head, footer)
        if tex:
            out.append(tex)
    return "\n\n".join(out) if out else None


FIGURE_SCALE = 0.72        # 10pt plot labels print at about 7pt


def figure_size(w_in, h_in):
    """Printed size of a plot that matplotlib drew at w_in x h_in inches."""
    w = min(TEXTWIDTH_IN, w_in * FIGURE_SCALE)
    h = w * h_in / w_in
    if h > 3.8:
        h, w = 3.8, 3.8 * w_in / h_in
    return w, h


def png_inches(path):
    with Image.open(path) as im:
        dpi = im.info.get("dpi", (72, 72))[0] or 72
        return im.size[0] / dpi, im.size[1] / dpi


def pdf_inches(path):
    box = PdfReader(str(path)).pages[0].mediabox
    return float(box.width) / 72, float(box.height) / 72


FONTCONF = None


def fontconfig_env():
    """A fontconfig file that also sees the TeX fonts (for SVG text)."""
    global FONTCONF
    if FONTCONF is None:
        dirs = set()
        for f in ("XCharter-Roman.otf", "FiraSans-Book.otf"):
            p = subprocess.run(["kpsewhich", f], capture_output=True, text=True).stdout.strip()
            if p:
                dirs.add(str(Path(p).parent))
        FONTCONF = BUILD / "fonts.conf"
        FONTCONF.write_text(
            '<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n<fontconfig>\n'
            '  <include ignore_missing="yes">/etc/fonts/fonts.conf</include>\n'
            + "".join(f"  <dir>{d}</dir>\n" for d in sorted(dirs))
            + f"  <cachedir>{BUILD / 'fc-cache'}</cachedir>\n</fontconfig>\n")
    return dict(os.environ, FONTCONFIG_FILE=str(FONTCONF))


def svg_figure(svg, dest_pdf):
    # Graphviz labels are set in Times; use the book's text face instead
    # (slightly smaller, as Charter runs wider than Times).
    def font_size(m):
        return f'font-size="{float(m.group(1)) * 0.9:.2f}"'
    svg = svg.replace('font-family="Times,serif"', 'font-family="XCharter"')
    svg = svg.replace('font-family="Times-Roman"', 'font-family="XCharter"')
    svg = re.sub(r'font-size="([\d.]+)"', font_size, svg)
    tmp = dest_pdf.with_suffix(".svg")
    tmp.write_text(svg)
    subprocess.run(["rsvg-convert", "-f", "pdf", "-o", str(dest_pdf), str(tmp)],
                   check=True, env=fontconfig_env())
    m = re.search(r'<svg[^>]*\swidth="([\d.]+)pt"[^>]*\sheight="([\d.]+)pt"', svg, re.S)
    if m:
        w_in, h_in = float(m.group(1)) / 72 * 0.8, float(m.group(2)) / 72 * 0.8
    else:
        w_in, h_in = 3.0, 2.0
    if w_in > TEXTWIDTH_IN:
        h_in, w_in = h_in * TEXTWIDTH_IN / w_in, TEXTWIDTH_IN
    if h_in > 3.6:
        w_in, h_in = w_in * 3.6 / h_in, 3.6
    return w_in, h_in


def vector_replacement(ch, idx, k):
    p = VECTOR / ch.slug / f"c{idx:03d}-{k}.pdf"
    return p if p.exists() else None


def render_outputs(cell, ch, idx):
    blocks, text_run = [], []

    def flush_text():
        if text_run:
            txt = clean_output_text("\n".join(text_run))
            if txt.strip():
                blocks.append(fenced(txt, " {.output}"))
            text_run.clear()

    fig_k = 0
    for out in cell.get("outputs", []):
        kind = out["output_type"]
        if kind == "stream":
            if out.get("name") == "stderr":           # warnings are not book content
                continue
            text_run.append("".join(out["text"]).rstrip("\n"))
            continue
        if kind == "error":
            text_run.append("\n".join(out.get("traceback", [])))
            continue
        data = out.get("data", {})
        rendered = None
        if "image/png" in data or "image/svg+xml" in data or "image/jpeg" in data:
            fig_dir = BUILD / "figures" / ch.slug
            fig_dir.mkdir(parents=True, exist_ok=True)
            vec = vector_replacement(ch, idx, fig_k)
            if "image/svg+xml" in data:
                dest = fig_dir / f"c{idx:03d}-{fig_k}.pdf"
                w, h = svg_figure("".join(data["image/svg+xml"]), dest)
            else:
                key = "image/png" if "image/png" in data else "image/jpeg"
                raw = data[key]
                raw = "".join(raw) if isinstance(raw, list) else raw
                ext = "png" if key == "image/png" else "jpg"
                dest = fig_dir / f"c{idx:03d}-{fig_k}.{ext}"
                dest.write_bytes(base64.b64decode(raw))
                if vec:
                    dest = vec
                    w, h = figure_size(*pdf_inches(vec))
                else:
                    w, h = figure_size(*png_inches(dest))
            rel = os.path.relpath(dest, BUILD)
            rendered = raw_latex(rf"\bookimage{{{w / TEXTWIDTH_IN:.3f}\linewidth}}{{{h:.2f}in}}{{{rel}}}")
            fig_k += 1
        elif "text/html" in data:
            rendered = html_to_tables("".join(data["text/html"]))
            if rendered:
                rendered = raw_latex(rendered)
            elif "text/plain" in data:
                text_run.append("".join(data["text/plain"]))
                continue
        elif "text/latex" in data:
            rendered = raw_latex("".join(data["text/latex"]))
        elif "text/plain" in data:
            text_run.append("".join(data["text/plain"]))
            continue
        if rendered:
            flush_text()
            blocks.append(rendered)
    flush_text()
    return blocks


# ---------------------------------------------------------------------------
# Chapters
# ---------------------------------------------------------------------------

def notebook_markdown(ch):
    nb = json.loads(ch.path.read_text())
    chunks, first_md = [], True
    for idx, cell in enumerate(nb["cells"]):
        src = source(cell)
        if cell["cell_type"] == "markdown":
            if first_md:
                title, src = split_title(src)
                if title:
                    ch.title = clean_title(title)
                first_md = False
            chunks.append(markdown_cell(src, ch))
        elif cell["cell_type"] == "code":
            if src.strip():
                chunks.append(fenced(wrap_code(src.rstrip()), "python"))
            chunks.extend(render_outputs(cell, ch, idx))
    if not ch.title:
        ch.title = clean_title(ch.path.stem.replace("-", " "))
    return "\n\n".join(c for c in chunks if c.strip()) + "\n"


# CommonMark, like Jupyter, so lists may interrupt paragraphs and so on.
MD_FORMAT = ("commonmark_x-subscript-superscript-yaml_metadata_block-emoji"
             "-fancy_lists-definition_lists")


def pandoc_latex(md, chapter_id, keep_contribute=False):
    cmd = ["pandoc", "-f", MD_FORMAT, "-t", "latex", "--wrap=preserve",
           f"--lua-filter={FILTER}", f"--highlight-style={TEX / 'brave.theme'}",
           "-M", f"chapter_id={chapter_id}"]
    if keep_contribute:
        cmd += ["-M", "keep_contribute=true"]
    res = subprocess.run(cmd, input=md, capture_output=True, text=True)
    if res.returncode:
        sys.exit(f"pandoc failed for {chapter_id}:\n{res.stderr}")
    if res.stderr.strip():
        warn(f"pandoc ({chapter_id}): {res.stderr.strip()}")
    tex = re.sub(r"^\\def\\labelenumi\{\\arabic\{enumi\}\.\}\n", "", res.stdout, flags=re.M)
    return tex.replace(CODE_CONT, r"\codecont{}")


def build_chapter(ch):
    md = notebook_markdown(ch)
    (BUILD / "md").mkdir(parents=True, exist_ok=True)
    (BUILD / "md" / f"{ch.slug}.md").write_text(md)
    body = pandoc_latex(md, ch.slug)
    head = rf"\typeout{{BOOKFILE {ch.slug}}}\chapter{{{title_tex(ch.title)}}}\label{{{ch.slug}}}" + "\n\n"
    (BUILD / "chapters").mkdir(parents=True, exist_ok=True)
    (BUILD / "chapters" / f"{ch.slug}.tex").write_text(head + body)


def build_preface():
    md = (SRC / "landing-page.md").read_text()
    md = re.sub(r"^#\s+.*\n", "", md, count=1)                 # book title
    md = re.sub(r"^!\[[^\]]*\]\([^)]*brave-and-true[^)]*\)\s*\n", "", md, flags=re.M)
    fake = Chapter(SRC / "landing-page.md", "", "preface", False)
    md = markdown_cell(md, fake)
    body = pandoc_latex(md, "preface", keep_contribute=True)
    head = "\\chapter*{Preface}\\label{preface}\n\\addcontentsline{toc}{chapter}{Preface}\n" \
           "\\markboth{Preface}{Preface}\n\n"
    (BUILD / "chapters" / "preface.tex").write_text(head + body)


def highlighting_macros():
    tpl = BUILD / "macros.tpl"
    tpl.write_text("$highlighting-macros$\n")
    res = subprocess.run(
        ["pandoc", "-f", "markdown", "-t", "latex", "--standalone", f"--template={tpl}",
         f"--highlight-style={TEX / 'brave.theme'}"],
        input="```python\nx = 1\n```\n", capture_output=True, text=True, check=True)
    keep = []
    for line in res.stdout.splitlines():
        if re.match(r"\\(usepackage|DefineVerbatimEnvironment|newenvironment)\b", line):
            continue
        if line.startswith("%"):
            continue
        keep.append(line)
    (BUILD / "highlighting.tex").write_text("\n".join(keep) + "\n")


def git_revision():
    """The last commit that changed the notebooks: the edition's content
    revision, which commits to the build pipeline leave alone."""
    def git(*args):
        return subprocess.run(["git", "-C", str(REPO), *args],
                              capture_output=True, text=True, check=True).stdout.strip()
    try:
        rev = git("log", "-1", "--format=%h", "--", str(SRC)) or "unknown"
        return rev + ("-dirty" if git("status", "--porcelain", "--", str(SRC)) else "")
    except Exception:
        return "unknown"


# Acronyms and synonyms that point to the main index entry.
INDEX_SEE = {
    "ATE": "average treatment effect (ATE)",
    "ATT": "average treatment effect on the treated (ATT)",
    "CATE": "conditional average treatment effect (CATE)",
    "RCT": "randomized controlled trial (RCT)",
    "OLS": "ordinary least squares (OLS)",
    "FWL theorem": "Frisch--Waugh--Lovell theorem",
    "IV": "instrumental variables (IV)",
    "2SLS": "two-stage least squares (2SLS)",
    "LATE": "local average treatment effect (LATE)",
    "TWFE": "two-way fixed effects (TWFE)",
    "SDID": "synthetic difference-in-differences (SDID)",
    "RDD": "regression discontinuity design (RDD)",
    "diff-in-diff": "difference-in-differences",
    "debiased machine learning": "double/debiased machine learning",
    "S-learner": "meta-learners",
    "T-learner": "meta-learners",
    "X-learner": "meta-learners",
    "randomized experiment": "randomized controlled trial (RCT)",
    "selection bias": "bias",
    "omitted variable bias": "bias",
}


def write_master(parts, only):
    lines = [
        r"\pdfvariable minorversion=7",
        r"\documentclass[10pt,twoside,openright,final]{memoir}",
        r"\usepackage{brave}",
        r"\input{highlighting}",
        r"\hypersetup{pdftitle={" + BOOK_TITLE + "}, pdfauthor={" + AUTHOR + "},",
        r"  pdfsubject={Causal inference, econometrics and machine learning in Python},",
        r"  pdfkeywords={causal inference, econometrics, potential outcomes, Python}}",
        r"\newcommand*{\sourcerevision}{" + git_revision() + "}",
        r"\begin{document}",
        r"\pdfbookmark[0]{Cover}{cover}",
        r"\input{cover}",
        r"\frontmatter",
        r"\input{titlepages}",
        r"\cleardoublepage\pdfbookmark[0]{Brief Contents}{briefcontents}",
        r"\begingroup\setcounter{tocdepth}{0}\renewcommand*{\contentsname}{Brief Contents}",
        r"\tableofcontents*\endgroup",
        r"\cleardoublepage\pdfbookmark[0]{Contents in Detail}{contents}",
        r"\begingroup\setcounter{tocdepth}{1}\renewcommand*{\contentsname}{Contents in Detail}",
        r"\tableofcontents*\endgroup",
        r"\input{chapters/preface}",
        r"\mainmatter",
    ]
    for part in parts:
        chapters = [c for c in part.chapters if not only or c.number in only]
        if not chapters:
            continue
        if part.appendix:
            lines += [r"\appendix", r"\appendixpart"]
        else:
            lines.append(rf"\bravepart{{{tex_escape(part.title)}}}")
        lines += [rf"\input{{chapters/{c.slug}}}" for c in chapters]
    lines += [r"\backmatter", r"\input{index-see}",
              r"\begingroup\small\printindex\endgroup",
              r"\input{colophon}", r"\end{document}"]
    (BUILD / "book.tex").write_text("\n".join(lines) + "\n")
    see = "".join(rf"\index{{{k.lower()}@{k}|see{{{v}}}}}" + "\n" for k, v in INDEX_SEE.items())
    (BUILD / "index-see.tex").write_text(see)


def compile_pdf():
    env = dict(os.environ, TEXINPUTS=f".:{TEX}//:", max_print_line="10000")
    shutil.copy2(TEX / "brave.ist", BUILD / "brave.ist")
    (BUILD / "latexmkrc").write_text("$makeindex = 'makeindex -s brave.ist %O -o %D %S';\n")
    cmd = ["latexmk", "-r", "latexmkrc", "-lualatex", "-interaction=nonstopmode",
           "-halt-on-error", "-file-line-error", "book.tex"]
    res = subprocess.run(cmd, cwd=BUILD, env=env, capture_output=True, text=True)
    log = (BUILD / "book.log").read_text(errors="replace") if (BUILD / "book.log").exists() else ""
    if res.returncode:
        tail = "\n".join(log.splitlines()[-60:])
        sys.exit(f"LuaLaTeX failed:\n{tail}")
    overfull = len(re.findall(r"^Overfull \\hbox", log, re.M))
    print(f"  overfull hboxes: {overfull}")
    return BUILD / "book.pdf"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", help="comma-separated chapter numbers/letters to include")
    ap.add_argument("--no-pdf", action="store_true", help="write LaTeX but do not compile")
    args = ap.parse_args()
    only = set(args.only.split(",")) if args.only else None

    BUILD.mkdir(exist_ok=True)
    (BUILD / "chapters").mkdir(exist_ok=True)
    parts = load_toc()
    (BUILD / "img").mkdir(exist_ok=True)
    shutil.copy2(SRC / "data" / "img" / "brave-and-true.png", BUILD / "img" / "brave-and-true.png")
    highlighting_macros()
    build_preface()
    for part in parts:
        for ch in part.chapters:
            if only and ch.number not in only:
                continue
            print(f"[{ch.number:>2}] {ch.path.name}")
            build_chapter(ch)
    write_master(parts, only)
    if args.no_pdf:
        return
    pdf = compile_pdf()
    target = HERE / PDF_NAME
    shutil.copy2(pdf, target)
    print(f"wrote {target.relative_to(REPO)}")
    if WARNINGS:
        print(f"{len(WARNINGS)} warning(s)", file=sys.stderr)


if __name__ == "__main__":
    main()

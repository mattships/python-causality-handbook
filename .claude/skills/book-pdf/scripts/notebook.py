"""Jupyter notebooks -> Markdown with raw LaTeX for their outputs.

Markdown cells go through markup.preprocess_markdown.  Code cells become
fenced listings in the kernel's language.  Outputs keep what the reader saw:
DataFrame and statsmodels HTML tables become booktabs tables, images become
figures (or their vector re-draws, see figures.py), text becomes an output
block.  Jupyter Book cell tags (remove-cell, remove-input, remove-output,
hide-input) are respected.
"""

import base64
import hashlib
import json
import re
from pathlib import Path

from PIL import Image

import markup

NUMERIC = re.compile(r"^[-+−]?(\d[\d,]*(\.\d*)?|\.\d+)([eE][-+]?\d+)?%?$")
NUMLIKE = {"", "NaN", "nan", "NaT", "None", "inf", "-inf", "True", "False",
           "...", "…", "<NA>", "-"}
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

TEX_ESCAPES = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
    "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}", "<": r"\textless{}", ">": r"\textgreater{}",
}


def tex_escape(s):
    return "".join(TEX_ESCAPES.get(ch, ch) for ch in s)


def source(cell):
    s = cell.get("source", "")
    return "".join(s) if isinstance(s, list) else s


def raw_latex(tex):
    return markup.fence(tex, "{=latex}")


def figure_key(path, root):
    """Stable name for a notebook's figures (independent of chapter order)."""
    try:
        rel = Path(path).resolve().relative_to(Path(root).resolve())
    except ValueError:
        rel = Path(Path(path).name)
    return re.sub(r"[^A-Za-z0-9]+", "-", str(rel.with_suffix(""))).strip("-")


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


# ---------------------------------------------------------------------------
# HTML tables (pandas, statsmodels)
# ---------------------------------------------------------------------------

def parse_html_table(table):
    """Return (rows, n_header_rows); rows are lists of cell dicts."""
    trs = table.find_all("tr")
    thead = table.find("thead")
    n_head = len(thead.find_all("tr")) if thead else 0
    grid, pending = [], {}
    for r, tr in enumerate(trs):
        row, c = [], 0
        for cell in tr.find_all(["td", "th"], recursive=False):
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
    """Approximate width of table text in em (sans, tabular figures)."""
    return sum(0.512 if ch.isdigit() or ch in ".,-−+" else 0.47 for ch in s)


def table_width_pt(widths, size):
    return sum(w * size for w in widths) + 9.0 * (len(widths) - 1) + 12.0


def split_columns(widths, n_idx, ncols, size, textwidth_pt):
    """Cut the data columns into the fewest stacks that fit, of even width."""
    data = list(range(n_idx, ncols))
    idx_w = widths[:n_idx]
    total = sum(widths[c] for c in data)

    def fits(cols):
        return table_width_pt(idx_w + [widths[c] for c in cols], size) <= textwidth_pt

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


def render_table(grid, n_head, textwidth_pt, footer=None):
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
        if table_width_pt(widths, s) <= textwidth_pt:
            size = s
            break
    if size is None:
        size = 8
        chunks = split_columns(widths, n_idx, ncols, size, textwidth_pt)

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


def html_to_tables(html, textwidth_pt):
    from bs4 import BeautifulSoup
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
        tex = render_table(grid, n_head, textwidth_pt, footer)
        if tex:
            out.append(tex)
    return "\n\n".join(out) if out else None


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------

FIGURE_SCALE = 0.72        # 10pt plot labels print at about 7pt


def figure_size(w_in, h_in, textwidth_in, max_h=3.8):
    """Printed size of a plot that was drawn at w_in x h_in inches."""
    w = min(textwidth_in, w_in * FIGURE_SCALE)
    h = w * h_in / w_in
    if h > max_h:
        h, w = max_h, max_h * w_in / h_in
    return w, h


def png_inches(path):
    with Image.open(path) as im:
        dpi = (im.info.get("dpi") or (72, 72))[0] or 72
        return im.size[0] / dpi, im.size[1] / dpi


def pdf_inches(path):
    from pypdf import PdfReader
    box = PdfReader(str(path)).pages[0].mediabox
    return float(box.width) / 72, float(box.height) / 72


# ---------------------------------------------------------------------------
# Notebook -> Markdown
# ---------------------------------------------------------------------------

def render_outputs(cell, idx, nb_key, ctx):
    blocks, text_run = [], []

    def flush_text():
        if text_run:
            txt = clean_output_text("\n".join(text_run))
            if txt.strip():
                blocks.append(markup.fence(txt, " {.output}"))
            text_run.clear()

    fig_dir = ctx.dir / "figures" / nb_key
    fig_k = 0
    for out in cell.get("outputs", []):
        kind = out.get("output_type")
        if kind == "stream":
            if out.get("name") == "stderr":           # warnings are not book content
                continue
            text_run.append("".join(out.get("text", "")).rstrip("\n"))
            continue
        if kind == "error":
            text_run.append("\n".join(out.get("traceback", [])))
            continue
        data = out.get("data", {})
        rendered = None
        if any(k in data for k in ("image/png", "image/svg+xml", "image/jpeg", "application/pdf")):
            fig_dir.mkdir(parents=True, exist_ok=True)
            vec = ctx.vector_figure(nb_key, idx, fig_k)
            if "image/svg+xml" in data and not vec:
                dest = fig_dir / f"c{idx:03d}-{fig_k}.pdf"
                w, h = ctx.svg_to_pdf("".join(data["image/svg+xml"]), dest, scale=0.8)
            elif "application/pdf" in data and not vec:
                dest = fig_dir / f"c{idx:03d}-{fig_k}.pdf"
                raw = data["application/pdf"]
                dest.write_bytes(base64.b64decode("".join(raw) if isinstance(raw, list) else raw))
                w, h = figure_size(*pdf_inches(dest), ctx.textwidth_in)
            else:
                key = "image/png" if "image/png" in data else "image/jpeg"
                if key not in data:
                    key = next(k for k in data if k.startswith("image/"))
                raw = data[key]
                raw = "".join(raw) if isinstance(raw, list) else raw
                ext = "png" if key == "image/png" else "jpg"
                dest = fig_dir / f"c{idx:03d}-{fig_k}.{ext}"
                dest.write_bytes(base64.b64decode(raw))
                if vec:
                    dest = vec
                    w, h = figure_size(*pdf_inches(vec), ctx.textwidth_in)
                else:
                    w, h = figure_size(*png_inches(dest), ctx.textwidth_in)
            rel = ctx.rel(dest)
            rendered = raw_latex(rf"\bookimage{{{w / ctx.textwidth_in:.3f}\linewidth}}{{{h:.2f}in}}{{{rel}}}")
            fig_k += 1
        elif "text/html" in data:
            html = "".join(data["text/html"])
            rendered = html_to_tables(html, ctx.textwidth_pt)
            if rendered:
                rendered = raw_latex(rendered)
            elif "text/markdown" in data:
                rendered = "".join(data["text/markdown"])
            elif "text/plain" in data and not re.search(r"<(div|p|span|b|i|ul|ol|h\d)\b", html):
                text_run.append("".join(data["text/plain"]))
                continue
            else:
                rendered = ctx.html_to_markdown(html)
        elif "text/markdown" in data:
            rendered = "".join(data["text/markdown"])
        elif "text/latex" in data:
            tex = "".join(data["text/latex"]).strip()
            m = re.fullmatch(r"\$\$?(.*?)\$?\$", tex, re.S)
            rendered = f"$${m.group(1).replace(chr(92) + 'displaystyle', '').strip()}$$" if m else raw_latex(tex)
        elif "text/plain" in data:
            text_run.append("".join(data["text/plain"]))
            continue
        if rendered:
            flush_text()
            blocks.append(rendered)
    flush_text()
    return blocks


def write_attachments(cell, idx, nb_key, ctx):
    """Images embedded in a Markdown cell ('attachment:name')."""
    names = {}
    for name, bundle in (cell.get("attachments") or {}).items():
        for mime, data in bundle.items():
            if mime.startswith("image/"):
                ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
                       "image/svg+xml": ".svg"}.get(mime, ".png")
                dest = ctx.dir / "img" / "attachments" / f"{nb_key}-{idx}-{Path(name).stem}{ext}"
                dest.parent.mkdir(parents=True, exist_ok=True)
                raw = "".join(data) if isinstance(data, list) else data
                dest.write_bytes(raw.encode() if mime == "image/svg+xml" else base64.b64decode(raw))
                names[name] = dest
                break
    return names


def notebook_markdown(path, ctx):
    """(markdown, kernel language, metadata) for a notebook."""
    nb = json.loads(Path(path).read_text(errors="replace"))
    meta = nb.get("metadata", {})
    lang = (meta.get("kernelspec", {}).get("language")
            or meta.get("language_info", {}).get("name") or ctx.default_lang or "python").lower()
    nb_key = figure_key(path, ctx.root)
    chunks = []
    for idx, cell in enumerate(nb.get("cells", [])):
        tags = set((cell.get("metadata") or {}).get("tags") or [])
        if "remove-cell" in tags or "remove_cell" in tags:
            continue
        src = source(cell)
        if cell.get("cell_type") == "markdown":
            for name, dest in write_attachments(cell, idx, nb_key, ctx).items():
                src = src.replace(f"attachment:{name}", dest.resolve().as_uri()[len("file://"):])
            md, _ = markup.preprocess_markdown(src, path, ctx)
            chunks.append(md)
        elif cell.get("cell_type") == "code":
            if src.strip() and not tags & {"remove-input", "remove_input", "hide-input", "hide_input"}:
                if not src.lstrip().startswith(("%%capture",)):
                    chunks.append(markup.fence(src.rstrip(), lang))
            if not tags & {"remove-output", "remove_output"}:
                chunks.extend(render_outputs(cell, idx, nb_key, ctx))
        elif cell.get("cell_type") == "raw":
            fmt = (cell.get("metadata") or {}).get("format", "") or \
                (cell.get("metadata") or {}).get("raw_mimetype", "")
            if "latex" in fmt:
                chunks.append(raw_latex(src))
    return "\n\n".join(c for c in chunks if c.strip()) + "\n", lang, meta


def digest(data):
    raw = "".join(data) if isinstance(data, list) else data
    return hashlib.sha1(base64.b64decode(raw)).hexdigest()[:10]

#!/usr/bin/env python3
"""Re-draw a book's notebook plots as vector PDFs (optional quality pass).

Notebooks store matplotlib plots as PNGs, usually at 72-100 dpi, which look
soft in print.  This script re-executes each notebook of book.yaml with the
inline backend emitting PDF as well as PNG, in the book's sans-serif face
and with the geometry the plots were first drawn with, and compares every
new figure with the stored one.  A vector figure replaces the stored PNG
only where it is the same plot: thumbnails that correlate at 0.97 or more
are accepted; the rest wait for a decision in review.yaml, taken by looking
at the side-by-side sheets this script draws (library drift moves legends
and labels without changing the data; an unseeded random draw changes the
data, and then the stored figure must stay, or it would contradict the text).

Run it with an interpreter that has the notebooks' own dependencies plus
nbclient, ipykernel, numpy, pillow, pypdf, fonttools and pyyaml:

    python3 -m venv fig-env && fig-env/bin/pip install -r requirements.txt \\
        nbclient ipykernel numpy pillow pypdf fonttools pyyaml
    fig-env/bin/python figures.py book.yaml --jobs 3

Writes <vector_figures>/<notebook>/cNNN-K.pdf (cell NNN, K-th image), which
book.py uses when book.yaml sets `vector_figures:` to that folder, plus
report.json and review/*.png.  Decisions go in <vector_figures>/review.yaml:

    01-Introduction:                 # notebook key (as in report.json)
      c012-0: {png: 4f3a9c01de, use: true}             # same plot, newer style
      c031-0: {png: 0be1d2c3aa, use: false, note: unseeded data}

A decision holds only while the stored PNG (its SHA-1 prefix) is unchanged.
"""

import argparse
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

AUTO_ACCEPT = 0.97

SANS = {"charter": ("Fira Sans", ["FiraSans-Book.otf", "FiraSans-BookItalic.otf", "FiraSans-Medium.otf",
                                  "FiraSans-SemiBold.otf", "FiraSans-Bold.otf"]),
        "libertinus": ("Libertinus Sans", ["LibertinusSans-Regular.otf", "LibertinusSans-Italic.otf",
                                           "LibertinusSans-Bold.otf"]),
        "stix": ("Source Sans Pro", ["SourceSansPro-Regular.otf", "SourceSansPro-It.otf",
                                     "SourceSansPro-Semibold.otf", "SourceSansPro-Bold.otf"]),
        "lm": ("Latin Modern Sans", ["lmsans10-regular.otf", "lmsans10-oblique.otf", "lmsans10-bold.otf"])}

# Before 2022 ipykernel's inline backend drew 6x4in figures at 72 dpi with
# 10pt text; later versions use matplotlib's own defaults (100 dpi).
CLASSIC_INLINE = {"figure.figsize": (6.0, 4.0), "figure.dpi": 72, "font.size": 10,
                  "figure.facecolor": (1, 1, 1, 0), "figure.edgecolor": (1, 1, 1, 0),
                  "figure.subplot.bottom": 0.125}


def book_fonts(family):
    return {"font.family": "sans-serif", "font.sans-serif": [family, "DejaVu Sans"],
            "mathtext.fontset": "custom", "mathtext.rm": family, "mathtext.it": f"{family}:italic",
            "mathtext.bf": f"{family}:bold", "pdf.fonttype": 42}


def kpsewhich(name):
    return subprocess.run(["kpsewhich", name], capture_output=True, text=True).stdout.strip()


def inline_rc(classic, family):
    rc = dict(CLASSIC_INLINE) if classic else {}
    rc.update(book_fonts(family))
    return rc


def setup_cell(classic, family, font_paths):
    return "\n".join([
        "from matplotlib import font_manager as _fm",
        f"for _f in {font_paths!r}:",
        "    _fm.fontManager.addfont(_f)",
        "_SANS = {'dejavu sans', 'sans-serif', 'sans', 'arial', 'helvetica',",
        "         'bitstream vera sans', 'liberation sans', 'verdana'}",
        "_findfont = _fm.FontManager.findfont",
        "def _book_findfont(self, prop, *args, **kwargs):",
        "    if isinstance(prop, _fm.FontProperties):",
        "        fam = [f.lower() for f in prop.get_family()]",
        "        if fam and fam[0] in _SANS:",
        "            prop = prop.copy()",
        f"            prop.set_family({family!r})",
        "    return _findfont(self, prop, *args, **kwargs)",
        "_fm.FontManager.findfont = _book_findfont",
        f"%config InlineBackend.rc = {inline_rc(classic, family)!r}",
        "%config InlineBackend.figure_formats = ['png', 'pdf']",
        "%matplotlib inline",
    ])


def image_outputs(cell):
    """Image-bearing outputs of a cell, counted as notebook.py counts them."""
    return [o for o in cell.get("outputs", [])
            if o.get("output_type") in ("execute_result", "display_data")
            and any(k in o.get("data", {}) for k in ("image/png", "image/svg+xml", "image/jpeg",
                                                      "application/pdf"))]


def b64(data):
    return base64.b64decode("".join(data) if isinstance(data, list) else data)


def png_digest(data):
    return hashlib.sha1(b64(data)).hexdigest()[:10]


def rgb_thumb(png, size):
    import numpy as np
    from PIL import Image, ImageFilter
    im = Image.open(io.BytesIO(png)).convert("RGBA")
    im = Image.alpha_composite(Image.new("RGBA", im.size, (255, 255, 255, 255)), im).convert("RGB")
    im = im.resize(size, Image.LANCZOS).filter(ImageFilter.GaussianBlur(1.2))
    return np.asarray(im, dtype=float)


def similarity(orig_png, new_png):
    """Correlation of blurred 160px colour thumbnails, and aspect-ratio drift."""
    from PIL import Image
    ow, oh = Image.open(io.BytesIO(orig_png)).size
    nw, nh = Image.open(io.BytesIO(new_png)).size
    size = (160, max(8, round(160 * oh / ow)))
    a, b = rgb_thumb(orig_png, size), rgb_thumb(new_png, size)
    a, b = a - a.mean(axis=(0, 1)), b - b.mean(axis=(0, 1))
    den = ((a * a).sum() * (b * b).sum()) ** 0.5
    return (float((a * b).sum() / den) if den else 0.0), abs(ow / oh - nw / nh) / (ow / oh)


def classic_inline(nb):
    from PIL import Image
    for cell in nb.cells:
        for o in image_outputs(cell):
            if "image/png" in o["data"]:
                dpi = Image.open(io.BytesIO(b64(o["data"]["image/png"]))).info.get("dpi", (72, 72))
                return round(dpi[0]) <= 72
    return True


def execute(key, path, classic, family, font_paths, work, cwd):
    import nbformat
    from nbclient import NotebookClient
    nb = nbformat.read(path, as_version=4)
    nb.cells.insert(0, nbformat.v4.new_code_cell(setup_cell(classic, family, font_paths)))
    # the old inline backend re-applied its settings at every "%matplotlib inline"
    reapply = f"import matplotlib as _mpl; _mpl.rcParams.update({inline_rc(classic, family)!r})"
    for cell in nb.cells[1:]:
        if cell.cell_type == "code":
            cell.outputs = []
            cell.source = re.sub(r"^([ \t]*)%matplotlib inline[ \t]*$",
                                 lambda m: f"{m.group(0)}\n{m.group(1)}{reapply}", cell.source, flags=re.M)
    client = NotebookClient(nb, timeout=3600, kernel_name="python3", allow_errors=True,
                            resources={"metadata": {"path": str(cwd)}})
    try:
        client.execute()
    except Exception as exc:
        print(f"{key}: execution stopped: {exc}", file=sys.stderr)
    work.mkdir(parents=True, exist_ok=True)
    nbformat.write(nb, work / f"{key}.ipynb")
    nb.cells = nb.cells[1:]
    return nb


def side_by_side(orig_png, new_png, dest):
    from PIL import Image, ImageDraw
    a = Image.open(io.BytesIO(orig_png)).convert("RGB")
    b = Image.open(io.BytesIO(new_png)).convert("RGB")
    h = max(a.size[1], b.size[1])
    b = b.resize((round(b.size[0] * a.size[1] / b.size[1]), a.size[1])) if b.size[1] != a.size[1] else b
    sheet = Image.new("RGB", (a.size[0] + b.size[0] + 30, h + 26), "white")
    sheet.paste(a, (0, 26))
    sheet.paste(b, (a.size[0] + 30, 26))
    d = ImageDraw.Draw(sheet)
    d.text((4, 4), "stored", fill=(160, 0, 0))
    d.text((a.size[0] + 34, 4), "re-drawn", fill=(160, 0, 0))
    dest.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest)


def process(job):
    key, path, family, font_paths, out, reuse, decisions, cwd = job
    import nbformat
    original = nbformat.read(path, as_version=4)
    report = []
    if not any("image/png" in o["data"] for c in original.cells for o in image_outputs(c)):
        return key, report
    for stale in (out / "review").glob(f"{key}-*.png"):
        stale.unlink()
    done = out / "executed" / f"{key}.ipynb"
    if reuse and done.exists():
        rendered = nbformat.read(done, as_version=4)
        rendered.cells = rendered.cells[1:]
    else:
        rendered = execute(key, path, classic_inline(original), family, font_paths, out / "executed", cwd)
    nb_dir = out / key
    for old_pdf in nb_dir.glob("c*.pdf"):
        old_pdf.unlink()
    for idx, (old, new) in enumerate(zip(original.cells, rendered.cells)):
        if old.cell_type != "code":
            continue
        olds, news = image_outputs(old), image_outputs(new)
        for k, o in enumerate(olds):
            entry = {"cell": idx, "k": k, "id": f"c{idx:03d}-{k}"}
            report.append(entry)
            if "image/png" not in o["data"]:
                entry["status"] = "not-a-plot"
                continue
            if k >= len(news) or "application/pdf" not in news[k]["data"]:
                entry["status"] = "missing"
                continue
            orig_png, new_png = b64(o["data"]["image/png"]), b64(news[k]["data"]["image/png"])
            entry["png"] = png_digest(o["data"]["image/png"])
            entry["corr"], entry["aspect"] = (round(x, 4) for x in similarity(orig_png, new_png))
            decision = (decisions.get(key) or {}).get(entry["id"])
            if decision and str(decision.get("png")) == entry["png"]:
                use = bool(decision.get("use"))
                entry["decided"] = True
            else:
                use = entry["corr"] >= AUTO_ACCEPT and entry["aspect"] < 0.03
                if not use:
                    entry["status"] = "needs-review"
                    side_by_side(orig_png, new_png, out / "review" / f"{key}-{entry['id']}.png")
                    continue
            entry["status"] = "vector" if use else "original"
            if use:
                nb_dir.mkdir(parents=True, exist_ok=True)
                (nb_dir / f"{entry['id']}.pdf").write_bytes(fix_fonts(b64(news[k]["data"]["application/pdf"])))
    return key, report


def cff_to_glyf(data):
    """An OpenType-CFF font program rebuilt with TrueType outlines (glyph
    order, hence the glyph ids the PDF uses, unchanged)."""
    from fontTools.pens.cu2quPen import Cu2QuPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib import TTFont, newTable
    font = TTFont(io.BytesIO(data))
    order = font.getGlyphOrder()
    glyph_set = font.getGlyphSet()
    glyf = newTable("glyf")
    glyf.glyphOrder = order
    glyf.glyphs = {}
    for name in order:
        pen = TTGlyphPen(glyph_set)
        glyph_set[name].draw(Cu2QuPen(pen, 1.0, reverse_direction=True))
        glyf.glyphs[name] = pen.glyph()
    font["loca"] = newTable("loca")
    font["glyf"] = glyf
    del font["CFF "]
    if "VORG" in font:
        del font["VORG"]
    glyf.compile(font)
    hmtx = font["hmtx"]
    for name, g in glyf.glyphs.items():
        if hasattr(g, "xMin"):
            hmtx[name] = (hmtx[name][0], g.xMin)
    maxp = font["maxp"] = newTable("maxp")
    maxp.tableVersion = 0x00010000
    maxp.maxZones, maxp.maxTwilightPoints, maxp.maxStorage = 1, 0, 0
    maxp.maxFunctionDefs = maxp.maxInstructionDefs = maxp.maxStackElements = 0
    maxp.maxSizeOfInstructions = maxp.maxComponentElements = 0
    font["post"].formatType = 3.0
    font.sfntVersion = "\0\1\0\0"
    out = io.BytesIO()
    font.save(out)
    return out.getvalue()


def fix_fonts(pdf):
    """matplotlib embeds OpenType-CFF fonts as TrueType (FontFile2), which
    strict PDF readers reject: give those programs TrueType outlines."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject, NumberObject
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf)))
    for page in writer.pages:
        for ref in page["/Resources"].get("/Font", {}).values():
            for desc in ref.get_object().get("/DescendantFonts", []):
                fd = desc.get_object()["/FontDescriptor"].get_object()
                if "/FontFile2" not in fd:
                    continue
                stream = fd["/FontFile2"].get_object()
                data = stream.get_data()
                if data[:4] == b"OTTO":
                    ttf = cff_to_glyf(data)
                    stream.set_data(ttf)
                    stream[NameObject("/Length1")] = NumberObject(len(ttf))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def main():
    import yaml
    import notebook
    from book import Build
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("config")
    ap.add_argument("--only", help="comma-separated notebook keys (see report.json)")
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--reuse", action="store_true", help="re-score last run's executed notebooks")
    args = ap.parse_args()
    os.environ["PYTHONHASHSEED"] = "0"            # kernels inherit it: stable set order
    b = Build(args.config)
    b.plan()
    out = (b.base / str(b.cfg.get("vector_figures") or "vector-figures")).resolve()
    out.mkdir(parents=True, exist_ok=True)
    family, files = SANS.get(b.cfg.get("fonts", "charter"), SANS["charter"])
    font_paths = [p for p in (kpsewhich(f) for f in files) if p]
    if not font_paths:
        sys.exit(f"{family} not found (kpsewhich); install the TeX font package")
    review = out / "review.yaml"
    decisions = yaml.safe_load(review.read_text()) if review.exists() else {}
    jobs = []
    for c in b.chapters():
        for u in c.units:
            if u.fmt == "ipynb":
                key = notebook.figure_key(u.path, b.root)
                if not args.only or key in args.only.split(","):
                    jobs.append((key, u.path, family, font_paths, out, args.reuse, decisions or {}, u.path.parent))
    report_path = out / "report.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else {}
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        for key, entries in pool.map(process, jobs):
            report[key] = entries
            plots = [e for e in entries if e["status"] not in ("not-a-plot",)]
            n = sum(e["status"] == "vector" for e in plots)
            r = sum(e["status"] == "needs-review" for e in plots)
            print(f"{key}: {n}/{len(plots)} vector" + (f", {r} to review" if r else ""), flush=True)
            report_path.write_text(json.dumps(dict(sorted(report.items())), indent=1) + "\n")
    pending = sorted((out / "review").glob("*.png")) if (out / "review").exists() else []
    if pending:
        print(f"\n{len(pending)} figure(s) need a decision; look at {out / 'review'} and record them in {review}")
    if b.cfg.get("vector_figures") is None:
        print(f"\nset  vector_figures: {os.path.relpath(out, b.base)}  in book.yaml to use them")


if __name__ == "__main__":
    main()

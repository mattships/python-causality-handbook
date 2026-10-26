#!/usr/bin/env python3
"""Re-draw the notebooks' matplotlib figures as vector PDFs for the book.

The notebooks store their plots as 72 dpi PNGs, which look soft in print.
This script re-executes every notebook with the inline backend emitting PDF
as well as PNG, in the book's sans-serif face and with the geometry the
notebooks were originally drawn with, and compares each new figure with the
stored one.  A vector figure is used only where the plot is the same plot:
the thumbnail correlation is printed for every figure, and every pair was
also checked by eye (REVIEW below), because library drift moves legends
and labels around without changing the data while, once in a while, a
stored output predates a change to the data.  Everything else keeps its
original PNG, so no figure can disagree with the text around it.

Run it with an interpreter that has the notebooks' dependencies, e.g.

    python3.11 -m venv venv && venv/bin/pip install -r pdf/requirements-figures.txt
    venv/bin/python pdf/figures.py --jobs 3

Writes pdf/figures/<chapter>/cNNN-K.pdf (cell NNN, K-th image of the cell),
which build.py picks up, and pdf/figures/report.json with every score.
"""

import argparse
import base64
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SRC = REPO / "causal-inference-for-the-brave-and-true"
OUT = HERE / "figures"
WORK = HERE / "build" / "executed"

AUTO_ACCEPT = 0.97     # thumbnail correlation that needs no second look

# Decisions from looking at every original/re-drawn pair side by side, keyed
# (chapter, cell, k) -> (SHA-1 prefix of the stored PNG, use the vector?).
# A decision only applies while the stored output is unchanged.
REVIEW = {
    ("ch01", 2, 0): ("c97aef97e2", True),
    ("ch01", 8, 0): ("1dafb40998", True),
    ("ch03", 4, 0): ("692fd42394", True),
    ("ch03", 6, 0): ("974bd881ca", False),  # different scatter (data)
    ("ch03", 10, 0): ("7f94cda715", True),
    ("ch03", 13, 0): ("b40926d5ca", True),
    ("ch03", 16, 0): ("3a8067b2c8", True),
    ("ch03", 20, 0): ("9dfc626cca", True),
    ("ch03", 23, 0): ("d88060180a", True),
    ("ch03", 26, 0): ("0ff46f6d12", True),
    ("ch05", 14, 0): ("4637f14e0c", True),
    ("ch06", 2, 0): ("d6dd1869a0", True),
    ("ch06", 14, 0): ("ec5e3ff508", True),
    ("ch06", 22, 0): ("fe164c379c", True),
    ("ch06", 24, 0): ("7249c07146", True),
    ("ch06", 29, 0): ("3aff30678e", True),
    ("ch07", 6, 0): ("5282f373a3", True),
    ("ch07", 12, 0): ("912a2b3951", True),
    ("ch07", 41, 0): ("59777bef91", False),  # histogram tail differs
    ("ch08", 11, 0): ("b6fa76eca2", True),
    ("ch08", 17, 0): ("98db3ce38c", True),
    ("ch08", 36, 0): ("b59ddd85fe", True),
    ("ch08", 37, 0): ("5fe48391c2", True),
    ("ch11", 9, 0): ("cabb097f90", True),
    ("ch11", 19, 0): ("828553229d", True),
    ("ch11", 21, 0): ("803d3f6d97", True),
    ("ch11", 29, 0): ("c2f20dcf02", False),  # bootstrap draws differ
    ("ch11", 34, 0): ("eeceef70cb", True),
    ("ch11", 36, 0): ("3754b816aa", True),
    ("ch12", 13, 0): ("8019482fc5", False),  # bootstrap draws differ
    ("ch13", 10, 0): ("0aa9309154", True),
    ("ch13", 14, 0): ("9ef2b68453", True),
    ("ch14", 23, 0): ("629970a293", True),
    ("ch14", 25, 0): ("51b9fda1c2", True),
    ("ch15", 5, 0): ("f2a25d166c", True),
    ("ch15", 15, 0): ("0091d34878", True),
    ("ch15", 25, 0): ("099ed7135c", True),
    ("ch15", 27, 0): ("59184c3fab", True),
    ("ch15", 36, 0): ("d14ac84901", True),
    ("ch15", 38, 0): ("a7fb9c9a61", True),
    ("ch15", 44, 0): ("881fe3912b", True),
    ("ch16", 7, 0): ("c66bb3e220", True),
    ("ch16", 11, 0): ("6e4e7d314a", True),
    ("ch16", 13, 0): ("53578a44d2", True),
    ("ch16", 16, 0): ("cae7148c26", True),
    ("ch16", 19, 0): ("569a254ecc", True),
    ("ch16", 21, 0): ("5c74d8285f", True),
    ("ch16", 25, 0): ("3f8e4bc126", True),
    ("ch16", 27, 0): ("210a2fc7d3", True),
    ("ch16", 31, 0): ("908c5de815", True),
    ("ch16", 36, 0): ("07f5fc0ec9", True),
    ("ch17", 12, 0): ("6b15e97fbe", True),
    ("ch17", 14, 0): ("1b94f8f10b", True),
    ("ch17", 18, 0): ("1fb8dfeaf0", False),  # bar colour changed
    ("ch18", 22, 0): ("8336fb9206", True),
    ("ch18", 24, 0): ("ce7cebf7b8", True),
    ("ch19", 17, 0): ("feb3e7eaaa", True),
    ("ch19", 21, 0): ("8a53c5349e", True),
    ("ch19", 26, 0): ("7202b39770", True),
    ("ch19", 32, 0): ("2a22ca935b", True),
    ("ch19", 36, 0): ("63629529a9", True),
    ("ch20", 13, 0): ("160453ecad", True),
    ("ch20", 25, 0): ("407ea354a6", False),  # different curve
    ("ch21", 11, 0): ("4daf99c868", True),
    ("ch21", 15, 0): ("ac479a4f99", True),
    ("ch21", 24, 0): ("81ea063bc9", True),
    ("ch22", 3, 0): ("add77f9094", True),
    ("ch22", 13, 0): ("a67989b9b9", True),
    ("ch22", 17, 0): ("480ed0a7d9", True),
    ("ch22", 25, 0): ("0bf81ab7f5", True),
    ("ch22", 33, 0): ("37d60ed66e", True),
    ("ch22", 37, 0): ("36cbef7e55", True),
    ("ch22", 41, 0): ("34e12436c5", True),
    ("ch22", 55, 0): ("269fbf70f4", True),
    ("ch22", 57, 0): ("46a00e92ef", True),
    ("ch22", 59, 0): ("f1140e216f", True),
    ("ch23", 12, 0): ("b83ca5c011", True),
    ("ch23", 14, 0): ("3857ec44d0", True),
    ("ch23", 16, 0): ("000fc5f3ad", True),
    ("ch23", 20, 0): ("a03149a9d4", True),
    ("ch23", 22, 0): ("8d17ef3172", True),
    ("ch23", 25, 0): ("5554288a52", True),
    ("ch23", 27, 0): ("c5be3ca259", True),
    ("ch23", 29, 0): ("0a58a07057", True),
    ("ch23", 31, 0): ("12a9f2cd1e", True),
    ("ch24", 3, 0): ("79b4fc7e8e", True),
    ("ch24", 11, 0): ("89ceceb65a", True),
    ("ch24", 15, 0): ("f363822a64", True),
    ("ch24", 19, 0): ("e5ddb091a6", True),
    ("ch24", 21, 0): ("eabc73017d", True),
    ("ch24", 24, 0): ("8f88f23e88", True),
    ("ch24", 28, 0): ("a811ad45ce", True),
    ("ch24", 33, 0): ("eadaf33881", False),  # counterfactual differs
    ("ch24", 35, 0): ("7c4da33487", False),  # estimates differ
    ("ch24", 41, 0): ("d2eb457441", True),
    ("ch24", 47, 0): ("e3205b94c9", True),
    ("ch24", 49, 0): ("b724127565", True),
    ("ch25", 9, 0): ("90ad63865c", True),
    ("ch25", 11, 0): ("cc60631f91", True),
    ("ch25", 17, 0): ("57abda6b9c", True),
    ("ch25", 25, 0): ("803229cb34", True),
    ("ch25", 33, 0): ("98e6114d67", True),
    ("ch25", 46, 0): ("0b5b3bb3da", True),
    ("ch25", 51, 0): ("34283b104f", True),
    ("ch25", 54, 0): ("da6539b2ed", True),
    ("ch25", 74, 0): ("5fbaff99cd", True),
    ("appA", 7, 0): ("c53a8271f4", False),  # unseeded data differ
    ("appA", 11, 0): ("51c2250acc", False),  # unseeded data differ
    ("appA", 15, 0): ("bdf4998b1c", False),  # unseeded data differ
    ("appA", 21, 0): ("52e282a48e", False),  # unseeded data differ
    ("appA", 23, 0): ("0545d17aaf", False),  # unseeded data differ
    ("appA", 25, 0): ("08b3d23a08", False),  # unseeded data differ
    ("appA", 32, 0): ("629ad46cef", False),  # unseeded data differ
    ("appB", 10, 0): ("9612d15707", True),
    ("appB", 17, 0): ("9e759d3e6a", True),
    ("appB", 22, 0): ("7aefadcc94", True),
    ("appB", 27, 0): ("77491274e5", True),
    ("appB", 33, 0): ("76c01ca014", True),
    ("appB", 36, 0): ("42a554b982", True),
    ("appB", 40, 0): ("acf58159e9", True),
    ("appB", 45, 0): ("96a845442c", True),
    ("appB", 49, 0): ("8a2ec647b8", True),
    ("appD", 14, 0): ("ae93d8b35b", True),
    ("appE", 3, 0): ("3eef7d07ac", True),
    ("appE", 9, 0): ("a920c60603", True),
    ("appE", 11, 0): ("da1b273a2e", True),
    ("appE", 13, 0): ("97370692f7", True),
    ("appE", 16, 0): ("9337992fe3", True),
    ("appE", 22, 0): ("439e7eef7e", True),
    ("appE", 39, 0): ("fb3180772f", True),
    ("appE", 44, 0): ("f99ac2569e", True),
}

FONT_FILES = ["FiraSans-Book.otf", "FiraSans-BookItalic.otf", "FiraSans-Medium.otf",
              "FiraSans-MediumItalic.otf", "FiraSans-SemiBold.otf", "FiraSans-Bold.otf"]

# Before 2022 ipykernel's inline backend drew 6x4in figures at 72 dpi with
# 10pt text; later versions use matplotlib's own defaults (100 dpi).
CLASSIC_INLINE = {
    "figure.figsize": (6.0, 4.0), "figure.dpi": 72, "font.size": 10,
    "figure.facecolor": (1, 1, 1, 0), "figure.edgecolor": (1, 1, 1, 0),
    "figure.subplot.bottom": 0.125,
}
BOOK_FONTS = {
    "font.family": "sans-serif", "font.sans-serif": ["Fira Sans", "DejaVu Sans"],
    "mathtext.fontset": "custom", "mathtext.rm": "Fira Sans",
    "mathtext.it": "Fira Sans:italic", "mathtext.bf": "Fira Sans:bold",
    "pdf.fonttype": 42,
}


def kpsewhich(name):
    return subprocess.run(["kpsewhich", name], capture_output=True, text=True).stdout.strip()


def setup_cell(classic, font_paths):
    rc = inline_rc(classic)
    return "\n".join([
        "from matplotlib import font_manager as _fm",
        f"for _f in {font_paths!r}:",
        "    _fm.fontManager.addfont(_f)",
        # Explicit requests for the usual defaults also get the book face.
        "_SANS = {'dejavu sans', 'sans-serif', 'sans', 'arial', 'helvetica',",
        "         'bitstream vera sans', 'liberation sans', 'verdana'}",
        "_findfont = _fm.FontManager.findfont",
        "def _book_findfont(self, prop, *args, **kwargs):",
        "    if isinstance(prop, _fm.FontProperties):",
        "        fam = [f.lower() for f in prop.get_family()]",
        "        if fam and fam[0] in _SANS:",
        "            prop = prop.copy()",
        "            prop.set_family('Fira Sans')",
        "    return _findfont(self, prop, *args, **kwargs)",
        "_fm.FontManager.findfont = _book_findfont",
        f"%config InlineBackend.rc = {rc!r}",
        "%config InlineBackend.figure_formats = ['png', 'pdf']",
        "%matplotlib inline",
    ])


def image_outputs(cell):
    """The image-bearing outputs of a cell, in the order build.py counts them."""
    return [o for o in cell.get("outputs", [])
            if o.get("output_type") in ("execute_result", "display_data")
            and any(k in o.get("data", {}) for k in ("image/png", "image/svg+xml", "image/jpeg"))]


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
    """Colour-aware correlation of blurred 160px thumbnails, and the
    relative difference in aspect ratio."""
    from PIL import Image
    ow, oh = Image.open(io.BytesIO(orig_png)).size
    nw, nh = Image.open(io.BytesIO(new_png)).size
    size = (160, max(8, round(160 * oh / ow)))
    a, b = rgb_thumb(orig_png, size), rgb_thumb(new_png, size)
    a, b = a - a.mean(axis=(0, 1)), b - b.mean(axis=(0, 1))
    den = ((a * a).sum() * (b * b).sum()) ** 0.5
    corr = float((a * b).sum() / den) if den else 0.0
    return corr, abs(ow / oh - nw / nh) / (ow / oh)


def inline_rc(classic):
    rc = dict(CLASSIC_INLINE) if classic else {}
    rc.update(BOOK_FONTS)
    return rc


def execute(slug, path, classic, font_paths):
    import nbformat
    from nbclient import NotebookClient
    nb = nbformat.read(path, as_version=4)
    nb.cells.insert(0, nbformat.v4.new_code_cell(setup_cell(classic, font_paths)))
    # The old inline backend re-applied its settings on every
    # "%matplotlib inline", on top of any style loaded before it.
    reapply = f"import matplotlib as _mpl; _mpl.rcParams.update({inline_rc(classic)!r})"
    for cell in nb.cells[1:]:
        if cell.cell_type == "code":
            cell.outputs = []
            cell.source = re.sub(r"^([ \t]*)%matplotlib inline[ \t]*$",
                                 lambda m: f"{m.group(0)}\n{m.group(1)}{reapply}",
                                 cell.source, flags=re.M)
    client = NotebookClient(nb, timeout=3600, kernel_name="python3", allow_errors=True,
                            resources={"metadata": {"path": str(SRC)}})
    try:
        client.execute()
    except Exception as exc:                       # kernel death and the like
        print(f"{slug}: execution aborted: {exc}", file=sys.stderr)
    WORK.mkdir(parents=True, exist_ok=True)
    nbformat.write(nb, WORK / f"{slug}.ipynb")
    nb.cells = nb.cells[1:]
    return nb


def classic_inline(nb):
    """Were this notebook's figures drawn by the 72 dpi inline backend?"""
    from PIL import Image
    for cell in nb.cells:
        for o in image_outputs(cell):
            if "image/png" in o["data"]:
                dpi = Image.open(io.BytesIO(b64(o["data"]["image/png"]))).info.get("dpi", (72, 72))
                return round(dpi[0]) <= 72
    return True


def process(job):
    slug, path, font_paths, reuse = job
    import nbformat
    original = nbformat.read(path, as_version=4)
    report = []
    if not any("image/png" in o["data"] for c in original.cells for o in image_outputs(c)):
        return slug, report
    done = WORK / f"{slug}.ipynb"
    if reuse and done.exists():
        rendered = nbformat.read(done, as_version=4)
        rendered.cells = rendered.cells[1:]
    else:
        rendered = execute(slug, path, classic_inline(original), font_paths)
    out_dir = OUT / slug
    if out_dir.exists():
        shutil.rmtree(out_dir)
    for idx, (old, new) in enumerate(zip(original.cells, rendered.cells)):
        if old.cell_type != "code":
            continue
        olds, news = image_outputs(old), image_outputs(new)
        for k, o in enumerate(olds):
            entry = {"cell": idx, "k": k}
            report.append(entry)
            if "image/png" not in o["data"]:
                entry["status"] = "not-a-plot"        # graphviz SVG and the like
                continue
            if k >= len(news) or "application/pdf" not in news[k]["data"]:
                entry["status"] = "missing"
                continue
            entry["corr"], entry["aspect"] = (round(x, 4) for x in similarity(
                b64(o["data"]["image/png"]), b64(news[k]["data"]["image/png"])))
            review = REVIEW.get((slug, idx, k))
            if review and review[0] == png_digest(o["data"]["image/png"]):
                verdict = review[1]
            else:
                verdict = entry["corr"] >= AUTO_ACCEPT
                entry["reviewed"] = False
            entry["status"] = "vector" if verdict else "original"
            if verdict:
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / f"c{idx:03d}-{k}.pdf").write_bytes(fix_fonts(b64(news[k]["data"]["application/pdf"])))
    return slug, report


def cff_to_glyf(data):
    """Rebuild an OpenType-CFF font program with TrueType outlines.

    Glyph order (hence every glyph id the PDF uses) is kept as it is.
    """
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
    font["post"].formatType = 3.0                 # glyph names are not needed
    font.sfntVersion = "\0\1\0\0"
    out = io.BytesIO()
    font.save(out)
    return out.getvalue()


def fix_fonts(pdf):
    """matplotlib embeds OpenType-CFF fonts as TrueType (FontFile2), which
    strict PDF readers reject; give those font programs TrueType outlines."""
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


def chapters():
    sys.path.insert(0, str(HERE))
    from build import load_toc
    return [(ch.slug, ch.path) for part in load_toc() for ch in part.chapters]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", help="comma-separated chapter slugs, e.g. ch01,appA")
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--reuse", action="store_true",
                    help="re-score the notebooks executed last time instead of running them")
    args = ap.parse_args()
    os.environ["PYTHONHASHSEED"] = "0"            # kernels inherit it: stable set order
    font_paths = [kpsewhich(f) for f in FONT_FILES]
    if not all(font_paths):
        sys.exit("Fira Sans not found (kpsewhich); install TeX Live's fira package")
    jobs = [(slug, path, font_paths, args.reuse) for slug, path in chapters()
            if not args.only or slug in args.only.split(",")]
    report_path = OUT / "report.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else {}
    OUT.mkdir(exist_ok=True)
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        for slug, entries in pool.map(process, jobs):
            report[slug] = entries
            plots = [e for e in entries if e["status"] != "not-a-plot"]
            n = sum(e["status"] == "vector" for e in plots)
            print(f"{slug}: {n}/{len(plots)} figures redrawn as vectors", flush=True)
            report_path.write_text(json.dumps(dict(sorted(report.items())), indent=1) + "\n")


if __name__ == "__main__":
    main()

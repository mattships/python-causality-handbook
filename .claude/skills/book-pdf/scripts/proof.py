#!/usr/bin/env python3
"""Proof a typeset book: page images to look at, and the checks a
production editor would make.

  proof.py BOOK.pdf                      checks + contact sheets of every page
  proof.py BOOK.pdf --pages 1-8,120      those pages at reading size
  proof.py BOOK.pdf --find "some text"   pages where a phrase occurs

Writes PNGs to <pdf name>-proof/ next to the PDF and prints their paths;
open them (the Read tool shows images) and look before calling a book done.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def page_count(pdf):
    out = run(["pdfinfo", str(pdf)]).stdout
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    return int(m.group(1)) if m else 0


def parse_pages(spec, n):
    pages = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            pages += range(int(a or 1), int(b or n) + 1)
        elif part:
            pages.append(int(part))
    return [p for p in pages if 1 <= p <= n]


def render(pdf, page, dpi, out):
    stem = out / f"p{page:04d}-{dpi}"
    run(["pdftoppm", "-r", str(dpi), "-f", str(page), "-l", str(page), "-png", "-singlefile",
         str(pdf), str(stem)])
    return stem.with_suffix(".png")


def contact_sheets(pdf, n, out, per_sheet=24, cols=6, dpi=28):
    from PIL import Image, ImageDraw
    tmp = out / "thumbs"
    tmp.mkdir(parents=True, exist_ok=True)
    run(["pdftoppm", "-r", str(dpi), "-png", str(pdf), str(tmp / "t")])
    thumbs = sorted(tmp.glob("t-*.png"), key=lambda p: int(re.findall(r"\d+", p.stem)[-1]))
    sheets = []
    for s in range(0, len(thumbs), per_sheet):
        group = thumbs[s:s + per_sheet]
        ims = [Image.open(p).convert("RGB") for p in group]
        w = max(i.size[0] for i in ims)
        h = max(i.size[1] for i in ims)
        rows = (len(ims) + cols - 1) // cols
        pad = 14
        sheet = Image.new("RGB", (cols * (w + pad) + pad, rows * (h + pad + 12) + pad), (120, 120, 120))
        d = ImageDraw.Draw(sheet)
        for k, im in enumerate(ims):
            x = pad + (k % cols) * (w + pad)
            y = pad + (k // cols) * (h + pad + 12)
            sheet.paste(im, (x, y + 12))
            d.text((x, y), str(s + k + 1), fill=(255, 255, 255))
        path = out / f"sheet-{s // per_sheet + 1:02d}.png"
        sheet.save(path)
        sheets.append(path)
    for p in thumbs:
        p.unlink()
    tmp.rmdir()
    return sheets


def check_fonts(pdf):
    out = run(["pdffonts", str(pdf)]).stdout.splitlines()[2:]
    problems = []
    for line in out:
        cols = line.split()
        if len(cols) < 5:
            continue
        # name type [encoding] emb sub uni object ID
        emb = cols[-5] if len(cols) >= 7 else "?"
        if emb != "yes":
            problems.append(line.strip())
        if "Type 3" in line:
            problems.append("Type 3 (bitmap) font: " + line.strip())
    return problems


def blank_pages(pdf, n):
    """Pages with almost no text (blank versos are expected; others are not)."""
    text = run(["pdftotext", "-layout", str(pdf), "-"]).stdout.split("\f")
    out = []
    for i, t in enumerate(text[:n], 1):
        if len(t.strip()) < 3:
            out.append(i)
    return out


def find(pdf, phrase):
    text = run(["pdftotext", str(pdf), "-"]).stdout.split("\f")
    norm = lambda s: re.sub(r"\s+", " ", s).lower()
    return [i for i, t in enumerate(text, 1) if norm(phrase) in norm(t)]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("pdf")
    ap.add_argument("--pages", help="pages to render at reading size, e.g. 1-6,42")
    ap.add_argument("--dpi", type=int, default=100)
    ap.add_argument("--find", help="list the pages where this text occurs")
    ap.add_argument("--no-sheets", action="store_true")
    args = ap.parse_args()
    pdf = Path(args.pdf).resolve()
    n = page_count(pdf)
    out = pdf.parent / f"{pdf.stem}-proof"
    out.mkdir(exist_ok=True)
    if args.find:
        print("pages:", find(pdf, args.find))
        return
    if args.pages:
        for p in parse_pages(args.pages, n):
            print(render(pdf, p, args.dpi, out))
        return
    print(f"{pdf.name}: {n} pages")
    fonts = check_fonts(pdf)
    print("fonts: all embedded" if not fonts else "font problems:\n  " + "\n  ".join(fonts[:10]))
    blanks = blank_pages(pdf, n)
    print(f"blank pages: {len(blanks)}" + (f" ({', '.join(map(str, blanks[:30]))})" if blanks else "")
          + " -- versos before chapters and parts are expected")
    report = pdf.parent / "book-build" / "report.json"
    if report.exists():
        r = json.loads(report.read_text())
        print(f"overfull lines: {sum((r.get('overfull') or {}).values())}, "
              f"missing glyphs: {len(r.get('missing_glyphs') or {})}, "
              f"undefined references: {len(r.get('undefined_refs') or [])}, "
              f"warnings: {len(r.get('warnings') or [])}")
    if not args.no_sheets:
        for s in contact_sheets(pdf, n, out):
            print(s)


if __name__ == "__main__":
    sys.exit(main())

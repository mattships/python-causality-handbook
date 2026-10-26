#!/usr/bin/env python3
"""Typeset documentation, notebooks, manuscripts or source code as a
publisher-quality PDF book (pandoc + LuaLaTeX, memoir).

  book.py doctor                          check the toolchain
  book.py init SOURCE [-o book.yaml]      propose the book's structure
  book.py build book.yaml [--only 3,A]    typeset it

The design (assets/) is fixed; book.yaml chooses the content, the metadata
and a few knobs: trim size, fonts, accent colour.  See references/config.md.
"""

import argparse
import datetime
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import yaml  # noqa: E402

import astutil as A  # noqa: E402
import markup  # noqa: E402
import notebook  # noqa: E402
import postprocess as P  # noqa: E402
import structure as S  # noqa: E402
from autodoc import Autodoc, info_fields  # noqa: E402

ASSETS = HERE.parent / "assets"

# Markdown dialects.  CommonMark (as Jupyter, MyST, GitHub and MkDocs mostly
# are) without the extensions that misfire on ordinary prose.
MD_FORMAT = "commonmark_x-subscript-superscript-yaml_metadata_block-emoji-fancy_lists"
NB_FORMAT = MD_FORMAT + "-definition_lists"
QMD_FORMAT = "markdown-yaml_metadata_block-implicit_figures"
MD_WRITE = "commonmark_x-subscript-superscript-emoji"
PANDOC_READERS = {"org", "textile", "mediawiki", "docbook", "rtf", "typst", "jats", "fb2",
                  "opml", "man", "muse", "t2t", "creole", "dokuwiki", "tikiwiki", "twiki",
                  "vimwiki", "haddock", "jira", "endnotexml", "ris", "bibtex", "csljson"}

# Trim sizes: stock w, stock h, text w (in), text h (in), spine margin, top
# margin, code size/leading (pt), class font size.
TRIMS = {
    "7x10": ("7in", "10in", 5.25, 8.05, "0.82in", "0.9in", 8.6, 10.6, "10pt"),
    "6x9": ("6in", "9in", 4.5, 7.15, "0.72in", "0.8in", 8.0, 10.0, "10pt"),
    "royal": ("6.14in", "9.21in", 4.6, 7.35, "0.72in", "0.82in", 8.0, 10.0, "10pt"),
    "7x9.19": ("7in", "9.19in", 5.25, 7.3, "0.82in", "0.85in", 8.6, 10.6, "10pt"),
    "7.5x9.25": ("7.5in", "9.25in", 5.55, 7.4, "0.88in", "0.85in", 8.8, 10.8, "10pt"),
    "8x10": ("8in", "10in", 5.9, 8.05, "0.95in", "0.9in", 9.0, 11.0, "11pt"),
    "b5": ("176mm", "250mm", 5.0, 7.8, "0.72in", "0.8in", 8.4, 10.4, "10pt"),
    "a5": ("148mm", "210mm", 4.15, 6.5, "0.62in", "0.7in", 7.8, 9.8, "10pt"),
    "a4": ("210mm", "297mm", 5.9, 9.3, "1in", "1in", 9.0, 11.0, "11pt"),
    "letter": ("8.5in", "11in", 6.0, 8.9, "1in", "0.95in", 9.0, 11.0, "11pt"),
}
FONT_SETS = {
    "charter": ("XCharter-Roman.otf", "FiraSans-Book.otf", "Inconsolatazi4-Regular.otf", "XCharter-Math.otf"),
    "libertinus": ("LibertinusSerif-Regular.otf", "LibertinusSans-Regular.otf",
                   "Inconsolatazi4-Regular.otf", "LibertinusMath-Regular.otf"),
    "stix": ("STIXTwoText-Regular.otf", "SourceSansPro-Regular.otf", "SourceCodePro-Regular.otf",
             "STIXTwoMath-Regular.otf"),
    "lm": ("lmroman10-regular.otf", "lmsans10-regular.otf", "lmmono10-regular.otf", "latinmodern-math.otf"),
}
FONT_NAMES = {                       # text, headings, code
    "charter": ("XCharter", "Fira Sans", "Inconsolata"),
    "libertinus": ("Libertinus Serif", "Libertinus Sans", "Inconsolata"),
    "stix": ("STIX Two", "Source Sans Pro", "Source Code Pro"),
    "lm": ("Latin Modern Roman", "Latin Modern Sans", "Latin Modern Mono"),
}
LANG_LABEL = {"python": "Python", "javascript": "JavaScript", "typescript": "TypeScript",
              "cpp": "C++", "cs": "C#", "c": "C", "bash": "Shell", "zsh": "Shell", "yaml": "YAML",
              "toml": "TOML", "json": "JSON", "ini": "INI", "xml": "XML", "html": "HTML",
              "css": "CSS", "scss": "SCSS", "sql": "SQL", "php": "PHP", "objectivec": "Objective-C",
              "makefile": "Makefile", "dockerfile": "Dockerfile", "cmake": "CMake", "r": "R",
              "fsharp": "F#", "ocaml": "OCaml", "powershell": "PowerShell", "dosbat": "Batch",
              "plain": "Text", "commonlisp": "Lisp", "latex": "LaTeX", "markdown": "Markdown"}
BABEL = {"en": "english", "en-us": "american", "en-gb": "british", "pt": "portuguese",
         "pt-br": "brazilian", "de": "ngerman", "fr": "french", "es": "spanish", "it": "italian",
         "nl": "dutch", "sv": "swedish", "da": "danish", "nb": "norsk", "fi": "finnish",
         "pl": "polish", "cs": "czech", "ru": "russian", "uk": "ukrainian", "el": "greek",
         "tr": "turkish", "hu": "magyar", "ro": "romanian", "ca": "catalan", "ja": "japanese",
         "zh": "chinese", "ko": "korean", "id": "indonesian", "vi": "vietnamese"}
BADGE = re.compile(r"(shields\.io|badge\.fury\.io|badgen\.net|travis-ci\.|codecov\.io/|coveralls\.io/|"
                   r"/badge(s)?[./?]|badge\.svg|readthedocs\.org/projects/[^/]+/badge|pepy\.tech/badge|"
                   r"circleci\.com/.+\.svg|github\.com/.+/workflows/.+\.svg|anaconda\.org/.+/badges|"
                   r"zenodo\.org/badge|mybinder\.org/badge|colab\.research\.google\.com/assets/colab-badge)",
                   re.I)
TEX_ESC = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
           "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}


def tex(s):
    """Text for LaTeX: escaped, with typographic quotes."""
    return "".join(TEX_ESC.get(c, c) for c in P.curl(str(s)))


def slugify(s, n=40):
    s = re.sub(r"[^A-Za-z0-9]+", "-", str(s)).strip("-")
    return (s[:n].rstrip("-") or "book")


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def which_version(cmd, pattern):
    try:
        out = run(cmd)
        m = re.search(pattern, out.stdout + out.stderr)
        return m.group(1) if m else "?"
    except (OSError, FileNotFoundError):
        return None


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------

def doctor():
    ok = True
    print("book-pdf toolchain\n")
    tools = [("pandoc", ["pandoc", "--version"], r"pandoc ([\d.]+)", True),
             ("lualatex", ["lualatex", "--version"], r"(LuaHBTeX|LuaTeX)[^\n]*?([\d.]+)", True),
             ("latexmk", ["latexmk", "--version"], r"Version ([\d.a-z]+)", True),
             ("makeindex", ["makeindex", "-q", "/dev/null"], r"()", True),
             ("rsvg-convert", ["rsvg-convert", "--version"], r"version ([\d.]+)", False),
             ("gs", ["gs", "--version"], r"([\d.]+)", False),
             ("pdftoppm", ["pdftoppm", "-v"], r"version ([\d.]+)", False),
             ("pdffonts", ["pdffonts", "-v"], r"version ([\d.]+)", False)]
    for name, cmd, pat, required in tools:
        v = which_version(cmd, pat)
        state = "ok " if v is not None else ("MISSING" if required else "missing (optional)")
        if v is None and required:
            ok = False
        print(f"  {name:<14} {state} {v or ''}")
    pv = which_version(["pandoc", "--version"], r"pandoc ([\d.]+)")
    if pv and tuple(int(x) for x in re.findall(r"\d+", pv)[:2]) < (3, 1):
        print("  pandoc 3.1 or newer is needed")
        ok = False
    print()
    for fs, files in FONT_SETS.items():
        missing = [f for f in files if not run(["kpsewhich", f]).stdout.strip()]
        print(f"  fonts {fs:<10} {'ok' if not missing else 'missing: ' + ', '.join(missing)}")
        if fs == "charter" and missing:
            ok = False
    dejavu = run(["fc-list", "DejaVu Sans"]).stdout.strip() if shutil.which("fc-list") else ""
    print(f"  fonts {'fallback':<10} {'ok (DejaVu)' if dejavu or run(['kpsewhich', 'DejaVuSans.ttf']).stdout.strip() else 'missing DejaVu (fonts-dejavu-core)'}")
    print()
    for mod in ("yaml", "PIL", "bs4", "lxml", "pypdf"):
        try:
            __import__(mod)
            print(f"  python {mod:<9} ok")
        except ImportError:
            print(f"  python {mod:<9} MISSING")
            ok = False
    if not ok:
        print("\nInstall what is missing, e.g. on Debian/Ubuntu:\n"
              "  apt-get install -y pandoc texlive-luatex texlive-latex-extra texlive-fonts-extra \\\n"
              "      texlive-science latexmk librsvg2-bin poppler-utils ghostscript fonts-dejavu-core\n"
              "  pip install pyyaml pillow beautifulsoup4 lxml pypdf\n"
              "on macOS: brew install pandoc librsvg poppler && brew install --cask mactex-no-gui\n"
              "(pandoc must be 3.1+: https://github.com/jgm/pandoc/releases)")
    print("\n" + ("ready" if ok else "not ready"))
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

LICENSES = [
    (r"Permission is hereby granted, free of charge", "MIT License"),
    (r"Apache License[\s\S]{0,80}Version 2\.0", "Apache License 2.0"),
    (r"Redistribution and use in source and binary forms[\s\S]*Neither the name", "BSD 3-Clause License"),
    (r"Redistribution and use in source and binary forms", "BSD 2-Clause License"),
    (r"GNU LESSER GENERAL PUBLIC LICENSE", "GNU Lesser General Public License"),
    (r"GNU AFFERO GENERAL PUBLIC LICENSE", "GNU Affero General Public License"),
    (r"GNU GENERAL PUBLIC LICENSE[\s\S]{0,60}Version 3", "GNU General Public License v3"),
    (r"GNU GENERAL PUBLIC LICENSE[\s\S]{0,60}Version 2", "GNU General Public License v2"),
    (r"Mozilla Public License[\s\S]{0,30}2\.0", "Mozilla Public License 2.0"),
    (r"Attribution-NonCommercial-ShareAlike 4\.0", "CC BY-NC-SA 4.0"),
    (r"Attribution-NonCommercial 4\.0", "CC BY-NC 4.0"),
    (r"Attribution-ShareAlike 4\.0", "CC BY-SA 4.0"),
    (r"Attribution 4\.0 International", "CC BY 4.0"),
    (r"free and unencumbered software released into the public domain", "The Unlicense"),
    (r"Permission to use, copy, modify, and(/or)? distribute this software for any purpose", "ISC License"),
]


def find_license(start, stop):
    d = Path(start).resolve()
    stop = Path(stop).resolve()
    for _ in range(3):
        for name in ("LICENSE", "LICENSE.txt", "LICENSE.md", "LICENSE.rst", "LICENCE", "LICENCE.txt",
                     "COPYING", "COPYING.txt"):
            p = d / name
            if p.is_file():
                return p
        if d == stop or d.parent == d:
            break
        d = d.parent
    return None


def git_info(path):
    def git(*args):
        return run(["git", "-C", str(path), *args]).stdout.strip()
    top = git("rev-parse", "--show-toplevel")
    if not top:
        return None, None
    url = git("remote", "get-url", "origin")
    m = re.match(r"(?:git@github\.com:|https://github\.com/)([^/]+/[^/.]+?)(?:\.git)?/?$", url)
    branch = "main"
    head = git("symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if head:
        branch = head.split("/", 1)[-1]
    base = f"https://github.com/{m.group(1)}/blob/{branch}/" if m else None
    return Path(top), base


INIT_HEADER = """\
# book.yaml -- what book-pdf typesets.  Written by `book.py init`; edit freely.
# Paths are relative to `root`.  Every key is explained in references/config.md.
#
# Chapters: a path; or {path, title} to retitle; or {path, sections: [...]} to
# fold more files into one chapter; or {path, split: true} to cut one long
# file into chapters at its top headings; or {code: dir} for a chapter of
# source listings.  `front` chapters are unnumbered (preface); `appendix`
# chapters are lettered.
"""


def file_meta(path):
    """Title, subtitle and author that a document carries itself."""
    fmt = S.fmt_of(path)
    reader = {"docx": "docx", "odt": "odt", "epub": "epub", "latex": "latex", "html": "html",
              "md": "commonmark_x", "qmd": "markdown", "rmd": "markdown", "rst": "rst",
              "org": "org"}.get(fmt)
    if not reader:
        return {}
    try:
        doc, _ = A.read(path, reader, is_path=True, cwd=str(Path(path).parent))
    except A.PandocError:
        return {}
    meta = doc.get("meta", {})
    out = {k: A.meta_text(meta, k) for k in ("title", "subtitle", "author")}
    if isinstance(meta.get("author"), dict) and meta["author"].get("t") == "MetaList":
        out["author"] = ", ".join(A.meta_text({"a": a}, "a") or "" for a in meta["author"]["c"])
    if not out.get("title"):
        # no document properties: a short title block before the first heading
        lead = []
        for b in unwrap_divs(doc["blocks"]):
            if b["t"] == "Header":
                break
            if b["t"] in ("Para", "Plain") and A.stringify(b).strip():
                lead.append(A.stringify(b).strip())
        if 1 <= len(lead) <= 4 and len(" ".join(lead).split()) <= 45:
            out["title"] = lead[0]
            if len(lead) > 1 and len(lead[1].split()) <= 16:
                out["subtitle"] = lead[1]
            if len(lead) > 2 and len(lead[2].split()) <= 8:
                out["author"] = lead[2]
    return {k: v for k, v in out.items() if v}


def init(source, out_path):
    prop = S.propose(source)
    if Path(source).is_file():
        prop.meta.update(file_meta(Path(source).resolve()))
    cfg = prop.to_config()
    out_path = Path(out_path).resolve()
    root = Path(cfg["root"]).resolve()
    meta = {}
    title = cfg.get("title") or root.name
    if not cfg.get("subtitle") and ": " in str(title):
        title, sub = str(title).split(": ", 1)
        cfg["subtitle"] = sub
    meta["title"] = str(title)
    for k in ("subtitle", "author"):
        if cfg.get(k):
            meta[k] = str(cfg[k])
    meta["author"] = meta.get("author") or ""
    top, link_base = git_info(root)
    lic = find_license(root, top or root.parent.parent)
    if lic:
        text = lic.read_text(errors="replace")
        for pat, name in LICENSES:
            if re.search(pat, text, re.I):
                meta["license"] = name
                break
        m = re.search(r"^\s*Copyright\s+(?:\(c\)|©)?\s*([^\n]{3,80})", text, re.M | re.I)
        if m and not cfg.get("copyright"):
            meta["copyright"] = "Copyright © " + m.group(1).strip().rstrip(".") + "."
        if len(text) < 2600:
            rel = os.path.relpath(lic, out_path.parent)
            meta["license_file"] = rel if rel.count("..") <= 3 else str(lic)
    if cfg.get("copyright"):
        meta["copyright"] = cfg["copyright"]
    if cfg.get("cover_image"):
        meta["cover_image"] = cfg["cover_image"]
    lang = "english"
    conf = root / "conf.py"
    if conf.exists():
        m = re.search(r"^language\s*=\s*['\"]([\w-]+)['\"]", conf.read_text(errors="replace"), re.M)
        if m:
            lang = BABEL.get(m.group(1).lower(), BABEL.get(m.group(1)[:2].lower(), "english"))
    meta.update(language=lang, trim="7x10", fonts="charter", accent="9A1F26")
    rel_root = os.path.relpath(root, out_path.parent)
    if rel_root.count("..") > 3:
        rel_root = str(root)
    body = {"root": rel_root, "output": slugify(meta["title"], 60) + ".pdf"}
    for key in ("front", "parts", "chapters", "appendix"):
        if cfg.get(key):
            body[key] = cfg[key]
    opts = {"index": "auto"}
    if cfg.get("link_base") or link_base:
        opts["link_base"] = cfg.get("link_base") or link_base
    if cfg.get("myst"):
        opts["myst"] = True
    if cfg.get("code_roots"):
        opts["code_roots"] = cfg["code_roots"]
    for key in ("bibliography", "csl"):
        if cfg.get(key):
            opts[key] = cfg[key]
    if prop.kind == "code book":
        opts["default_language"] = "plain"
    text = INIT_HEADER + "\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=100) + "\n" + \
        yaml.safe_dump(body, sort_keys=False, allow_unicode=True, width=100) + "\n" + \
        yaml.safe_dump(opts, sort_keys=False, allow_unicode=True, width=100)
    out_path.write_text(text)
    n_ch = len(cfg.get("chapters", [])) + sum(len(p["chapters"]) for p in cfg.get("parts", []))
    print(f"{prop.kind}: {len(cfg.get('front', []))} front, {n_ch} chapters"
          f"{' in ' + str(len(cfg['parts'])) + ' parts' if cfg.get('parts') else ''}, "
          f"{len(cfg.get('appendix', []))} appendix -> {out_path}")
    for n in prop.notes:
        print("  note:", n)
    return 0


# ---------------------------------------------------------------------------
# The book's structure
# ---------------------------------------------------------------------------

class Unit(P.UnitContext):
    """One source file (or one piece of a split file) and its pandoc tree."""

    def __init__(self, book, path, slug, fmt, role="chapter", title=None, blocks=None, files=None):
        super().__init__(book, path, slug, fmt)
        self.role = role              # chapter | section
        self.title = title            # text, or inlines from a split file
        self.preset = blocks          # blocks of a split piece
        self.files = files            # source files of a code chapter
        self.doc = None
        self.title_inlines = None


class Chapter:
    def __init__(self, kind, title=None):
        self.kind = kind              # front | main | appendix | back
        self.title = title
        self.units = []
        self.slug = None
        self.number = None
        self.title_inlines = None


class PartBreak:
    def __init__(self, title):
        self.title = title


PART_HEAD = re.compile(r"^\s*part\s+([IVXLC]+|\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b"
                       r"\s*[-:.–—]?\s*", re.I)
APPENDIX_HEAD = re.compile(r"^\s*(appendix|appendices|annex)\b\s*([A-Z]|\d+)?\s*[-:.–—]?\s*", re.I)
VERSIONISH = re.compile(r"^\s*(v(ersion)?\.?\s*|release\s+)?\d+(\.\d+)+|^\s*\d{4}-\d{2}-\d{2}", re.I)
FRONT_HEAD = re.compile(r"^\s*(abstract|summary|executive summary|preface|foreword|prologue|"
                        r"acknowledg(e)?ments?|dedication|about this (book|report|document))\s*$", re.I)
BACK_HEAD = re.compile(r"^\s*(references|bibliography|works cited|literature cited|index)\s*$", re.I)


def clean_title(text, strip_numbers=True):
    t = re.sub(r"\s+", " ", text).strip()
    if strip_numbers:
        t = re.sub(r"^(chapter|lesson|lecture|unit|module|session|week)\s+[\dIVXLC]+\s*[-:.–—]?\s*", "", t, flags=re.I)
        t = re.sub(r"^\d+(\.\d+)*[a-z]?\s*[-:.)–—]\s*", "", t)
    return t.strip() or text.strip()


SMALL_WORDS = {"a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "into", "nor", "of",
               "on", "or", "the", "to", "vs", "with", "via"}


def title_case(title):
    out = []
    for i, w in enumerate(title.split()):
        after_colon = out and out[-1].endswith(":")
        if i and not after_colon and w.lower() in SMALL_WORDS:
            out.append(w.lower())
        elif w[:1].islower() and not re.search(r"[A-Z_./()]", w[1:]):
            out.append(w[0].upper() + w[1:])
        else:
            out.append(w)
    return " ".join(out)


def drop_prefix(inlines, n):
    """Remove the first n characters of plain-text inlines."""
    out, k = [], 0
    for il in inlines:
        if k >= n:
            out.append(il)
            continue
        s = A.stringify(il)
        if il["t"] in ("Str", "Space", "SoftBreak") and k + len(s) <= n:
            k += len(s)
            continue
        if il["t"] == "Str":
            out.append(A.Str(s[n - k:]))
            k = n
            continue
        out.append(il)
        k = n
    while out and out[0]["t"] in ("Space", "SoftBreak"):
        out.pop(0)
    return out


def fix_title(inlines, clean, case=False):
    text = A.stringify(inlines).strip()
    new = clean(text)
    simple = all(i["t"] in ("Str", "Space", "SoftBreak") for i in inlines)
    if case and simple:
        new = title_case(new)
    if new == text:
        return inlines
    if simple:
        return A.text_inlines(new)
    if text.endswith(new):
        return drop_prefix(inlines, len(text) - len(new))
    return inlines


def unwrap_divs(blocks):
    """Divs that only group content (HTML <div>, <section>, EPUB files)."""
    out = []
    for b in blocks:
        if b["t"] == "Div" and not set(A.classes(b)) & {"admonition", "bookapi", "book-refs", "missing-image",
                                                       "note", "warning", "tip", "important", "caution"} \
                and not any(c in markup.ADMONITIONS for c in A.classes(b)):
            out.extend(unwrap_divs(b["c"][1]))
        else:
            out.append(b)
    return out


# ---------------------------------------------------------------------------
# Listings: break points for long lines
# ---------------------------------------------------------------------------

UNIT = re.compile(r"\\[A-Za-z]+Tok\{|\\[A-Za-z]+\{\}|\\\^\{\}|\\[_{}%#&$ ~^]|\}|.", re.S)
ESC_VIS = {"\\textbackslash{}": "\\", "\\textasciitilde{}": "~", "\\textasciicircum{}": "^", "\\^{}": "^",
           "\\textquotesingle{}": "'", "\\textasciigrave{}": "`", "\\textquotedbl{}": '"',
           "\\textless{}": "<", "\\textgreater{}": ">", "\\textbar{}": "|"}


def inject_breaks(line):
    """Insert \\cbr{penalty} where a long code line may break: after a comma
    or an opening bracket, before a method call's dot, after a keyword
    argument's '=', and, as a last resort, inside long names."""
    units = UNIT.findall(line)
    vis = []
    for u in units:
        if u.endswith("Tok{") or u == "}":
            vis.append(None)
        elif u.endswith("{}"):
            vis.append(ESC_VIS.get(u, "?"))
        elif len(u) == 2 and u[0] == "\\":
            vis.append(u[1])
        else:
            vis.append(u)
    idx = [i for i, v in enumerate(vis) if v is not None]
    pen, since = {}, 0
    for k in range(len(idx) - 1):
        a, b = vis[idx[k]], vis[idx[k + 1]]
        c = vis[idx[k + 2]] if k + 2 < len(idx) else ""
        prev = vis[idx[k - 1]] if k else ""
        if a == " " or b == " ":
            since = 0
            continue
        p = None
        if a in ",;":
            p = 50
        elif a in "([{" and b not in ")]}":
            p = 200
        elif b == "." and (a.isalnum() or a in ")]_'\"") and c[:1].isalpha():
            p = 250
        elif a == "=" and b not in "=>" and prev not in "=!<>+-*/%&|^:":
            p = 150
        elif a == "/" and b != "/" and prev != "/":
            p = 400
        elif a == ":" and b not in ":/=":
            p = 300
        elif a in "|&+*" and b not in "|&=+*":
            p = 450
        elif a == "_" and b.isalnum():
            p = 1000
        elif a.islower() and b.isupper():
            p = 1500
        since += 1
        if p is None and since >= 18:
            p = 3000
        if p is not None:
            pen[idx[k]] = p
            since = 0
    if not pen:
        return line
    out = []
    for i, u in enumerate(units):
        out.append(u)
        if i in pen:
            out.append(f"\\cbr{{{pen[i]}}}")
    return "".join(out)


def postprocess_latex(text):
    text = re.sub(r"^\\def\\labelenumi\{\\arabic\{enumi\}\.\}\n", "", text, flags=re.M)
    out, in_hl = [], False
    for line in text.split("\n"):
        if line.startswith("\\begin{Highlighting}"):
            in_hl = True
        elif line.startswith("\\end{Highlighting}"):
            in_hl = False
        elif in_hl:
            line = inject_breaks(line)
        out.append(line)
    return "\n".join(out)


# ---------------------------------------------------------------------------
# The build
# ---------------------------------------------------------------------------

class Build:
    def __init__(self, cfg_path, only=None):
        self.cfg_path = Path(cfg_path).resolve()
        self.base = self.cfg_path.parent
        self.cfg = cfg = yaml.safe_load(self.cfg_path.read_text()) or {}
        self.root = (self.base / str(cfg.get("root", "."))).resolve()
        self.dir = (self.base / str(cfg.get("build_dir", "book-build"))).resolve()
        self.title = str(cfg.get("title") or self.root.name)
        self.output = (self.base / str(cfg.get("output") or slugify(self.title, 60) + ".pdf")).resolve()
        trim = str(cfg.get("trim", "7x10")).lower()
        if trim not in TRIMS:
            sys.exit(f"unknown trim {trim!r}; choose one of {', '.join(TRIMS)}")
        self.trim = TRIMS[trim]
        self.textwidth_in = self.trim[2]
        self.textwidth_pt = self.trim[2] * 72.27
        self.textheight_in = self.trim[3]
        self.image_max_height_in = round(0.46 * self.trim[3], 2)
        self.keep_lines = int(cfg.get("keep_lines", 14))
        self.default_lang = cfg.get("default_language", "python")
        self.fetch_images = bool(cfg.get("fetch_images", True))
        self.link_base = cfg.get("link_base")
        self.myst_project = bool(cfg.get("myst"))
        self.only = only
        self.warnings, self.unknown, self.macros, self.used_ids = [], {}, {}, set()
        self.cited = []
        self.split_front, self.split_appendix, self.split_back = [], [], []
        self.class_stack = []
        self.numbered = {}
        # a copy of assets/ with a changed design (references/design.md)
        self.assets = (self.base / str(cfg["assets"])).resolve() if cfg.get("assets") else ASSETS
        top, _ = git_info(self.root)
        self.repo_root = top or self.root
        dirs = [self.root / d for d in cfg.get("image_dirs", [])]
        self.image_dirs = [d for d in dirs + [self.root / "_static", self.root / "images", self.root / "img",
                                              self.root / "assets", self.root / "static", self.root / "figures"]
                           if d.is_dir()]
        out, _ = A.run_pandoc(["--list-highlight-languages"])
        self.highlight_languages = set(out.split())
        roots = [self.root / r for r in cfg.get("code_roots", [])]
        roots += [self.root, self.root / "src", self.root.parent, self.root.parent / "src",
                  self.repo_root, self.repo_root / "src"]
        seen, uniq = set(), []
        for r in roots:
            if r.is_dir() and r.resolve() not in seen:
                seen.add(r.resolve())
                uniq.append(r)
        self.autodoc = Autodoc(uniq, self.warn)
        self.images = P.ImageStore(self)
        self.api = [1, 23, 1]
        bib = cfg.get("bibliography")
        self.bibliography = [str((self.root / b).resolve()) for b in ([bib] if isinstance(bib, str) else bib or [])]

    # --- services for markup.py, notebook.py and postprocess.py ------------

    def asset(self, name):
        p = self.assets / name
        return p if p.exists() else ASSETS / name

    def warn(self, msg):
        self.warnings.append(msg)

    def directive_action(self, name):
        return (self.cfg.get("directives") or {}).get(name)

    def language_for(self, path):
        return S.code_language(path) or "plain"

    def rst_to_markdown(self, text, path):
        rst = markup.preprocess_rst(text, path, self)
        out, _ = A.run_pandoc(["-f", "rst", "-t", MD_WRITE, "--wrap=none"], text=rst)
        return out

    def html_to_markdown(self, html):
        out, _ = A.run_pandoc(["-f", "html", "-t", MD_WRITE, "--wrap=none"], text=html)
        return out

    def note_unknown_directive(self, name, src, note=""):
        self.unknown.setdefault(name, set()).add(Path(src).name + (f" ({note})" if note else ""))

    def autodoc_rst(self, name, target, opts, src, module=None, body=None):
        kind = name.split(":")[-1]
        if not kind.startswith("auto"):                 # .. function:: f(x) -- described by hand
            inner = markup.preprocess_rst("\n".join(info_fields(list(body or []))), src, self, module)
            lines = [".. container:: bookapi", "", "   ``" + target.replace("``", "` `") + "``", ""]
            lines += ["   " + l if l.strip() else "" for l in inner.split("\n")]
            return "\n".join(lines) + "\n"
        if self.class_stack and kind in ("automethod", "autoattribute", "autoproperty") and "." not in target:
            hit = self.autodoc.resolve(f"{self.class_stack[-1]}.{target}", module)
            if hit:
                target = f"{self.class_stack[-1]}.{target.split('(')[0]}"
        if kind == "autoobject":
            hit = self.autodoc.resolve(target, module)
            if hit and hit[2] is None:
                kind = "automodule"
            elif hit:
                kind = "autoclass" if type(hit[2]).__name__ == "ClassDef" else "autofunction"
        rst = self.autodoc.render(kind, target, opts, module)
        if not rst:
            self.note_unknown_directive(name, src, f"{target} not found in the source")
            return (f".. admonition:: API\n\n   The reference for ``{target}`` is generated from the "
                    f"source code, which was not found.\n")
        if body:
            rst += "\n" + "\n".join("   " + l if l.strip() else "" for l in body) + "\n"
        # versionadded and the like inside docstrings; methods nested in a class
        self.class_stack.append(target.split("(")[0].strip().lstrip("~!"))
        try:
            return markup.preprocess_rst(rst, src, self, module)
        finally:
            self.class_stack.pop()

    def vector_figure(self, nb_key, idx, k):
        d = self.cfg.get("vector_figures")
        if not d:
            return None
        p = self.base / d / nb_key / f"c{idx:03d}-{k}.pdf"
        return p if p.exists() else None

    def fontconfig_env(self):
        conf = self.dir / "fonts.conf"
        if not conf.exists():
            dirs = {str(Path(p).parent) for f in FONT_SETS[self.cfg.get("fonts", "charter")]
                    if (p := run(["kpsewhich", f]).stdout.strip())}
            conf.write_text('<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n<fontconfig>\n'
                            '  <include ignore_missing="yes">/etc/fonts/fonts.conf</include>\n'
                            + "".join(f"  <dir>{d}</dir>\n" for d in sorted(dirs))
                            + f"  <cachedir>{self.dir / 'fc-cache'}</cachedir>\n</fontconfig>\n")
        return dict(os.environ, FONTCONFIG_FILE=str(conf))

    def svg_to_pdf(self, svg, dest, scale=0.8, natural=False):
        """Convert SVG text to a PDF; return its printed size in inches."""
        face = {"charter": "XCharter", "libertinus": "Libertinus Serif", "stix": "STIX Two Text",
                "lm": "Latin Modern Roman"}[self.cfg.get("fonts", "charter")]
        svg = re.sub(r'font-family="(Times[^"]*|serif)"', f'font-family="{face}"', svg)
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".svg")
        tmp.write_text(svg)
        if shutil.which("rsvg-convert"):
            res = run(["rsvg-convert", "-f", "pdf", "-o", str(dest), str(tmp)], env=self.fontconfig_env())
            if res.returncode:
                raise RuntimeError(res.stderr.strip()[:200])
        else:
            try:
                import cairosvg
                cairosvg.svg2pdf(bytestring=svg.encode(), write_to=str(dest))
            except ImportError:
                raise RuntimeError("rsvg-convert (librsvg2-bin) is needed for SVG images")
        w, h = svg_size(svg)
        if natural:
            return w, h
        w, h = w * scale, h * scale
        if w > self.textwidth_in:
            h, w = h * self.textwidth_in / w, self.textwidth_in
        cap = min(3.6, self.image_max_height_in)
        if h > cap:
            w, h = w * cap / h, cap
        return w, h

    def rel(self, path):
        return Path(os.path.relpath(Path(path).resolve(), self.dir)).as_posix()

    def add_macro(self, name, definition):
        self.macros.setdefault(name, definition)

    # --- planning ------------------------------------------------------------

    def find(self, rel):
        p = (self.root / str(rel))
        if p.exists():
            return p.resolve()
        hit = S.resolve_doc(self.root, str(rel))
        if hit:
            return hit.resolve()
        sys.exit(f"book.yaml: {rel} not found under {self.root}")

    def plan(self):
        cfg = self.cfg
        self.front = [c for e in cfg.get("front") or [] for c in self.entry(e, "front")
                      if isinstance(c, Chapter)]
        main = []
        self.parts = []
        if cfg.get("parts"):
            for part in cfg["parts"]:
                chapters = [c for e in part.get("chapters") or [] for c in self.entry(e, "main")
                            if isinstance(c, Chapter)]
                self.parts.append({"title": part.get("title"), "chapters": chapters})
        cur = {"title": None, "chapters": []}
        for e in cfg.get("chapters") or []:
            for c in self.entry(e, "main"):
                if isinstance(c, PartBreak):
                    if cur["chapters"] or cur["title"]:
                        self.parts.append(cur)
                    cur = {"title": c.title, "chapters": []}
                elif c.kind.endswith("_split"):
                    c.kind = c.kind[:-len("_split")]
                    {"front": self.split_front, "appendix": self.split_appendix,
                     "back": self.split_back}[c.kind].append(c)
                else:
                    cur["chapters"].append(c)
        if cur["chapters"]:
            self.parts.append(cur)
        self.front += self.split_front
        self.appendix = [c for e in cfg.get("appendix") or [] for c in self.entry(e, "appendix")
                         if isinstance(c, Chapter)] + self.split_appendix
        self.back = [c for e in cfg.get("back") or [] for c in self.entry(e, "back")
                     if isinstance(c, Chapter)] + self.split_back
        self.number()
        for i, c in enumerate(self.front):
            c.slug = f"front{i + 1}"
        for c in [c for p in self.parts for c in p["chapters"]] + self.appendix:
            c.slug = f"ch{c.number:0>2}" if c.kind == "main" else f"app{c.number}"
        for i, c in enumerate(self.back):
            c.slug = f"back{i + 1}"
        for c in self.chapters():
            for k, u in enumerate(c.units):
                u.slug = c.slug if k == 0 else f"{c.slug}-s{k}"
                u.anchor = u.slug

    def number(self):
        n, letters = 0, iter("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
        for part in self.parts:
            for c in part["chapters"]:
                n += 1
                c.number = str(n)
        for c in self.appendix:
            c.number = next(letters)

    def chapters(self):
        return self.front + [c for p in self.parts for c in p["chapters"]] + self.appendix + self.back

    def selected(self, c):
        return not self.only or c.number in self.only or (c.kind in ("front", "back") and "front" in self.only)

    def entry(self, e, kind):
        if isinstance(e, str):
            e = {"path": e}
        if e.get("code") is not None:
            return [self.code_chapter(e, kind)]
        path = self.find(e["path"])
        fmt = S.fmt_of(path) or ("code" if S.code_language(path) else "text")
        if fmt == "code" or path.is_dir():
            return [self.code_chapter({"code": e["path"], "title": e.get("title")}, kind)]
        if e.get("split"):
            return self.split_file(path, fmt, e, kind)
        ch = Chapter(kind, e.get("title"))
        ch.units.append(Unit(self, path, "", fmt, "chapter", e.get("title")))
        for s in e.get("sections") or []:
            sp = self.find(s)
            ch.units.append(Unit(self, sp, "", S.fmt_of(sp) or "text", "section"))
        return [ch]

    def code_chapter(self, e, kind):
        d = self.find(e["code"]) if e["code"] not in (".", "") else self.root
        inc, exc = e.get("include") or ["*"], e.get("exclude") or []
        files = []
        if e.get("files"):                   # an explicit list, in the order given
            files = [(d / f).resolve() for f in e["files"]]
            missing = [str(f) for f in files if not f.is_file()]
            if missing:
                sys.exit(f"book.yaml: {', '.join(missing)} not found")
            title = e.get("title") or (self.relpath(d) if d != self.root else "Top-level files")
            ch = Chapter(kind, title)
            ch.units.append(Unit(self, d, "", "code", "chapter", title, files=files))
            return ch
        if d.is_file():
            files = [d]
        else:
            it = d.rglob("*") if e.get("recursive") else d.iterdir()
            for p in it:
                rel = p.relative_to(d).as_posix()
                if not p.is_file() or p.name.startswith(".") or p.name in S.SKIP_FILES:
                    continue
                if any(part in S.SKIP_DIRS for part in p.relative_to(d).parts[:-1]):
                    continue
                if not S.code_language(p) or not any(fnmatch.fnmatch(rel, g) for g in inc) \
                        or any(fnmatch.fnmatch(rel, g) for g in exc):
                    continue
                if p.stat().st_size > 400_000 or not p.read_text(errors="replace").strip():
                    continue
                files.append(p)
        lead = ("__init__", "index", "main", "mod", "lib", "app")
        files.sort(key=lambda p: (len(p.relative_to(d).parts) if d.is_dir() else 0,
                                  0 if p.stem in lead else 1, S.natural_key(p.name)))
        title = e.get("title") or (self.relpath(d) if d != self.root else "Top-level files")
        ch = Chapter(kind, title)
        ch.units.append(Unit(self, d, "", "code", "chapter", title, files=files))
        return ch

    def relpath(self, p):
        try:
            return Path(p).resolve().relative_to(self.root).as_posix()
        except ValueError:
            return Path(p).name

    def split_file(self, path, fmt, e, kind):
        """One long document -> chapters at its top headings ("Part ..."
        headings start parts, "Appendix ..." ones the appendix)."""
        probe = Unit(self, path, slugify(path.stem), fmt)
        doc, meta_title = self.read_doc(probe)
        blocks = unwrap_divs(doc["blocks"])
        heads = [(i, b["c"][0], A.stringify(b["c"][2])) for i, b in enumerate(blocks) if b["t"] == "Header"]
        if not heads:
            ch = Chapter(kind, e.get("title"))
            ch.units.append(Unit(self, path, "", fmt, "chapter", e.get("title") or meta_title, blocks=blocks))
            return [ch]
        levels = sorted({h[1] for h in heads})
        top = [h for h in heads if h[1] == levels[0]]
        lvl = levels[0]
        if len(top) == 1 and len(levels) > 1 and top[0][0] <= 3:
            self.cfg.setdefault("title", top[0][2])
            blocks = blocks[:top[0][0]] + blocks[top[0][0] + 1:]
            heads = [(i - (i > top[0][0]), lv, t) for i, lv, t in heads if i != top[0][0]]
            lvl = levels[1]
        part_level = None
        if fmt == "latex" and "\\part" in path.read_text(errors="replace"):
            part_level, lvl = lvl, lvl + 1
        elif any(PART_HEAD.match(t) for i, lv, t in heads if lv == lvl) and any(lv == lvl + 1 for _, lv, _ in heads):
            part_level, lvl = lvl, lvl + 1
        if part_level is not None:
            # "# Book Title" above "# Part I ..." headings: the book's title
            first = next(((i, t) for i, lv, t in heads if lv == part_level), None)
            if first and first[0] <= 3 and not PART_HEAD.match(first[1]) and not APPENDIX_HEAD.match(first[1]):
                self.cfg.setdefault("title", first[1])
                blocks = blocks[:first[0]] + blocks[first[0] + 1:]
        appendix_titles = set()
        if fmt == "latex":
            src = path.read_text(errors="replace")
            k = src.find("\\appendix")
            if k >= 0:
                appendix_titles = {clean_title(t) for t in re.findall(r"\\chapter\*?\{([^}]*)\}", src[k:])}
        out, cur, cur_title, cur_id, mode, lead = [], None, None, "", kind, []
        in_appendix = False

        def flush():
            if cur is None:
                return
            k2 = mode
            t = A.stringify(cur_title)
            if BACK_HEAD.match(t):
                k2 = "back_split" if kind == "main" else "back"
            elif FRONT_HEAD.match(t) and kind == "main" and not any(
                    isinstance(c, Chapter) and c.kind == "main" for c in out):
                k2 = "front_split"
            elif in_appendix or APPENDIX_HEAD.match(t) or t in appendix_titles:
                k2 = "appendix_split" if kind == "main" else kind
            ch = Chapter(k2)
            title = cur_title
            m = APPENDIX_HEAD.match(t)
            if m and A.stringify(title)[m.end():].strip():
                title = A.text_inlines(A.stringify(title)[m.end():].strip())
            u = Unit(self, path, "", fmt, "chapter", title, blocks=cur)
            u.head_id = cur_id
            ch.units.append(u)
            out.append(ch)

        pending = None                  # a part's introduction, before its first chapter
        for b in blocks:
            if b["t"] == "Header" and part_level is not None and b["c"][0] == part_level:
                flush()
                cur, cur_title = None, None
                t = A.stringify(b["c"][2])
                am = APPENDIX_HEAD.match(t)
                if am:
                    in_appendix = True
                    if t[am.end():].strip():         # "Appendix A: Glossary" is itself a chapter
                        cur, cur_title, cur_id = [], A.text_inlines(t[am.end():].strip()), b["c"][1][0]
                    pending = None
                    continue
                if pending:                          # a part with text but no chapters
                    ch = Chapter(kind, out[-1].title)
                    ch.units.append(Unit(self, path, "", fmt, "chapter", out[-1].title, blocks=pending))
                    out.append(ch)
                pm = PART_HEAD.match(t)
                out.append(PartBreak(t[pm.end():].strip() if pm and t[pm.end():].strip() else t))
                pending = []
                continue
            if b["t"] == "Header" and b["c"][0] == lvl:
                flush()
                cur, cur_title, cur_id = list(pending or []), b["c"][2], b["c"][1][0]
                pending = None
                continue
            if cur is not None:
                cur.append(b)
            elif pending is not None:
                pending.append(b)
            else:
                lead.append(b)
        flush()
        words = len(A.stringify(lead).split())
        if words >= 60:
            ch = Chapter("front_split" if kind == "main" else kind, e.get("lead_title", "Preface"))
            ch.units.append(Unit(self, path, "", fmt, "chapter", e.get("lead_title", "Preface"), blocks=lead))
            out.insert(0, ch)
        elif words:
            self.warn(f"{path.name}: {words} words before the first chapter heading were left out "
                      f"(title-page material?): {A.stringify(lead)[:80]!r}")
        return out

    # --- reading -------------------------------------------------------------

    def read_doc(self, u):
        """(pandoc document, title from metadata) for a unit's source."""
        path, fmt = u.path, u.fmt
        meta_title = None
        self.current_module = None
        if fmt == "code":
            return {"meta": {}, "blocks": self.code_blocks(u)}, u.title
        if fmt == "ipynb":
            md, lang, _meta = notebook.notebook_markdown(path, self)
            doc, err = A.read(md, NB_FORMAT)
        elif fmt == "md":
            md, meta = markup.preprocess_markdown(path.read_text(errors="replace"), path, self)
            meta_title = meta.get("title") if isinstance(meta.get("title"), str) else None
            doc, err = A.read(md, MD_FORMAT)
        elif fmt in ("qmd", "rmd"):
            text = self.frozen(path) or path.read_text(errors="replace")
            md, meta = markup.preprocess_markdown(text, path, self, myst=False)
            meta_title = meta.get("title") if isinstance(meta.get("title"), str) else None
            doc, err = A.read(md, QMD_FORMAT)
        elif fmt == "rst":
            rst = markup.preprocess_rst(path.read_text(errors="replace"), path, self)
            doc, err = A.read(rst, "rst")
        elif fmt == "html":
            doc, err = A.read(clean_html(path.read_text(errors="replace")), "html")
            doc["blocks"] = unwrap_divs(doc["blocks"])
        elif fmt in ("docx", "odt", "epub"):
            media = self.dir / "media" / slugify(path.stem)
            doc, err = A.read(path, fmt, extra=["--extract-media", str(media)], is_path=True)
            doc["blocks"] = unwrap_divs(doc["blocks"])
            meta_title = A.meta_text(doc.get("meta", {}), "title")
        elif fmt == "latex":
            text = self.latex_bibliography(path, path.read_text(errors="replace"))
            doc, err = A.read(text, "latex", cwd=str(path.parent))
            meta_title = A.meta_text(doc.get("meta", {}), "title")
        elif fmt == "asciidoc":
            if not shutil.which("asciidoctor"):
                sys.exit(f"{path.name}: AsciiDoc needs asciidoctor (gem install asciidoctor)")
            xml = run(["asciidoctor", "-b", "docbook5", "-o", "-", str(path)]).stdout
            doc, err = A.read(xml, "docbook")
        elif fmt == "text":
            doc, err = {"meta": {}, "blocks": text_blocks(path.read_text(errors="replace"))}, ""
        elif fmt in PANDOC_READERS:
            doc, err = A.read(path, fmt, is_path=True)
        else:
            sys.exit(f"{path.name}: no reader for this format")
        if err:
            self.warn(f"pandoc ({path.name}): {err[:300]}")
        return doc, meta_title

    def latex_bibliography(self, path, text):
        """\\bibliography{refs} -> citeproc with refs.bib; a hand-written
        thebibliography -> numbered references [1] that need no BibTeX."""
        for m in re.finditer(r"\\(?:bibliography|addbibresource)\{([^}]+)\}", text):
            for name in m.group(1).split(","):
                bib = (path.parent / name.strip())
                bib = bib if bib.suffix == ".bib" else bib.with_name(bib.name + ".bib")
                if bib.exists() and str(bib) not in self.bibliography:
                    self.bibliography.append(str(bib.resolve()))
        m = re.search(r"\\begin\{thebibliography\}\{[^}]*\}(.*?)\\end\{thebibliography\}", text, re.S)
        if not m:
            return text
        parts = re.split(r"\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}", m.group(1))
        keys, entries = [k.strip() for k in parts[1::2]], [t.strip() for t in parts[2::2]]
        number = {k: i + 1 for i, k in enumerate(keys)}
        head = "\\chapter*{References}" if "\\chapter" in text else "\\section*{References}"
        refs = head + "\n\\begin{enumerate}\n" + "\n".join(f"\\item {e}" for e in entries) + "\n\\end{enumerate}\n"
        text = text[:m.start()] + refs + text[m.end():]

        def cite(c):
            nums = ", ".join(str(number.get(k.strip(), "?")) for k in c.group(2).split(","))
            return "[" + nums + (", " + c.group(1) if c.group(1) else "") + "]"
        return re.sub(r"\\cite[tp]?\*?(?:\[([^\]]*)\])?\{([^}]+)\}", cite, text)

    def frozen(self, path):
        """Quarto's frozen render (code results included), if there is one."""
        try:
            rel = path.resolve().relative_to(self.root).with_suffix("")
        except ValueError:
            return None
        for fmt in ("html", "pdf", "latex", "markdown", "md"):
            f = self.root / "_freeze" / rel / "execute-results" / f"{fmt}.json"
            if f.exists():
                try:
                    md = json.loads(f.read_text())["result"]["markdown"]
                except (KeyError, ValueError):
                    continue
                # figure paths in the frozen output are relative to the project
                return re.sub(r"\]\((?!https?:|/)([^)\s]+)\)",
                              lambda m: "](" + str((self.root / m.group(1)).resolve()) + ")"
                              if (self.root / m.group(1)).exists() else m.group(0), md)
        return None

    def code_blocks(self, u):
        blocks = []
        for f in u.files:
            rel = self.relpath(f)
            lang = P.LANG_ALIASES.get(S.code_language(f), S.code_language(f)) or "plain"
            if lang not in self.highlight_languages:
                lang = "plain"
            text = f.read_text(errors="replace").replace("\r\n", "\n").rstrip("\n").expandtabs(4)
            n = text.count("\n") + 1
            info = f"{LANG_LABEL.get(lang, lang.title())} · {n:,} line{'s' if n != 1 else ''}"
            blocks.append(A.Header(1, A.text_inlines(rel), ident=slugify(rel, 60).lower()))
            blocks.append(A.RawBlock("latex", f"\\sourceinfo{{{tex(info)}}}"))
            blocks.append(A.CodeBlock(text, [lang, "numberLines"]))
        if not blocks:
            blocks.append(A.Para(A.text_inlines("(No source files.)")))
        return blocks

    def load(self, u):
        if u.preset is not None:
            doc, meta_title = {"meta": {}, "blocks": u.preset}, None
        else:
            doc, meta_title = self.read_doc(u)
        blocks = doc["blocks"]
        blocks = P.convert_roles(blocks)
        blocks = P.convert_divs(blocks, u)
        blocks = P.convert_raw_html(blocks, u)
        blocks = drop_badges(blocks)
        blocks = P.drop_caption_echoes(blocks)
        P.smart_quotes(blocks)
        if u.title is not None:
            title = u.title if isinstance(u.title, list) else A.text_inlines(str(u.title))
            if u.preset is None and u.fmt != "code":
                _t, blocks = P.take_title({"meta": {}, "blocks": blocks})
        else:
            before = blocks
            title, blocks = P.take_title({"meta": doc.get("meta", {}), "blocks": blocks}, meta_title)
            gone = [b for b in before if b["t"] == "Header" and not any(b is x for x in blocks)]
            if gone and gone[0]["c"][1][0]:
                u.head_id = gone[0]["c"][1][0]          # links to the title go to the chapter
        if not title:
            title = A.text_inlines(S.title_from_name(u.path.stem if u.path.is_file() else u.path.name))
        strip = self.cfg.get("strip_numbers", True)
        title = fix_title(title, lambda t: clean_title(t, strip), self.cfg.get("title_case", False))
        blocks = P.normalize_headings(blocks, 1 if u.role == "chapter" else 2)
        if u.role == "section":
            blocks = [A.Header(1, title, ident="book-unit")] + blocks
        blocks = P.drop_sections(blocks, self.cfg.get("drop_sections") or [])
        blocks = P.drop_empty_items(blocks)
        blocks = P.drop_empty_sections(blocks)
        blocks = P.mark_references(blocks)
        blocks = P.process_images(blocks, u)
        default = self.default_lang if u.fmt == "rst" else None
        if self.default_lang == "plain":
            default = None
        blocks = P.normalize_code(blocks, self, default)
        blocks = P.prefix_ids(blocks, u, self.used_ids)
        if u.role == "section":
            u.anchor = u.ids.get("book-unit", u.slug)
        if getattr(u, "head_id", ""):
            u.ids.setdefault(u.head_id, u.anchor)
        blocks = P.extract_macros(blocks, self)
        blocks = [b for b in blocks if not (b["t"] == "RawBlock" and not b["c"][1].strip())]
        u.doc = {"pandoc-api-version": self.api, "meta": {}, "blocks": blocks}
        u.title_inlines = title
        if self.bibliography:
            for n in A.iter_nodes(blocks):
                if n.get("t") == "Cite":
                    for c in n["c"][0]:
                        if c["citationId"] not in self.cited:
                            self.cited.append(c["citationId"])

    # --- index ---------------------------------------------------------------

    def index_terms(self, chapters):
        """Write index-terms.lua and index-see.tex; return (lua path, has index, has ranges)."""
        spec = self.cfg.get("index", "auto")
        n_api = sum(1 for c in chapters for u in c.units for n in A.iter_nodes(u.doc["blocks"])
                    if n.get("t") == "Div" and "bookapi" in A.classes(n) and A.attrs(n).get("index"))
        api = n_api >= 15 or (spec not in ("auto", None) and n_api > 0)
        if spec in (None, False, "none", "off"):
            return None, False, False
        import suggest_index
        words = sum(len(A.stringify(u.doc["blocks"]).split()) for c in chapters for u in c.units)
        if spec == "auto" and words < 12000 and not api:
            self.warn(f"no index: the book is short ({words:,} words); set index: auto-always to force one")
            return None, False, False
        if spec in ("auto", "auto-always"):
            terms, see = suggest_index.auto_terms(chapters), {}
        else:
            data = yaml.safe_load((self.base / spec).read_text()) or {}
            terms, see = suggest_index.from_yaml(data, chapters), data.get("see") or {}
        lua = self.dir / "index-terms.lua"
        lua.write_text(suggest_index.to_lua(terms))
        (self.dir / "index-see.tex").write_text(
            "".join(f"\\index{{{suggest_index.sort_key(k)}@{tex(k)}|see{{{tex(v)}}}}}\n" for k, v in see.items()))
        ranges = any(t.get("home") for t in terms)
        return lua, bool(terms or api or see), ranges

    # --- writing -------------------------------------------------------------

    def inline_tex(self, inlines):
        out, _ = A.write({"pandoc-api-version": self.api, "meta": {}, "blocks": [A.Plain(inlines)]},
                         "latex", ["--wrap=none"])
        return out.strip()

    def citeproc(self, doc):
        args = ["-f", "json", "-t", "json", "--citeproc", "-M", "suppress-bibliography=true",
                "-M", "link-citations=true"] + [f"--bibliography={b}" for b in self.bibliography]
        if self.cfg.get("csl"):
            args.append(f"--csl={(self.root / self.cfg['csl']).resolve()}")
        out, err = A.run_pandoc(args, text=json.dumps(doc))
        if err:
            self.warn(f"citeproc: {err[:300]}")
        return json.loads(out)

    def write_chapter(self, ch, index_lua):
        blocks = [b for u in ch.units for b in u.doc["blocks"]]
        doc = {"pandoc-api-version": self.api, "meta": {}, "blocks": blocks}
        if self.bibliography and self.cited:
            doc = self.citeproc(doc)
        args = ["--wrap=preserve", f"--lua-filter={self.asset('book.lua')}",
                f"--highlight-style={self.asset('book.theme')}", "-M", f"chapter_id={ch.slug}",
                "-M", f"keep_lines={self.keep_lines}", "-M", f"textwidth_pt={self.textwidth_pt:.1f}"]
        if index_lua:
            args += ["-M", f"index_terms_file={index_lua}"]
        body, err = A.write(doc, "latex", args)
        if err:
            self.warn(f"pandoc ({ch.slug}): {err[:300]}")
        body = postprocess_latex(body)
        secs = [A.stringify(b["c"][2]) for b in blocks if b["t"] == "Header" and b["c"][0] == 1]
        versions = sum(1 for t in secs if VERSIONISH.match(t))
        if len(secs) > 24 or (len(secs) > 8 and versions >= 0.6 * len(secs)):
            body = "\\booktocsectionsoff\n" + body + "\n\\booktocsectionson\n"
        title = self.inline_tex(ch.title_inlines)
        plain = A.stringify(ch.title_inlines).strip()
        if title != tex(plain):
            title = f"\\texorpdfstring{{{title}}}{{{tex(plain)}}}"
        head_title = tex(running_head(plain))
        if ch.kind in ("front", "back"):
            head = (f"\\chapter*{{{title}}}\\label{{{ch.slug}}}\\hypertarget{{{ch.slug}}}{{}}\n"
                    f"\\addcontentsline{{toc}}{{chapter}}{{{title}}}\\markboth{{{head_title}}}{{{head_title}}}\n")
        else:
            short = f"[{title}][{head_title}]" if head_title != tex(plain) else ""
            head = f"\\chapter{short}{{{title}}}\\label{{{ch.slug}}}\\hypertarget{{{ch.slug}}}{{}}\n"
        (self.dir / "chapters").mkdir(parents=True, exist_ok=True)
        (self.dir / "chapters" / f"{ch.slug}.tex").write_text(
            f"\\typeout{{BOOKFILE {ch.slug}}}\n" + head + "\n" + body + "\n")

    def bibliography_chapter(self):
        keys = ", ".join("@" + k for k in self.cited)
        md = f"---\nnocite: |\n  {keys}\n---\n"
        args = ["-f", "markdown", "-t", "json", "--citeproc"] + [f"--bibliography={b}" for b in self.bibliography]
        if self.cfg.get("csl"):
            args.append(f"--csl={(self.root / self.cfg['csl']).resolve()}")
        out, err = A.run_pandoc(args, text=md)
        doc = json.loads(out)
        ch = Chapter("back", self.cfg.get("bibliography_title", "References"))
        ch.slug = "references"
        u = Unit(self, self.root, "references", "md", "chapter", ch.title, blocks=doc["blocks"])
        u.doc = {"pandoc-api-version": self.api, "meta": {}, "blocks": doc["blocks"]}
        u.title_inlines = A.text_inlines(ch.title)
        ch.units, ch.title_inlines = [u], u.title_inlines
        return ch

    def highlighting(self):
        tpl = self.dir / "macros.tpl"
        tpl.write_text("$highlighting-macros$\n")
        out, _ = A.run_pandoc(["-f", "markdown", "-t", "latex", "--standalone", f"--template={tpl}",
                               f"--highlight-style={self.asset('book.theme')}"], text="```python\nx = 1\n```\n")
        keep = [l for l in out.splitlines()
                if not re.match(r"\\(usepackage|DefineVerbatimEnvironment|newenvironment)\b", l)
                and not l.startswith("%")]
        (self.dir / "highlighting.tex").write_text("\n".join(keep) + "\n")

    def revision(self):
        r = run(["git", "-C", str(self.root), "log", "-1", "--format=%h", "--", "."]).stdout.strip()
        if not r:
            return ""
        dirty = run(["git", "-C", str(self.root), "status", "--porcelain", "--", "."]).stdout.strip()
        return r + ("-dirty" if dirty else "")

    def source_kind(self, chapters):
        counts = {}
        for c in chapters:
            for u in c.units:
                counts[u.fmt] = counts.get(u.fmt, 0) + 1
        if not counts:
            return "its sources"
        fmt = max(counts, key=counts.get)
        return {"ipynb": "Jupyter notebooks", "md": "Markdown sources", "rst": "reStructuredText sources",
                "qmd": "Quarto sources", "rmd": "R Markdown sources", "html": "HTML pages",
                "docx": "Word document", "odt": "OpenDocument text", "epub": "EPUB edition",
                "latex": "LaTeX sources", "code": "source code", "text": "text files"}.get(fmt, "sources")

    def bookconfig(self, chapters, has_ranges):
        cfg = self.cfg
        t = self.trim
        title = str(cfg.get("title") or self.title)
        line_a = str(cfg.get("title_line1") or title)
        line_b = str(cfg.get("title_line2") or "")
        sub = str(cfg.get("subtitle") or "")
        author = cfg.get("author") or ""
        if isinstance(author, list):
            author = ", ".join(map(str, author))
        longest = max([len(w) for w in line_a.split()] + [1])
        box = 0.8 * inches(t[0]) * 72                    # the cover's title block, in pt
        cover = min(54.0, box / (0.56 * longest), box * 2.2 / (0.5 * max(len(line_a), 1)))
        cover = max(30.0, round(cover, 1))
        page = max(26.0, round(min(44.0, cover * 0.84), 1))
        year = cfg.get("year") or datetime.date.today().year
        copyright = cfg.get("copyright") or (f"Copyright © {year} {author}." if author else "")
        if copyright and not cfg.get("copyright"):
            self.warn(f"copyright line assumed ({copyright!r}); set copyright: in book.yaml if it is wrong")
        lic_name = cfg.get("license") or ""
        lic_file = cfg.get("license_file")
        lic_text = ""
        if lic_file and (self.base / lic_file).is_file():
            raw = (self.base / lic_file).read_text(errors="replace").strip()
            raw = re.sub(r"^(The )?(MIT|ISC|BSD[\w -]*) License\s*\n+", "", raw, flags=re.I)
            raw = re.sub(r"^\s*Copyright[^\n]*\n+", "", raw, flags=re.I | re.M)
            if len(raw) < 2600:
                lic_text = "\n\n".join(tex(" ".join(p.split())) for p in re.split(r"\n\s*\n", raw) if p.strip())
        block = [f"{{\\headingfont {tex(title)}}}" + (f"\\\\\nby {tex(author)}" if author else ""), ""]
        if copyright:
            block += [tex(copyright), ""]
        if lic_name:
            block += [f"Released under the {tex(lic_name)}" + (":" if lic_text else "."), ""]
        if lic_text:
            block += ["{\\color{inkgray}" + lic_text + "\\par}", ""]
        for label, key in (("Source", "source_url"), ("Online edition", "online_url")):
            if cfg.get(key):
                block.append(f"{label}: \\url{{{cfg[key]}}}\\\\")
        if cfg.get("copyright_extra"):
            block += ["", tex(cfg["copyright_extra"])]
        rev = self.revision()
        typeset = f"This edition was typeset on \\today\\ from the {self.source_kind(chapters)}."
        if rev:
            typeset += f"\\\\\nSource revision \\texttt{{{tex(rev)}}}"
        fonts = cfg.get("fonts", "charter")
        names = list(FONT_NAMES.get(fonts, FONT_NAMES["charter"]))
        has_code = any(n.get("t") in ("CodeBlock", "Code") for c in chapters for u in c.units
                       for n in A.iter_nodes(u.doc["blocks"]))
        if not has_code:
            names = names[:2]
        faces = names[0] if len(set(names)) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        colophon = cfg.get("colophon") or (
            f"This book was typeset with LuaLaTeX in {faces},\\\\"
            f"from the {self.source_kind(chapters)}, converted with pandoc.")
        cover_img = cfg.get("cover_image")
        if cover_img:
            src = (self.root / cover_img) if (self.root / cover_img).exists() else (self.base / cover_img)
            placed = self.images.place(src) if src.exists() else None
            cover_img = self.rel(placed[0]) if placed else ""
            if not placed:
                self.warn(f"cover image {cfg['cover_image']} not found")
        defs = {
            "bookStockWidth": t[0], "bookStockHeight": t[1], "bookTextWidth": f"{t[2]}in",
            "bookTextHeight": f"{t[3]}in", "bookSpineMargin": t[4], "bookTopMargin": t[5],
            "bookCodeSize": str(cfg.get("code_size", t[6])),
            "bookCodeLeading": str(round(float(cfg.get("code_size", t[6])) * t[7] / t[6], 1)),
            "bookFontSet": fonts, "bookAccent": str(cfg.get("accent", "9A1F26")).lstrip("#"),
            "bookCoverAccent": str(cfg.get("cover_accent") or "").lstrip("#"),
            "bookLanguage": str(cfg.get("language", "english")),
            "bookTitleLineA": tex(line_a), "bookTitleLineB": tex(line_b), "bookSubtitle": tex_lines(sub),
            "bookAuthor": tex(author), "bookPublisher": tex(cfg.get("publisher") or ""),
            "bookTagline": tex_lines(cfg.get("tagline") or ""), "bookImprint": tex(cfg.get("imprint") or ""),
            "bookCoverImage": cover_img or "", "bookCoverTitleSize": str(cover),
            "bookCoverTitleLeading": str(round(cover * 1.08, 1)), "bookCoverSecondSize": str(round(cover * 0.62, 1)),
            "bookCoverSecondLeading": str(round(cover * 0.72, 1)), "bookTitlePageSize": str(page),
            "bookTitlePageLeading": str(round(page * 1.09, 1)),
            "bookCopyrightBlock": "\n".join(block), "bookTypesetLine": typeset,
            "bookDedication": tex_lines(cfg.get("dedication") or ""),
            "bookEpigraph": tex_lines(cfg.get("epigraph") or ""), "bookColophon": colophon,
        }
        if not has_ranges:
            defs["bookindexnote"] = ""
        lines = ["% Written by book.py from book.yaml."]
        for k, v in defs.items():
            lines.append(f"\\newcommand*{{\\{k}}}{{{v}}}" if "\n" not in v else f"\\newcommand{{\\{k}}}{{{v}}}")
        # glyphs the book's fonts lack: DejaVu, any fonts book.yaml names (e.g. a
        # CJK face), and colour emoji when the system has them
        extra = [str(f) for f in cfg.get("fallback_fonts") or []]
        emoji = ["NotoColorEmoji"] if shutil.which("fc-list") and \
            run(["fc-list", "Noto Color Emoji"]).stdout.strip() else []
        text_fb = ["DejaVuSans", "DejaVuSansMono"] + extra + emoji
        mono_fb = ["DejaVuSansMono", "DejaVuSans"] + extra + emoji
        lines.append("\\newcommand*{\\bookFallbackText}{" + ", ".join(f'"{f}:mode=harf;"' for f in text_fb) + "}")
        lines.append("\\newcommand*{\\bookFallbackMono}{" + ", ".join(f'"{f}:mode=harf;"' for f in mono_fb) + "}")
        (self.dir / "bookconfig.tex").write_text("\n".join(lines) + "\n")

    def master(self, has_index):
        cfg = self.cfg
        n_main = sum(len(p["chapters"]) for p in self.parts)
        named_parts = [p for p in self.parts if p["title"]]
        brief = (bool(named_parts) and n_main > 8) or n_main > 14
        L = [r"\pdfvariable minorversion=7",
             rf"\documentclass[{self.trim[8]},twoside,{self.opening()},final]{{memoir}}",
             r"\input{bookconfig}", r"\usepackage{book}", r"\input{highlighting}", r"\input{macros}",
             r"\hypersetup{pdftitle={" + tex(cfg.get("title") or self.title) + "}, pdfauthor={" +
             tex(cfg.get("author") or "") + "}, pdfsubject={" + tex(cfg.get("subtitle") or "") + "}}",
             r"\begin{document}", r"\pdfbookmark[0]{Cover}{cover}", r"\input{cover}", r"\frontmatter",
             r"\input{titlepages}"]
        if brief:
            L += [r"\cleardoublepage\pdfbookmark[0]{Brief Contents}{briefcontents}",
                  r"\begingroup\setcounter{tocdepth}{0}\renewcommand*{\contentsname}{Brief Contents}",
                  r"\tableofcontents*\endgroup",
                  r"\cleardoublepage\pdfbookmark[0]{Contents in Detail}{contents}",
                  r"\begingroup\setcounter{tocdepth}{1}\renewcommand*{\contentsname}{Contents in Detail}",
                  r"\tableofcontents*\endgroup"]
        else:
            L += [r"\cleardoublepage\pdfbookmark[0]{Contents}{contents}",
                  r"\begingroup\setcounter{tocdepth}{1}\tableofcontents*\endgroup"]
        L += [rf"\input{{chapters/{c.slug}}}" for c in self.front if self.selected(c)]
        L.append(r"\mainmatter")
        for part in self.parts:
            chs = [c for c in part["chapters"] if self.selected(c)]
            if not chs:
                continue
            if part["title"]:
                L.append(rf"\bookpart{{{tex(part['title'])}}}")
            L += [rf"\input{{chapters/{c.slug}}}" for c in chs]
        apps = [c for c in self.appendix if self.selected(c)]
        if apps:
            L.append(r"\appendix")
            if named_parts:
                L.append(rf"\bookappendixpart{{{tex(cfg.get('appendix_title', 'Appendices'))}}}")
            L += [rf"\input{{chapters/{c.slug}}}" for c in apps]
        L.append(r"\backmatter")
        L += [rf"\input{{chapters/{c.slug}}}" for c in self.back if self.selected(c)]
        if has_index:
            L += [r"\typeout{BOOKFILE index}", r"\input{index-see}", r"\begingroup\small\printindex\endgroup"]
        L += [r"\input{colophon}", r"\end{document}"]
        (self.dir / "book.tex").write_text("\n".join(L) + "\n")
        (self.dir / "macros.tex").write_text(
            "% \\newcommand & co. found in the sources' maths\n" +
            "".join(macro_line(d) + "\n" for d in self.macros.values()))

    def opening(self):
        """openright, as books do; openany for short ones without parts
        (a 20-page report would otherwise be a third blank pages)."""
        mode = str(self.cfg.get("chapters_open", "auto")).lower()
        if mode in ("right", "openright"):
            return "openright"
        if mode in ("any", "openany"):
            return "openany"
        parts = any(p["title"] for p in self.parts)
        return "openright" if parts or getattr(self, "words", 0) >= 8000 else "openany"

    def compile(self):
        dirs = ([str(self.assets)] if self.assets != ASSETS else []) + [str(ASSETS)]
        env = dict(os.environ, TEXINPUTS=".:" + ":".join(d + "//" for d in dirs) + ":", max_print_line="10000")
        shutil.copy2(self.asset("book.ist"), self.dir / "book.ist")
        (self.dir / "latexmkrc").write_text("$makeindex = 'makeindex -s book.ist %O -o %D %S';\n")
        res = run(["latexmk", "-r", "latexmkrc", "-lualatex", "-interaction=nonstopmode", "-halt-on-error",
                   "-file-line-error", "book.tex"], cwd=self.dir, env=env)
        log = (self.dir / "book.log").read_text(errors="replace") if (self.dir / "book.log").exists() else ""
        if res.returncode:
            err = [l for l in log.splitlines() if l.startswith("!") or ".tex:" in l and "error" in l.lower()]
            tail = "\n".join(log.splitlines()[-40:])
            sys.exit("LuaLaTeX failed:\n" + "\n".join(err[:10]) + "\n...\n" + tail)
        return analyze_log(log)

    def build(self, no_pdf=False):
        self.dir.mkdir(parents=True, exist_ok=True)
        for sub in ("chapters",):
            shutil.rmtree(self.dir / sub, ignore_errors=True)
        self.plan()
        chapters = [c for c in self.chapters() if self.selected(c)]
        print(f"{len(chapters)} chapters from {self.root}")
        for c in chapters:
            for u in c.units:
                self.load(u)
            c.title_inlines = c.units[0].title_inlines
            label = c.number or c.kind
            print(f"  [{label:>5}] {A.stringify(c.title_inlines)[:70]}")
        empty = [c for c in chapters if not any(u.doc["blocks"] for u in c.units)]
        for c in empty:
            self.warn(f"chapter {A.stringify(c.title_inlines)!r} ({c.units[0].path.name}) is empty; left out")
            chapters.remove(c)
            for group in [self.front, self.appendix, self.back] + [p["chapters"] for p in self.parts]:
                if c in group:
                    group.remove(c)
        if empty and not self.only:
            self.number()
        self.xref_labels = {c.slug: (f"Chapter {c.number}" if c.kind == "main" else
                                     f"Appendix {c.number}" if c.kind == "appendix" else
                                     A.stringify(c.title_inlines)) for c in chapters}
        P.resolve_links([u for c in chapters for u in c.units], self)
        self.words = sum(len(A.stringify(u.doc["blocks"]).split()) for c in chapters for u in c.units)
        if self.bibliography and self.cited:
            ref = self.bibliography_chapter()
            self.back.append(ref)
            chapters.append(ref)
        self.highlighting()
        lua, has_index, ranges = self.index_terms(chapters)
        for c in chapters:
            self.write_chapter(c, lua)
        self.bookconfig(chapters, ranges)
        self.master(has_index)
        report = {"chapters": len(chapters), "warnings": self.warnings,
                  "unknown_directives": {k: sorted(v) for k, v in self.unknown.items()}}
        if not no_pdf:
            print("typesetting (LuaLaTeX; a long book takes several minutes) ...")
            report.update(self.compile())
            out = self.output if not self.only else self.output.with_name(self.output.stem + "-preview.pdf")
            shutil.copy2(self.dir / "book.pdf", out)
            report["pdf"] = str(out)
            report["pages"] = report.get("pages")
        (self.dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print_report(report, self)
        return 0


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def inches(length):
    m = re.fullmatch(r"([\d.]+)(in|mm|cm|pt)", length)
    return float(m.group(1)) / {"in": 1, "mm": 25.4, "cm": 2.54, "pt": 72.27}[m.group(2)]


def tex_lines(s):
    return "\\\\".join(tex(l.strip()) for l in str(s).strip().split("\n")) if s else ""


def macro_line(definition):
    """\\newcommand in the preamble that does not clash with LaTeX's own."""
    return re.sub(r"^\\(newcommand|renewcommand)\*?", r"\\providecommand", definition) \
        if not definition.startswith("\\DeclareMathOperator") else definition


def running_head(title, limit=46):
    if len(title) <= limit:
        return title
    if ":" in title and len(title.split(":")[0]) <= limit:
        return title.split(":")[0]
    out = ""
    for w in title.split():
        if len(out) + len(w) + 1 > limit - 1:
            break
        out = (out + " " + w).strip()
    return out.rstrip(",;:") + "…"


def svg_size(svg):
    """Natural size of an SVG in inches."""
    def length(v):
        m = re.fullmatch(r"\s*([\d.]+)\s*(px|pt|in|cm|mm|pc|em)?\s*", v or "")
        if not m:
            return None
        n, unit = float(m.group(1)), m.group(2) or "px"
        return n / {"px": 96, "pt": 72, "in": 1, "cm": 2.54, "mm": 25.4, "pc": 6, "em": 6}[unit]
    head = re.search(r"<svg\b[^>]*>", svg, re.S)
    head = head.group(0) if head else ""
    w = re.search(r'\swidth="([^"]+)"', head)
    h = re.search(r'\sheight="([^"]+)"', head)
    vb = re.search(r'viewBox="\s*[-\d.]+[\s,]+[-\d.]+[\s,]+([\d.]+)[\s,]+([\d.]+)', head)
    wi, hi = length(w.group(1)) if w else None, length(h.group(1)) if h else None
    if (wi is None or hi is None) and vb:
        vw, vh = float(vb.group(1)) / 96, float(vb.group(2)) / 96
        if wi and not hi:
            hi = wi * vh / vw
        elif hi and not wi:
            wi = hi * vw / vh
        else:
            wi, hi = vw, vh
    return wi or 4.0, hi or 3.0


def text_blocks(text):
    text = text.replace("\r\n", "\n").strip()
    blocks = []
    for par in re.split(r"\n\s*\n", text):
        lines = par.split("\n")
        art = sum(1 for l in lines if re.match(r"^\s{2,}\S", l) or re.search(r"\S\s{3,}\S", l))
        if art > len(lines) / 2 or re.search(r"[|+]-{3,}|-{3,}[|+]", par):
            blocks.append(A.CodeBlock(par, ["plain"]))
        else:
            blocks.append(A.Para(A.text_inlines(" ".join(l.strip() for l in lines))))
    return blocks


def clean_html(html):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    main = (soup.find("main") or soup.find(attrs={"role": "main"}) or soup.find("article")
            or soup.select_one("div.document, div.body, div.md-content, div.content, #content")
            or soup.body or soup)
    for tag in main.find_all(["nav", "script", "style", "noscript", "header", "footer", "aside",
                              "button", "form", "iframe"]):
        tag.decompose()
    for tag in main.select(".headerlink, .toc, .sidebar, .related, .breadcrumb, .md-source-file, "
                           ".edit-this-page, .prev-next-area, .footer"):
        tag.decompose()
    for div in main.select("div[class*=highlight-]"):           # Sphinx: language on the wrapper
        lang = next((c[len("highlight-"):] for c in div.get("class", []) if c.startswith("highlight-")), "")
        pre = div.find("pre")
        if pre and lang and lang not in ("default", "none"):
            pre["class"] = [lang]
    return str(main)


def drop_badges(blocks):
    def fn(node):
        if node.get("t") == "Image" and BADGE.search(node["c"][2][0]):
            return []
        if node.get("t") == "Link" and not [i for i in node["c"][1] if i["t"] not in ("Space", "SoftBreak")] \
                and "book-xref" not in A.classes(node) and not node["c"][2][0].startswith("#"):
            return []
        if node.get("t") in ("Para", "Plain") and not [i for i in node["c"] if i["t"] not in ("Space", "SoftBreak", "LineBreak")]:
            return []
        return None
    return A.walk(blocks, fn)


def analyze_log(log):
    """Overfull lines (by chapter), missing glyphs and undefined references."""
    current, over, missing, undefined = "front", {}, {}, set()
    pages = None
    for line in log.splitlines():
        m = re.match(r"BOOKFILE (\S+)", line)
        if m:
            current = m.group(1)
            continue
        m = re.match(r"Overfull \\hbox \(([\d.]+)pt too wide\)", line)
        if m and float(m.group(1)) >= 1.0:
            over.setdefault(current, []).append(float(m.group(1)))
        m = re.search(r"Missing character: There is no (.+?) in font ([^!]+)!", line)
        if m:
            missing[m.group(1)] = m.group(2)
        m = re.search(r"(?:Reference|Hyper reference|Citation) `([^']+)' on page \d+ undefined", line)
        if m:
            undefined.add(m.group(1))
        m = re.search(r"name\{([^}]+)\} has been referenced but does not exist", line)
        if m:
            undefined.add(m.group(1))
        m = re.search(r"Output written on book\.pdf \((\d+) pages", line)
        if m:
            pages = int(m.group(1))
    return {"pages": pages, "overfull": {k: len(v) for k, v in over.items()},
            "overfull_max_pt": max([x for v in over.values() for x in v] or [0]),
            "missing_glyphs": missing, "undefined_refs": sorted(undefined)}


def print_report(r, build):
    print()
    if r.get("pdf"):
        print(f"wrote {r['pdf']} ({r.get('pages')} pages)")
    over = r.get("overfull") or {}
    if over:
        print(f"overfull lines: {sum(over.values())} (max {r['overfull_max_pt']:.1f}pt) in " +
              ", ".join(f"{k}: {v}" for k, v in sorted(over.items())))
    if r.get("missing_glyphs"):
        print("missing glyphs:", ", ".join(f"{k} ({v.strip()})" for k, v in list(r["missing_glyphs"].items())[:12]))
    if r.get("undefined_refs"):
        print("undefined references:", ", ".join(r["undefined_refs"][:12]))
    if r.get("unknown_directives"):
        print("directives without a book equivalent (content kept unless noted):")
        for k, v in r["unknown_directives"].items():
            print(f"  {k}: {', '.join(v[:4])}{' ...' if len(v) > 4 else ''}")
    if r.get("warnings"):
        print(f"{len(r['warnings'])} warning(s); first ones:")
        for w in r["warnings"][:15]:
            print("  -", w[:200])
    print(f"details: {build.dir / 'report.json'}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor", help="check the toolchain")
    p = sub.add_parser("init", help="propose book.yaml for a project, folder or file")
    p.add_argument("source")
    p.add_argument("-o", "--output", default="book.yaml")
    p = sub.add_parser("build", help="typeset the book described by book.yaml")
    p.add_argument("config")
    p.add_argument("--only", help="comma-separated chapter numbers/letters (and 'front') to include")
    p.add_argument("--no-pdf", action="store_true", help="write the LaTeX but do not compile it")
    args = ap.parse_args()
    if args.cmd == "doctor":
        return doctor()
    if args.cmd == "init":
        return init(args.source, args.output)
    only = set(args.only.split(",")) if args.only else None
    return Build(args.config, only).build(no_pdf=args.no_pdf)


if __name__ == "__main__":
    sys.exit(main())

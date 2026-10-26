"""Format-independent processing of one chapter's pandoc tree.

Every reader hands over a pandoc document; this module turns it into what
book.lua and the LaTeX design expect:

  directives/roles -> admonitions, API entries, code, plain text or links
  title            -> taken out (the chapter opener sets it)
  headings         -> first level below the title becomes \\section
  sections         -> boilerplate dropped, reference lists marked
  images           -> found, converted (SVG, GIF, WebP, EPS ...), sized
  code             -> language names pandoc can highlight, or "plain"
  raw HTML         -> converted or removed
  identifiers      -> prefixed with the chapter's slug (unique in the book)
  maths            -> \\newcommand & co. moved to the preamble

Links are resolved later, across the whole book (resolve_links).
"""

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

import astutil as A
from markup import ADMONITIONS, AUTODOC, DROP, UNWRAP

# Code-block language names -> pandoc highlighting names.
LANG_ALIASES = {
    "py": "python", "python3": "python", "py3": "python", "ipython": "python",
    "ipython3": "python", "pycon": "python", "pyi": "python", "sage": "python",
    "jupyter": "python", "numpy": "python", "pytb": "plain", "pyodide": "python",
    "sh": "bash", "shell": "bash", "console": "bash", "shell-session": "bash",
    "terminal": "bash", "zsh": "zsh", "ksh": "bash", "fish": "bash", "bat": "dosbat",
    "batch": "dosbat", "cmd": "dosbat", "ps1": "powershell", "pwsh": "powershell",
    "js": "javascript", "node": "javascript", "mjs": "javascript", "cjs": "javascript",
    "jsx": "javascriptreact", "ts": "typescript", "tsx": "typescript",
    "yml": "yaml", "rb": "ruby", "rs": "rust", "golang": "go", "kt": "kotlin",
    "kts": "kotlin", "cs": "cs", "csharp": "cs", "c#": "cs", "fs": "fsharp", "f#": "fsharp",
    "c++": "cpp", "cxx": "cpp", "cc": "cpp", "hpp": "cpp", "hh": "cpp", "h": "c",
    "objc": "objectivec", "objective-c": "objectivec", "tex": "latex", "md": "markdown",
    "htm": "html", "xhtml": "html", "svg": "xml", "jsonc": "json", "json5": "json",
    "ipynb": "json", "cfg": "ini", "conf": "ini", "properties": "ini", "toml": "toml",
    "docker": "dockerfile", "make": "makefile", "mk": "makefile", "psql": "sqlpostgresql",
    "postgres": "sqlpostgresql", "postgresql": "sqlpostgresql", "mysql": "sqlmysql",
    "pl": "perl", "pm": "perl", "jl": "julia", "rmd": "markdown", "qmd": "markdown",
    "hs": "haskell", "ex": "elixir", "exs": "elixir", "erl": "erlang", "clj": "clojure",
    "ml": "ocaml", "scm": "scheme", "rkt": "scheme", "vb": "monobasic", "v": "verilog",
    "sv": "systemverilog", "vhd": "vhdl", "asm": "nasm", "s": "gnuassembler",
    "proto": "protobuf", "gql": "graphql", "tf": "plain", "hcl": "plain",
    "text": "plain", "txt": "plain", "none": "plain", "output": "plain", "default": "plain",
    "raw": "plain", "log": "plain", "csv": "plain", "tsv": "plain", "pycon3": "python",
    "r": "r", "rscript": "r", "splus": "r", "matlab": "matlab", "m": "matlab",
    "octave": "octave", "lua": "lua", "dart": "dart", "swift": "swift", "scala": "scala",
    "sbt": "scala", "groovy": "groovy", "gradle": "groovy", "php": "php", "sql": "sql",
    "diff": "diff", "patch": "diff", "udiff": "diff", "ini": "ini", "nginx": "plain",
    "apacheconf": "apache", "jinja": "djangotemplate", "jinja2": "djangotemplate",
    "django": "djangotemplate", "html+jinja": "djangotemplate", "html+django": "djangotemplate",
    "xml+jinja": "djangotemplate", "j2": "djangotemplate", "mermaid": "plain",
    "dot": "dot", "graphviz": "dot", "nix": "nix", "zig": "plain", "elm": "elm",
}

GENERIC_ALT = {"", "img", "image", "picture", "pic", "figure", "fig", "screenshot",
               "screen shot", "photo", "png", "jpg", "jpeg", "gif", "svg", "alt", "alt text",
               "diagram", "logo", "icon", "badge"}
REFS = re.compile(r"^\s*(references?|bibliography|further reading|see also|resources|"
                  r"links|sources|reading list|literature)\s*:?\s*$", re.I)


class UnitContext:
    """What postprocessing needs to know about one source file."""

    def __init__(self, book, path, slug, fmt):
        self.book = book            # the Build (see book.py)
        self.path = Path(path)
        self.dir = Path(path).parent
        self.slug = slug
        self.fmt = fmt              # "markdown", "rst", "ipynb", "docx", ...
        self.ids = {}               # original id -> book id
        self.anchor = slug          # what links to this file point at


# ---------------------------------------------------------------------------
# directives and roles
# ---------------------------------------------------------------------------

def label_for(kind, arg=""):
    base = ADMONITIONS.get(kind, kind.replace("-", " ").title())
    if kind.startswith("version") or kind == "deprecated":
        return f"{base} {arg}".strip()
    if kind in ("admonition", "sidebar", "topic") and arg:
        return arg
    return base


def first_title_div(blocks):
    if blocks and blocks[0].get("t") == "Div" and "title" in A.classes(blocks[0]):
        return A.stringify(blocks[0]["c"][1]).strip(), blocks[1:]
    return None, blocks


def convert_divs(blocks, uctx):
    def fn(node):
        if node.get("t") != "Div":
            return None
        cls = A.classes(node)
        kv = A.attrs(node)
        content = node["c"][1]
        keep = {"admonition", "bookapi", "missing-image", "book-refs"}
        if "admonition-src" in cls:                     # from MyST
            kind = kv.get("kind", "note")
            label = kv.get("label") or label_for(kind, kv.get("arg", ""))
            return A.Div(content, ["admonition"], [("label", label)])
        if "bookapi" in cls:
            if content and content[0]["t"] in ("Para", "Plain") and \
                    len(content[0]["c"]) == 1 and content[0]["c"][0]["t"] == "Code":
                sig = content[0]["c"][0]["c"][1]
                return A.Div(content[1:], ["bookapi"], [("signature", sig), ("index", api_index_key(sig))])
            return A.Div(content, ["bookapi"], [("signature", "")])
        if cls and cls[0].startswith("callout-"):        # Quarto callouts
            kind = cls[0][len("callout-"):]
            title = kv.get("title")
            if not title and content and content[0]["t"] == "Header":
                title, content = A.stringify(content[0]["c"][2]), content[1:]
            return A.Div(content, ["admonition"], [("label", title or label_for(kind))])
        if cls and cls[0] in ADMONITIONS and cls[0] not in ("admonition-src",):
            title, rest = first_title_div(content)
            kind = cls[0]
            if kind in ("admonition", "sidebar", "topic") and not title and rest \
                    and rest[0]["t"] in ("Para", "Plain"):
                title, rest = A.stringify(rest[0]["c"]).strip(), rest[1:]   # rST: title paragraph
            label = title if title and kind in ("admonition", "sidebar", "topic") else label_for(kind)
            return A.Div(rest, ["admonition"], [("label", label)])
        if cls and (cls[0] in DROP or cls[0] in ("toctree",)):
            return []
        if cls and cls[0] in ("epigraph", "pull-quote", "highlights"):
            return A.el("BlockQuote", content)
        if cls and cls[0] in AUTODOC:
            target = A.stringify(content[:1]).strip() if content else ""
            uctx.book.note_unknown_directive(cls[0], uctx.path, f"autodoc target {target!r} not found")
            return A.Div([A.Para(A.text_inlines(f"API reference for {target} "
                                                "(generated from the source code online)."))],
                         ["admonition"], [("label", "API")])
        if any(c in keep for c in cls):
            return None
        if kv.get("custom-style"):                         # Word paragraph styles
            return content
        if cls and cls[0] not in UNWRAP and uctx.fmt == "rst" and cls[0] not in ("title",):
            uctx.book.note_unknown_directive(cls[0], uctx.path, "content kept")
        return content
    return A.walk(blocks, fn)


def api_index_key(sig):
    """makeindex entry for an API signature, filed under the object's own
    name: 'class jinja2.Environment(...)' -> Environment (jinja2)."""
    name = re.sub(r"^(async |static |classmethod |class |property |exception |def )+", "", sig.strip())
    name = re.split(r"[(\s\[:=]", name, maxsplit=1)[0].strip().strip(".")
    if not name:
        return ""
    parts = name.split(".")
    last, qual = parts[-1], ".".join(parts[:-1])

    def esc(t):
        t = t.replace("\\", "\\textbackslash{}")
        for c in "_#$%&":
            t = t.replace(c, "\\" + c)
        return re.sub(r'([!@|"])', r'"\1', t)
    show = f"\\texttt{{{esc(last)}}}" + (f" ({esc(qual)})" if qual else "")
    sort = re.sub(r'([!@|"])', r'"\1', (last + " " + qual).strip().lower())
    return f"{sort}@{show}"


ROLE_CODE = {"func", "meth", "class", "mod", "attr", "obj", "data", "const", "exc", "envvar",
             "option", "program", "command", "file", "samp", "makevar", "kbd", "code",
             "literal", "mimetype", "regexp", "token", "setting", "confval", "type", "member",
             "var", "macro", "struct", "enum", "enumerator", "function", "property", "method",
             "decorator", "module", "event", "rst:dir", "rst:role", "directive", "role"}


def role_text(body):
    """("display text", target) for 'text <target>', '~a.b.c', '!x'."""
    body = body.strip()
    m = re.match(r"^(.*?)\s*<([^<>]+)>$", body, re.S)
    if m and m.group(1).strip():
        return m.group(1).strip(), m.group(2).strip()
    target = m.group(2).strip() if m else body
    disp = target.lstrip("!")
    if disp.startswith("~"):
        disp = disp[1:].split(".")[-1]
    return disp, target.lstrip("!~")


def convert_roles(blocks):
    def fn(node):
        if node.get("t") != "Code":
            return None
        a = node["c"][0]
        cls, kv = a[1], dict(a[2])
        if "interpreted-text" not in cls:
            if cls:
                a[1] = []
            return None
        role = kv.get("role", "")
        name = role.split(":")[-1]
        body = node["c"][1]
        disp, target = role_text(body)
        if name == "math":
            return A.Math("InlineMath", body)
        explicit = bool(re.match(r"^(.*?)\s*<([^<>]+)>$", body.strip(), re.S))
        if name in ("ref", "doc") and target in ("genindex", "modindex", "py-modindex", "search"):
            return []                                   # pages only a website has
        if name in ("ref", "numref", "any", "label"):
            return xref("ref:" + target, disp if explicit else "")
        if name == "doc":
            return xref("doc:" + target, disp if explicit else "")
        if name in ("term", "dfn"):
            return A.el("Emph", A.text_inlines(disp))
        if name == "abbr":
            return A.text_inlines(re.sub(r"\s*\(.*\)\s*$", "", body))
        if name == "pep":
            return A.text_inlines(f"PEP {body}")
        if name == "rfc":
            return A.text_inlines(f"RFC {body}")
        if name in ("sub", "subscript"):
            return A.el("Subscript", A.text_inlines(body))
        if name in ("sup", "superscript"):
            return A.el("Superscript", A.text_inlines(body))
        if name in ("guilabel", "menuselection"):
            return A.el("Emph", A.text_inlines(body.replace("-->", "›").replace("&", "")))
        if name in ("download",):
            return A.text_inlines(disp)
        if name in ("func", "meth") and not disp.endswith(")"):
            disp += "()"
        if name in ROLE_CODE or ":" in role:
            return A.Code(disp)
        return A.Code(disp)
    return A.walk(blocks, fn)


# ---------------------------------------------------------------------------
# typographic quotes
# ---------------------------------------------------------------------------

INLINE_TYPES = {"Str", "Space", "SoftBreak", "LineBreak", "Emph", "Strong", "Underline", "Strikeout",
                "Superscript", "Subscript", "SmallCaps", "Quoted", "Cite", "Code", "Math", "RawInline",
                "Link", "Image", "Note", "Span"}
OPENERS = set("([{<\u2014\u2013-/\u00a0")


def curl(s, prev=" "):
    """Straight quotes -> typographic ones: opening after a space or an
    opening bracket, closing (or an apostrophe) everywhere else."""
    out = []
    for i, ch in enumerate(s):
        before = s[i - 1] if i else prev
        opening = before.isspace() or before in OPENERS
        if ch == '"':
            out.append("\u201c" if opening else "\u201d")
        elif ch == "'":
            nxt = s[i + 1] if i + 1 < len(s) else ""
            out.append("\u2018" if opening and nxt.isalpha() else "\u2019")
        else:
            out.append(ch)
    return "".join(out)


UNITS = {"%", "‰", "°", "°C", "°F", "m", "cm", "mm", "km", "µm", "μm", "nm", "kg", "g", "mg", "µg",
         "s", "ms", "µs", "ns", "min", "h", "Hz", "kHz", "MHz", "GHz", "kB", "KB", "MB", "GB", "TB", "KiB",
         "MiB", "GiB", "TiB", "kW", "MW", "mV", "mA", "kV", "Ω", "kΩ", "J", "kJ", "kcal", "ml", "mL",
         "px", "pt", "dpi", "ppi", "ppm", "dB", "°N", "°S", "°E", "°W", "km/h", "m/s", "mph"}


def keep_units(inlines):
    """'4.1 °C', '50 m', '20 %': no line break between a number and its unit."""
    out, i = [], 0
    while i < len(inlines):
        il = inlines[i]
        if (il["t"] == "Space" and out and out[-1]["t"] == "Str" and out[-1]["c"][-1:].isdigit()
                and i + 1 < len(inlines) and inlines[i + 1]["t"] == "Str"
                and re.sub(r"[.,;:!?)\]]+$", "", inlines[i + 1]["c"]) in UNITS):
            out[-1] = A.Str(out[-1]["c"] + "\u00a0" + inlines[i + 1]["c"])
            i += 2
            continue
        out.append(il)
        i += 1
    return out


def smart_quotes(x):
    """Curl the quotes of all prose (pandoc's readers for reST, HTML and
    plain text leave them straight, and TeX would print " as a closing
    quote).  Code, maths and raw markup are left alone."""
    if isinstance(x, list):
        if x and all(isinstance(i, dict) and i.get("t") in INLINE_TYPES for i in x):
            x[:] = keep_units(x)
            prev = " "
            for il in x:
                t = il["t"]
                if t == "Str":
                    if "'" in il["c"] or '"' in il["c"]:
                        il["c"] = curl(il["c"], prev)
                    prev = il["c"][-1:] or prev
                elif t in ("Space", "SoftBreak", "LineBreak"):
                    prev = " "
                else:
                    if t not in ("Code", "Math", "RawInline"):
                        smart_quotes(il.get("c"))
                    prev = "x"
        else:
            for i in x:
                smart_quotes(i)
    elif isinstance(x, dict):
        if x.get("t") in ("Code", "CodeBlock", "RawInline", "RawBlock", "Math"):
            return
        if "t" in x:
            c = x.get("c")
            if isinstance(c, (list, dict)):
                smart_quotes(c)
        else:
            for v in x.values():
                smart_quotes(v)
    return x


def drop_caption_echoes(blocks):
    """Word documents keep a caption's paragraph next to the table or
    figure that pandoc has given the caption to: drop the echo."""
    def norm(t):
        t = re.sub(r"^(table|figure|fig\.|image)\s*\d+[.:]?\s*", "", t.strip(), flags=re.I)
        return re.sub(r"\s+", " ", t).strip(" .").lower()

    def caption_of(b):
        if b["t"] == "Table":
            return A.stringify(b["c"][1][1])
        if b["t"] == "Figure":
            return A.stringify(b["c"][1][1])
        if b["t"] in ("Para", "Plain"):
            imgs = [i for i in b["c"] if i["t"] == "Image"]
            if len(imgs) == 1 and len([i for i in b["c"] if i["t"] not in ("Space", "SoftBreak")]) == 1:
                return A.stringify(imgs[0]["c"][1])
        return ""

    drop = set()
    for i, b in enumerate(blocks):
        cap = norm(caption_of(b))
        if len(cap) < 8:
            continue
        for j in (i - 1, i + 1):
            if 0 <= j < len(blocks) and blocks[j]["t"] in ("Para", "Plain") and norm(A.stringify(blocks[j])) == cap:
                drop.add(j)
    return [b for k, b in enumerate(blocks) if k not in drop]


# ---------------------------------------------------------------------------
# titles and headings
# ---------------------------------------------------------------------------

def take_title(doc, meta_title=None):
    """(title inlines or None, remaining blocks)."""
    blocks = doc["blocks"]
    if meta_title:
        return A.text_inlines(meta_title), blocks
    title = A.meta_text(doc.get("meta", {}), "title")
    if title:
        return doc["meta"]["title"]["c"] if doc["meta"]["title"]["t"] == "MetaInlines" \
            else A.text_inlines(title), blocks
    heads = [i for i, b in enumerate(blocks) if b["t"] == "Header"]
    if not heads:
        return None, blocks
    first = heads[0]
    level = blocks[first]["c"][0]
    lead = blocks[:first]
    ornamental = all(b["t"] in ("Para", "Plain") and all(
        i["t"] in ("Image", "Link", "Space", "SoftBreak", "LineBreak") for i in b["c"]) or
        b["t"] in ("RawBlock",) for b in lead)
    if first <= 3 and ornamental and level == min(blocks[h]["c"][0] for h in heads):
        return blocks[first]["c"][2], lead + blocks[first + 1:]
    return None, blocks


def normalize_headings(blocks, top=1):
    """Shift heading levels so the first heading after the title is `top`."""
    heads = [b for b in A.iter_nodes(blocks) if b.get("t") == "Header"]
    if not heads:
        return blocks
    base = min(h["c"][0] for h in heads)

    def fn(node):
        if node.get("t") == "Header":
            node["c"][0] = max(top, node["c"][0] - base + top)
        return None
    return A.walk(blocks, fn)


def section_ranges(blocks, match):
    """Yield (start, end) for headed sections whose heading matches."""
    i = 0
    while i < len(blocks):
        b = blocks[i]
        if b["t"] == "Header" and match(A.stringify(b["c"][2])):
            level, j = b["c"][0], i + 1
            while j < len(blocks) and not (blocks[j]["t"] == "Header" and blocks[j]["c"][0] <= level):
                j += 1
            yield i, j
            i = j
        else:
            i += 1


SITE_SECTIONS = [r"^indices and tables$", r"^indices$", r"^search( page)?$", r"^edit (this|on) "]


def drop_sections(blocks, patterns):
    """Sections whose heading matches one of the patterns (and sections
    only websites have, such as Sphinx's "Indices and tables")."""
    patterns = list(patterns or []) + SITE_SECTIONS
    regs = [re.compile(p, re.I) for p in patterns]
    match = lambda t: any(r.search(t) for r in regs)
    out, last = [], 0
    for s, e in section_ranges(blocks, match):
        out.extend(blocks[last:s])
        last = e
    return out + blocks[last:]


def drop_empty_items(blocks):
    """List items, and lists, left empty by removed links."""
    def empty(blocks_):
        return not A.stringify(blocks_).strip() and not any(
            n.get("t") in ("Image", "CodeBlock", "RawBlock", "Math") for n in A.iter_nodes(blocks_))

    def fn(node):
        t = node.get("t")
        if t == "BulletList":
            items = [i for i in node["c"] if not empty(i)]
            return [] if not items else A.el("BulletList", items)
        if t == "OrderedList":
            items = [i for i in node["c"][1] if not empty(i)]
            return [] if not items else A.el("OrderedList", [node["c"][0], items])
        return None
    return A.walk(blocks, fn)


def drop_empty_sections(blocks):
    """Headings with nothing under them (left behind by toctrees and other
    directives that have no place in print)."""
    while True:
        out = []
        for i, b in enumerate(blocks):
            if b["t"] == "Header":
                nxt = blocks[i + 1] if i + 1 < len(blocks) else None
                if nxt is None or (nxt["t"] == "Header" and nxt["c"][0] <= b["c"][0]):
                    continue
            out.append(b)
        if len(out) == len(blocks):
            return out
        blocks = out


def mark_references(blocks):
    out, last = [], 0
    for s, e in section_ranges(blocks, lambda t: bool(REFS.match(t))):
        out.extend(blocks[last:s + 1])
        out.append(A.Div(blocks[s + 1:e], ["book-refs"]))
        last = e
    return out + blocks[last:]


# ---------------------------------------------------------------------------
# images
# ---------------------------------------------------------------------------

def parse_length(v, textwidth_in, px_per_in=96.0):
    """A width/height attribute -> LaTeX length (or None)."""
    if not v:
        return None
    v = str(v).strip()
    m = re.fullmatch(r"([\d.]+)\s*(%|px|in|cm|mm|pt|em|ex|pc)?", v)
    if not m:
        if "\\linewidth" in v or "\\textwidth" in v or "\\textheight" in v:
            return v
        return None
    num, unit = float(m.group(1)), m.group(2) or "px"
    if unit == "%":
        return f"{min(num, 100) / 100:.3f}\\linewidth"
    per_in = {"px": px_per_in, "in": 1, "cm": 2.54, "mm": 25.4, "pt": 72.27, "pc": 6.02,
              "em": 7.2, "ex": 14.4}[unit]
    return f"{min(num / per_in, textwidth_in):.2f}in"       # never wider than the text


def fetch_remote(url, dest_dir, warn):
    dest_dir.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha1(url.encode()).hexdigest()[:12]
    ext = Path(urllib.parse.urlparse(url).path).suffix.lower()[:5] or ".img"
    dest = dest_dir / f"{h}{ext}"
    if dest.exists():
        return dest
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "book-pdf"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read(25_000_000)
            ctype = r.headers.get("Content-Type", "")
        if ext == ".img":
            ext = {"image/svg+xml": ".svg", "image/png": ".png", "image/jpeg": ".jpg",
                   "image/gif": ".gif", "image/webp": ".webp"}.get(ctype.split(";")[0], ".png")
            dest = dest_dir / f"{h}{ext}"
        dest.write_bytes(data)
        return dest
    except Exception as exc:
        warn(f"could not download image {url}: {exc}")
        return None


class ImageStore:
    """Copies and converts the book's images into build/img."""

    def __init__(self, build):
        self.build = build
        self.dir = build.dir / "img"
        self.cache = {}

    def place(self, src_path):
        """Path (relative to the build dir) of a LaTeX-ready copy, and its
        natural size in inches (w, h, is_vector)."""
        src_path = Path(src_path)
        key = str(src_path.resolve())
        if key in self.cache:
            return self.cache[key]
        h = hashlib.sha1(key.encode()).hexdigest()[:8]
        stem = re.sub(r"[^A-Za-z0-9_-]+", "-", src_path.stem)[:40] or "image"
        ext = src_path.suffix.lower()
        self.dir.mkdir(parents=True, exist_ok=True)
        res = None
        try:
            if ext in (".png", ".jpg", ".jpeg"):
                dest = self.dir / f"{stem}-{h}{ext}"
                shutil.copy2(src_path, dest)
                with Image.open(dest) as im:
                    dpi = (im.info.get("dpi") or (0, 0))[0]
                    res = (dest, im.size[0], im.size[1], dpi, False)
            elif ext == ".pdf":
                dest = self.dir / f"{stem}-{h}.pdf"
                shutil.copy2(src_path, dest)
                from pypdf import PdfReader
                box = PdfReader(str(dest)).pages[0].mediabox
                res = (dest, float(box.width) / 72 * 96, float(box.height) / 72 * 96, 96, True)
            elif ext == ".svg" or ext == ".svgz":
                dest = self.dir / f"{stem}-{h}.pdf"
                text = src_path.read_text(errors="replace")
                w, h_in = self.build.svg_to_pdf(text, dest, scale=1.0, natural=True)
                res = (dest, w * 96, h_in * 96, 96, True)
            elif ext in (".eps", ".ps"):
                dest = self.dir / f"{stem}-{h}.pdf"
                subprocess.run(["gs", "-q", "-dNOPAUSE", "-dBATCH", "-dEPSCrop", "-sDEVICE=pdfwrite",
                                f"-sOutputFile={dest}", str(src_path)], check=True,
                               capture_output=True)
                from pypdf import PdfReader
                box = PdfReader(str(dest)).pages[0].mediabox
                res = (dest, float(box.width) / 72 * 96, float(box.height) / 72 * 96, 96, True)
            else:
                dest = self.dir / f"{stem}-{h}.png"
                with Image.open(src_path) as im:
                    im.seek(0)
                    frame = im.convert("RGBA") if im.mode in ("P", "LA", "RGBA") else im.convert("RGB")
                    frame.save(dest)
                    dpi = (im.info.get("dpi") or (0, 0))[0]
                    res = (dest, frame.size[0], frame.size[1], dpi, False)
        except Exception as exc:
            self.build.warn(f"image {src_path}: {exc}")
            res = None
        self.cache[key] = res
        return res


def natural_size(w_px, h_px, dpi, is_vector, textwidth_in, max_h_in):
    """Printed size for an image whose source gave no size."""
    if w_px <= 0 or h_px <= 0:
        return textwidth_in * 0.6, max_h_in * 0.5
    if dpi and dpi >= 110 and not is_vector:
        w = w_px / dpi                          # print-ready image: honour its dpi
    elif w_px < 200:
        w = w_px / 96                           # icons and small diagrams stay small
    else:
        w = w_px / 140                          # a ~750px web column fills the text block
    w = min(textwidth_in, w)
    h = w * h_px / w_px
    if h > max_h_in:
        h, w = max_h_in, max_h_in * w_px / h_px
    return w, h


def meaningful_alt(alt, src):
    a = alt.strip().lower()
    if a in GENERIC_ALT or a == Path(src).name.lower() or a == Path(src).stem.lower():
        return False
    return len(a.split()) >= 2 or len(a) >= 12


def process_images(blocks, uctx):
    build = uctx.book
    store = build.images

    def resolve_src(src):
        if src.startswith("data:"):
            m = re.match(r"data:image/(\w+)[^,]*;base64,(.*)", src, re.S)
            if not m:
                return None
            ext = {"svg+xml": ".svg", "jpeg": ".jpg"}.get(m.group(1), "." + m.group(1))
            dest = build.dir / "img" / "inline" / (hashlib.sha1(src.encode()).hexdigest()[:12] + ext)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(base64.b64decode(m.group(2)))
            return dest
        if re.match(r"^https?://", src):
            return fetch_remote(src, build.dir / "img" / "remote", build.warn) if build.fetch_images else None
        clean = urllib.parse.unquote(src.split("#")[0].split("?")[0])
        p = Path(clean)
        cands = [p] if p.is_absolute() else [uctx.dir / p, build.root / p,
                                               *(Path(d) / p for d in build.image_dirs)]
        if clean.startswith("/"):
            cands.append(build.root / clean.lstrip("/"))
        for c in cands:
            if c.is_file():
                return c.resolve()
        return None

    def handle(img, standalone):
        a, alt_inl, target = img["c"]
        src = target[0]
        kv = dict(a[2])
        if kv.get("book-placed"):                # a figure's image, already done
            return img
        path = resolve_src(src)
        placed = store.place(path) if path else None
        if not placed:
            build.warn(f"{uctx.path.name}: image not found or unreadable: {src}")
            return None
        dest, w_px, h_px, dpi, vector = placed
        tw, max_h = build.textwidth_in, build.image_max_height_in
        width = parse_length(kv.get("width"), tw)
        height = parse_length(kv.get("height"), tw)
        if standalone:
            if not width and not height:
                w, h = natural_size(w_px, h_px, dpi, vector, tw, max_h)
                width, height = f"{w / tw:.3f}\\linewidth", f"{h:.2f}in"
            else:
                width = width or "\\linewidth"
                height = height or f"{max_h:.2f}in"
        else:
            if not width and not height:
                height = "1.1em" if h_px <= 64 or uctx.fmt in ("markdown", "rst", "html") else None
                width = None if height else f"{min(tw, w_px / 96):.2f}in"
        kv2 = {"book-placed": "1"}
        if width:
            kv2["width"] = width
        if height:
            kv2["height"] = height
        if kv.get("book-caption") == "yes" or (standalone and meaningful_alt(A.stringify(alt_inl), src)
                                               and uctx.fmt not in ("ipynb",)):
            kv2["book-caption"] = "yes"
        img["c"][0] = A.attr(a[0], [], list(kv2.items()))
        img["c"][2] = [build.rel(dest), target[1]]
        return img

    def only_image(inlines):
        imgs = [i for i in inlines if i["t"] == "Image"]
        rest = [i for i in inlines if i["t"] not in ("Image", "Space", "SoftBreak", "LineBreak")]
        if len(imgs) == 1 and not rest:
            return imgs[0]
        # a linked image (badge or screenshot wrapped in a link)
        if len(inlines) == 1 and inlines[0]["t"] == "Link":
            inner = inlines[0]["c"][1]
            if len(inner) == 1 and inner[0]["t"] == "Image":
                return inner[0]
        return None

    def fn(node):
        t = node.get("t")
        if t in ("Para", "Plain"):
            img = only_image(node["c"])
            if img is not None:
                res = handle(img, True)
                if res is None:
                    alt = A.stringify(img["c"][1]) or img["c"][2][0]
                    return A.Div([A.Plain(A.text_inlines(f"Image not available: {alt}"))],
                                 ["missing-image"])
                return A.Para([res])
            out = []
            for il in node["c"]:
                if il["t"] == "Image":
                    r = handle(il, False)
                    if r is not None:
                        out.append(r)
                else:
                    out.append(il)
            node["c"] = out
        elif t == "Figure":
            imgs = [n for n in A.iter_nodes(node["c"][2]) if n.get("t") == "Image"]
            if imgs:
                if handle(imgs[0], True) is None:
                    return A.Div([A.Plain(A.text_inlines("Image not available"))], ["missing-image"])
        return None

    # images inside table cells and links are inline; everything else is handled above
    return A.walk(blocks, fn)


# ---------------------------------------------------------------------------
# code, raw HTML, identifiers, maths
# ---------------------------------------------------------------------------

def normalize_code(blocks, build, default_lang):
    """Language names pandoc can highlight; blocks without one get
    default_lang, or are set plain when it is None."""
    langs = build.highlight_languages

    def canon(name):
        n = name.lower().strip().lstrip(".")
        n = LANG_ALIASES.get(n, n)
        if n in langs:
            return n
        return "plain"

    def fn(node):
        if node.get("t") != "CodeBlock":
            return None
        a = node["c"][0]
        cls = a[1]
        if "output" in cls:
            return None
        keep = [c for c in cls if c in ("numberLines",)]
        lang_cls = [c for c in cls if c not in ("numberLines", "sourceCode", "code", "highlight",
                                                 "notranslate", "literal-block", "doctest")]
        text = node["c"][1]
        if "doctest" in cls and not lang_cls:
            lang_cls = ["python"]
        lang = canon(lang_cls[0]) if lang_cls else (canon(default_lang) if default_lang else "plain")
        if lang == "plain" and lang_cls and not text.strip():
            return []
        a[1] = [lang] + keep
        node["c"][1] = text.expandtabs(4).rstrip("\n")
        return None
    return A.walk(blocks, fn)


def convert_raw_html(blocks, uctx):
    build = uctx.book

    def fn(node):
        t = node.get("t")
        if t == "RawBlock" and node["c"][0] == "html":
            html = node["c"][1]
            if not re.sub(r"<!--.*?-->", "", html, flags=re.S).strip():
                return []
            try:
                doc, _ = A.read(html, "html")
            except A.PandocError:
                return []
            return doc["blocks"]
        if t == "RawInline" and node["c"][0] == "html":
            tag = node["c"][1].strip().lower()
            if re.match(r"^<br\s*/?>$", tag):
                return A.el("LineBreak")
            return []
        if t in ("RawBlock", "RawInline") and node["c"][0] not in ("latex", "tex"):
            return []
        return None
    return A.walk(blocks, fn)


MATH_LABEL = re.compile(r"\\label\{([^}]+)\}")


def prefix_ids(blocks, uctx, used):
    """Identifiers unique in the book (prefixed with the unit's slug); the
    numbered ones (figures, tables, labelled equations) are recorded in
    build.numbered so that references to them can print their number."""
    numbered = uctx.book.numbered

    def new_id(orig):
        new = re.sub(r"[^A-Za-z0-9_:.-]+", "-", f"{uctx.slug}-{orig}")
        while new in used:
            new += "-x"
        used.add(new)
        uctx.ids.setdefault(orig, new)
        return new

    def fn(node):
        t = node.get("t")
        if t == "Math":
            def lab(m):
                new = new_id(m.group(1))
                numbered[new] = "eq"
                return "\\label{" + new + "}"
            node["c"][1] = MATH_LABEL.sub(lab, node["c"][1])
            return None
        a = A.get_attr(node)
        if a is None or not a[0]:
            return None
        if t == "Link":
            a[0] = ""
            return None
        a[0] = new_id(a[0])
        if t in ("Image", "Figure"):
            numbered[a[0]] = "fig"
        elif t == "Table":
            numbered[a[0]] = "tbl"
        return None
    return A.walk(blocks, fn)


MACRO_DEF = re.compile(r"\\(newcommand|renewcommand|providecommand|DeclareMathOperator)\*?\s*"
                       r"\{?\\([A-Za-z]+)\}?\s*(\[\d\])?")


def balanced(s, i):
    """End index (exclusive) of the {...} group starting at s[i] == '{'."""
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "{" and (j == 0 or s[j - 1] != "\\"):
            depth += 1
        elif s[j] == "}" and s[j - 1] != "\\":
            depth -= 1
            if depth == 0:
                return j + 1
    return len(s)


def extract_macros(blocks, build):
    def fn(node):
        if node.get("t") != "Math":
            return None
        text = node["c"][1]
        if "command" not in text and "DeclareMathOperator" not in text and "\\def" not in text:
            return None
        out, i = [], 0
        while True:
            m = MACRO_DEF.search(text, i)
            if not m:
                break
            j = m.end()
            while j < len(text) and text[j] in " \t\n":
                j += 1
            if j < len(text) and text[j] == "[" and m.group(1) != "DeclareMathOperator":
                k = text.find("]", j)
                j = k + 1 if k > 0 else j
            if j < len(text) and text[j] == "{":
                end = balanced(text, j)
                build.add_macro(m.group(2), text[m.start():end])
                out.append(text[i:m.start()])
                i = end
            else:
                out.append(text[i:m.end()])
                i = m.end()
        out.append(text[i:])
        new = "".join(out).strip()
        if not new:
            return []
        node["c"][1] = new
        return None
    blocks = A.walk(blocks, fn)
    # paragraphs left empty by moved definitions
    return [b for b in blocks if not (b["t"] in ("Para", "Plain") and not b["c"])]


# ---------------------------------------------------------------------------
# links (book-wide)
# ---------------------------------------------------------------------------

XREF_KIND = {"fig": "the figure", "tbl": "the table", "eq": "the equation", "lst": "the listing",
             "thm": "the theorem", "lem": "the lemma", "def": "the definition", "exm": "the example"}


def xref(target, text=""):
    """A cross-reference whose wording is filled in once the target is known."""
    return A.el("Link", [A.attr("", ["book-xref"]), A.text_inlines(text) if text else [], [target, ""]])


def resolve_links(units, build):
    """Point links at chapters and sections of this book where possible;
    external links are kept; anything else becomes plain text.  Cross-
    references without wording get the chapter's number ("Chapter 3") or
    the section's title."""
    by_path, labels, titles = {}, {}, {}
    for u in units:
        p = u.path.resolve()
        for key in {str(p), str(p.with_suffix("")), str(p.parent) if p.stem in ("index", "README", "readme") else None}:
            if key:
                by_path.setdefault(key, u)
        for orig, new in u.ids.items():
            labels.setdefault(orig, new)
            labels.setdefault(orig.lower(), new)
        for n in A.iter_nodes(u.doc["blocks"]):
            if n.get("t") == "Header" and n["c"][1][0]:
                titles[n["c"][1][0]] = n["c"][2]
    chapters = getattr(build, "xref_labels", {})

    def lookup_path(base_dir, ref):
        ref = urllib.parse.unquote(ref)
        p = (build.root / ref.lstrip("/")) if ref.startswith("/") else (base_dir / ref)
        p = Path(os.path.normpath(p))
        for cand in (p, p.with_suffix(""), p / "index", p / "README"):
            u = by_path.get(str(cand)) or by_path.get(str(cand.with_suffix("")))
            if u:
                return u
        return None

    numbered = getattr(build, "numbered", {})
    PREFIX = {"fig": "Figure~\\ref", "tbl": "Table~\\ref", "eq": "Equation~\\eqref"}

    def latex_ref(node, new, latex_style):
        """A reference to a numbered figure, table or equation, set by LaTeX."""
        anchor = new[1:] if new and new.startswith("#") else None
        kind = numbered.get(anchor)
        if not kind:
            return None
        if latex_style:                     # LaTeX source: "Figure~\ref{x}" in the text already
            cmd = "\\eqref" if A.attrs(node).get("reference-type") == "eqref" else "\\ref"
        else:
            cmd = PREFIX[kind]
        return A.RawInline("latex", f"{cmd}{{{anchor}}}")

    def wording(node, new, raw):
        anchor = new[1:] if new and new.startswith("#") else None
        if anchor in chapters:
            return A.text_inlines(chapters[anchor])
        if anchor in titles:
            return [i for i in json.loads(json.dumps(titles[anchor])) if i["t"] not in ("Note",)]
        kind = raw.split("-")[0].split(":")[0]
        if kind in XREF_KIND:
            return A.text_inlines(XREF_KIND[kind])
        return A.text_inlines(re.sub(r"^(sec|fig|tbl|eq|ch|chap)[-:]", "", raw).replace("-", " ").replace("_", " "))

    for u in units:
        def fn(node, u=u):
            if node.get("t") != "Link":
                return None
            target = node["c"][2][0]
            text = node["c"][1]
            if re.match(r"^(https?|ftp|mailto):", target):
                return None
            new, raw = None, target
            if target.startswith("ref:"):
                lab = raw = target[4:]
                new = labels.get(lab) or labels.get(lab.lower()) or \
                    labels.get(re.sub(r"[^a-z0-9]+", "-", lab.lower()).strip("-"))
                new = "#" + new if new else None
            elif target.startswith("doc:"):
                raw = target[4:]
                hit = lookup_path(u.dir, target[4:])
                new = "#" + hit.anchor if hit else None
            elif target.startswith("#"):
                frag = raw = target[1:]
                hit = u.ids.get(frag) or u.ids.get(frag.lower()) or labels.get(frag) or labels.get(frag.lower())
                new = "#" + hit if hit else None
            elif not re.match(r"^[a-z][a-z0-9+.-]*:", target):
                path, _, frag = target.partition("#")
                hit = lookup_path(u.dir, path) if path else u
                if hit:
                    sub = hit.ids.get(frag) if frag else None
                    new = "#" + (sub or hit.anchor)
                elif build.link_base:
                    try:
                        rel = Path(os.path.normpath(u.dir / path)).resolve().relative_to(build.repo_root)
                        new = build.link_base.rstrip("/") + "/" + rel.as_posix() + (f"#{frag}" if frag else "")
                    except ValueError:
                        new = None
            latex_style = "reference-type" in A.attrs(node)
            if latex_style or "book-xref" in A.classes(node):
                ref = latex_ref(node, new, latex_style)
                if ref is not None:
                    return ref
                if latex_style and new and new[1:] in chapters:      # "Chapter~\ref{ch:x}"
                    node["c"][1] = A.text_inlines(chapters[new[1:]].split()[-1])
                    node["c"][0] = A.attr()
                    node["c"][2] = [new, ""]
                    return None
                if latex_style:
                    text = []                                       # placeholder "[label]"
            if "book-xref" in A.classes(node) or not A.stringify(text).strip():
                text = wording(node, new, raw) if not A.stringify(text).strip() else text
                node["c"][1] = text
                node["c"][0] = A.attr()
            if new:
                node["c"][2] = [new, node["c"][2][1]]
                return None
            return text
        u.doc["blocks"] = A.walk(u.doc["blocks"], fn)

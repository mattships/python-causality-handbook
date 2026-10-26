"""Find a project's book structure: which files are chapters, in which order,
under which parts, and the book's title and author.

`book.py init SOURCE` calls propose() and writes the result as book.yaml for
review.  Layouts are recognised in this order:

  Jupyter Book     _toc.yml (+ _config.yml)
  Quarto book      _quarto.yml (project type book)
  bookdown         _bookdown.yml or index.Rmd
  MkDocs           mkdocs.yml (nav)
  mdBook, GitBook  SUMMARY.md (+ book.toml / book.json)
  Sphinx           conf.py and the root document's toctrees
  docs folder      Markdown, rST, notebooks, HTML, Word ... README/index first
  code project     source files only: a "code book" of annotated listings
  single file      one document, split into chapters at its top headings
"""

import json
import os
import re
from pathlib import Path

import yaml

# Document formats book.py can read, by extension.
DOC_EXT = {
    ".md": "md", ".markdown": "md", ".mdown": "md", ".mkd": "md", ".mdx": "md",
    ".ipynb": "ipynb", ".qmd": "qmd", ".rmd": "rmd", ".rst": "rst", ".rest": "rst",
    ".html": "html", ".htm": "html", ".xhtml": "html", ".docx": "docx", ".odt": "odt",
    ".epub": "epub", ".tex": "latex", ".latex": "latex", ".ltx": "latex", ".org": "org",
    ".textile": "textile", ".wiki": "mediawiki", ".mediawiki": "mediawiki",
    ".dbk": "docbook", ".docbook": "docbook", ".rtf": "rtf", ".typ": "typst",
    ".adoc": "asciidoc", ".asciidoc": "asciidoc", ".txt": "text", ".pod": "text",
}

# Source files for code books, by extension (the value is the language
# name pandoc highlights; book.py checks it against pandoc's list).
CODE_EXT = {
    ".py": "python", ".pyi": "python", ".pyx": "python", ".js": "javascript",
    ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript", ".ts": "typescript",
    ".tsx": "typescript", ".java": "java", ".kt": "kotlin", ".kts": "kotlin",
    ".scala": "scala", ".go": "go", ".rs": "rust", ".c": "c", ".h": "c", ".cpp": "cpp",
    ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp", ".hxx": "cpp", ".cs": "cs",
    ".rb": "ruby", ".php": "php", ".swift": "swift", ".m": "objectivec", ".mm": "objectivec",
    ".r": "r", ".jl": "julia", ".lua": "lua", ".pl": "perl", ".pm": "perl", ".sh": "bash",
    ".bash": "bash", ".zsh": "zsh", ".fish": "bash", ".ps1": "powershell", ".sql": "sql",
    ".hs": "haskell", ".ex": "elixir", ".exs": "elixir", ".erl": "erlang", ".clj": "clojure",
    ".cljs": "clojure", ".ml": "ocaml", ".mli": "ocaml", ".fs": "fsharp", ".fsx": "fsharp",
    ".dart": "dart", ".vue": "html", ".svelte": "html", ".css": "css", ".scss": "scss",
    ".sass": "sass", ".less": "css", ".xml": "xml", ".json": "json", ".yaml": "yaml",
    ".yml": "yaml", ".toml": "toml", ".ini": "ini", ".cfg": "ini", ".gradle": "groovy",
    ".groovy": "groovy", ".cmake": "cmake", ".lisp": "commonlisp", ".el": "commonlisp",
    ".scm": "scheme", ".rkt": "scheme", ".v": "verilog", ".sv": "systemverilog",
    ".vhd": "vhdl", ".vhdl": "vhdl", ".asm": "nasm", ".s": "gnuassembler", ".f90": "fortran",
    ".f": "fortran", ".pas": "pascal", ".d": "d", ".nim": "nim", ".zig": "zig",
    ".proto": "protobuf", ".graphql": "graphql", ".tf": "hcl", ".nix": "nix",
    ".elm": "elm", ".coffee": "coffee", ".tcl": "tcl", ".awk": "awk", ".bat": "dosbat",
    ".cmd": "dosbat", ".vb": "vb", ".ada": "ada", ".adb": "ada", ".ads": "ada",
    ".sol": "solidity", ".prolog": "prolog", ".purs": "purescript", ".mk": "makefile",
}
CODE_NAMES = {"Makefile": "makefile", "makefile": "makefile", "GNUmakefile": "makefile",
              "Dockerfile": "dockerfile", "CMakeLists.txt": "cmake", "Rakefile": "ruby",
              "Gemfile": "ruby", "Vagrantfile": "ruby", "Jenkinsfile": "groovy",
              "Justfile": "makefile", "justfile": "makefile", "SConstruct": "python"}

SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".tox", ".nox", ".venv",
             "venv", "env", ".env", "build", "dist", "_build", "site", "_site", "_book",
             ".ipynb_checkpoints", ".pytest_cache", ".mypy_cache", ".ruff_cache", "target",
             ".idea", ".vscode", ".github", ".gitlab", ".circleci", "htmlcov", ".eggs",
             "_freeze", ".quarto", "out", "coverage", "vendor", "third_party", ".next",
             ".docusaurus", ".cache", "__snapshots__", "book-build"}
SKIP_FILES = {"package-lock.json", "yarn.lock", "poetry.lock", "uv.lock", "Cargo.lock",
              "pnpm-lock.yaml", "composer.lock", "Gemfile.lock", ".DS_Store"}

BACK_MATTER = re.compile(r"(^|/)(\d+[-_. ]*)?(changelog|changes|history|news|release[-_]?notes|license|"
                         r"licence|copying|authors|contributors|credits|contributing|"
                         r"code[-_]of[-_]conduct|security|support|faqs?|glossary|"
                         r"acknowledg(e)?ments?|thanks)$", re.I)
HTML_ONLY = re.compile(r"(^|/)(genindex|modindex|py-modindex|search|404|sitemap|tags?)$", re.I)


def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(s))]


def title_from_name(stem):
    s = re.sub(r"^\d+[\s._-]*", "", stem)
    s = re.sub(r"[-_]+", " ", s).strip()
    if not s:
        return stem
    return s[0].upper() + s[1:] if s.islower() or s.isupper() else s


def fmt_of(path):
    p = Path(path)
    if p.suffix.lower() in DOC_EXT:
        return DOC_EXT[p.suffix.lower()]
    if p.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "AUTHORS", "NOTICE")):
        return "text"
    return None


def code_language(path):
    p = Path(path)
    return CODE_NAMES.get(p.name) or CODE_EXT.get(p.suffix.lower())


# ---------------------------------------------------------------------------
# Titles without a full conversion
# ---------------------------------------------------------------------------

def first_heading_md(text):
    m = re.match(r"---\s*\n(.*?)\n(---|\.\.\.)\s*\n", text, re.S)
    if m:
        try:
            meta = yaml.safe_load(m.group(1)) or {}
            if isinstance(meta, dict) and meta.get("title"):
                return str(meta["title"])
        except Exception:
            pass
        text = text[m.end():]
    in_fence = False
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if re.match(r"^ {0,3}(```|~~~)", line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        h = re.match(r"^#{1,2}\s+(.+?)\s*#*\s*$", line)
        if h:
            return re.sub(r"\s*\{[^}]*\}\s*$", "", h.group(1)).strip()
        if i + 1 < len(lines) and line.strip() and re.fullmatch(r"=+\s*", lines[i + 1]):
            return line.strip()
    return None


RST_ADORN = re.compile(r"^([=\-~^\"'`#*+<>:._])\1{2,}\s*$")


def first_heading_rst(text):
    lines = text.split("\n")
    for i in range(len(lines) - 1):
        a, b = lines[i], lines[i + 1]
        if a.strip() and not a.startswith((" ", "..")) and RST_ADORN.match(b) and \
                len(b.strip()) >= len(a.strip()) - 2:
            return a.strip()
        if RST_ADORN.match(a) and b.strip() and i + 2 < len(lines) and RST_ADORN.match(lines[i + 2]):
            return b.strip()
    return None


def read_title(path):
    path = Path(path)
    fmt = fmt_of(path)
    try:
        if fmt in ("md", "qmd", "rmd"):
            return first_heading_md(path.read_text(errors="replace"))
        if fmt == "rst":
            return first_heading_rst(path.read_text(errors="replace"))
        if fmt == "ipynb":
            nb = json.loads(path.read_text(errors="replace"))
            for cell in nb.get("cells", []):
                if cell.get("cell_type") == "markdown":
                    src = "".join(cell.get("source", []))
                    t = first_heading_md(src)
                    if t:
                        return t
            return None
        if fmt == "html":
            text = path.read_text(errors="replace")
            m = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.S | re.I) or \
                re.search(r"<title>(.*?)</title>", text, re.S | re.I)
            return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else None
    except Exception:
        return None
    return None


def word_count_md(path):
    """Prose words, ignoring code, directives and markup (to spot pages that
    are only a logo and a table of contents)."""
    text = Path(path).read_text(errors="replace")
    text = re.sub(r"(?ms)^(```|~~~|:::).*?^\1", "", text)
    text = re.sub(r"(?ms)^\.\. \w[\w:-]*::.*?(?=^\S)", "", text + "\nx")
    text = re.sub(r"<[^>]+>|!\[[^\]]*\]\([^)]*\)|\[[^\]]*\]\([^)]*\)|\{[^}]*\}", " ", text)
    return len(re.findall(r"[A-Za-z]{2,}", text))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

class Proposal:
    def __init__(self, root, kind):
        self.root = Path(root)
        self.kind = kind
        self.meta = {}
        self.front, self.parts, self.appendix, self.notes = [], [], [], []

    def rel(self, path):
        try:
            return Path(path).resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return str(Path(path).resolve())

    def add_part(self, title, chapters):
        chapters = [c for c in chapters if c]
        if title:
            title = str(title).strip().rstrip(":").strip()
            if re.fullmatch(r"(table of )?contents|documentation|docs|index|chapters|pages|toc", title, re.I):
                title = None
        if chapters:
            self.parts.append({"title": title or None, "chapters": chapters})

    def to_config(self):
        cfg = {k: v for k, v in self.meta.items() if v}
        cfg["root"] = str(self.root)
        if self.front:
            cfg["front"] = self.front
        named = [p for p in self.parts if p["title"]]
        # a single part is no part at all, nor are parts of one chapter each
        if len(named) >= 2 and any(len(p["chapters"]) > 1 for p in named):
            cfg["parts"] = self.parts
        else:
            cfg["chapters"] = [c for p in self.parts for c in p["chapters"]]
        if self.appendix:
            cfg["appendix"] = self.appendix
        return cfg


def entry(prop, path, title=None, sections=None):
    e = {"path": prop.rel(path)}
    if title:
        e["title"] = title
    if sections:
        e["sections"] = [prop.rel(s) for s in sections]
    return e if len(e) > 1 else e["path"]


def resolve_doc(base, name, exts=(".md", ".ipynb", ".rst", ".qmd", ".Rmd", ".rmd", ".txt", ".html")):
    """A table-of-contents name (often without extension) -> existing file."""
    p = (Path(base) / name)
    if p.is_file():
        return p
    for ext in exts:
        q = p.with_name(p.name + ext) if not p.suffix or p.suffix.lower() not in DOC_EXT else p
        if q.is_file():
            return q
        q = Path(str(p) + ext)
        if q.is_file():
            return q
    if p.is_dir():
        for n in ("index", "README", "readme", "_index"):
            hit = resolve_doc(p, n, exts)
            if hit:
                return hit
    return None


def is_back_matter(path, title=""):
    stem = Path(path).with_suffix("").as_posix()
    return bool(BACK_MATTER.search(stem) or BACK_MATTER.search((title or "").replace(" ", "-")))


def split_back_matter(prop, chapters):
    """Move changelogs, licences and the like to the appendix."""
    keep = []
    for c in chapters:
        path = c if isinstance(c, str) else c.get("path", "")
        title = "" if isinstance(c, str) else c.get("title", "")
        if path and is_back_matter(path, title):
            prop.appendix.append(c)
        else:
            keep.append(c)
    return keep


# ---------------------------------------------------------------------------
# Jupyter Book
# ---------------------------------------------------------------------------

def jupyter_book(root):
    toc = yaml.safe_load((root / "_toc.yml").read_text()) or {}
    prop = Proposal(root, "Jupyter Book")
    cfg_path = root / "_config.yml"
    if cfg_path.exists():
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
        prop.meta["title"] = cfg.get("title")
        prop.meta["author"] = cfg.get("author")
        prop.meta["logo"] = None
        repo = (cfg.get("repository") or {}).get("url")
        if repo:
            branch = (cfg.get("repository") or {}).get("branch", "main")
            prop.meta["link_base"] = f"{repo.rstrip('/')}/blob/{branch}/"

    def file_entry(item):
        if not isinstance(item, dict) or "file" not in item:
            return None
        path = resolve_doc(root, item["file"])
        if not path:
            prop.notes.append(f"_toc.yml names {item['file']}, which does not exist")
            return None
        secs = []
        for s in item.get("sections", []) or []:
            sp = resolve_doc(root, s["file"]) if isinstance(s, dict) and "file" in s else None
            if sp:
                secs.append(sp)
                for ss in s.get("sections", []) or []:
                    ssp = resolve_doc(root, ss["file"]) if isinstance(ss, dict) and "file" in ss else None
                    if ssp:
                        secs.append(ssp)
        return entry(prop, path, item.get("title"), secs)

    if isinstance(toc, list):                     # legacy format
        items = toc
        if items and isinstance(items[0], dict) and "file" in items[0] and "part" not in items[0]:
            first = resolve_doc(root, items[0]["file"])
            if first:
                prop.front.append(entry(prop, first))
            items = items[1:]
        loose = []
        for it in items:
            if "part" in it:
                prop.add_part(it["part"], [file_entry(c) for c in it.get("chapters", [])])
            else:
                loose.append(file_entry(it))
        if loose:
            prop.add_part(None, loose)
    else:
        if toc.get("root"):
            first = resolve_doc(root, toc["root"])
            if first:
                t = read_title(first) or ""
                same = prop.meta.get("title") and t.strip().lower() == str(prop.meta["title"]).strip().lower()
                prop.front.append(entry(prop, first, "Preface" if same else None))
        for part in toc.get("parts", []) or []:
            cap = part.get("caption") or part.get("part")
            chapters = [file_entry(c) for c in part.get("chapters", []) or []]
            if cap and re.match(r"^\s*appendi(x|ces)\b", cap, re.I):
                prop.appendix.extend(c for c in chapters if c)
            else:
                prop.add_part(cap, chapters)
        chapters = [file_entry(c) for c in (toc.get("chapters") or toc.get("sections") or [])]
        if chapters:
            prop.add_part(None, chapters)
    for part in prop.parts:
        part["title"] = re.sub(r"^Part\s+[IVXLC\d]+\s*[-:–—.]\s*", "", part["title"] or "").strip() or None
    return prop


# ---------------------------------------------------------------------------
# Quarto and bookdown
# ---------------------------------------------------------------------------

def quarto_book(root):
    cfg = yaml.safe_load((root / "_quarto.yml").read_text()) or {}
    book = cfg.get("book") or {}
    prop = Proposal(root, "Quarto book")
    author = book.get("author")
    if isinstance(author, list):
        author = ", ".join(a.get("name", "") if isinstance(a, dict) else str(a) for a in author)
    elif isinstance(author, dict):
        author = author.get("name")
    prop.meta.update(title=book.get("title"), subtitle=book.get("subtitle"), author=author)
    if book.get("cover-image"):
        prop.meta["cover_image"] = book["cover-image"]
    for key in ("bibliography", "csl"):
        if cfg.get(key) or book.get(key):
            prop.meta[key] = cfg.get(key) or book.get(key)

    def items(lst):
        out = []
        for it in lst or []:
            if isinstance(it, str):
                p = resolve_doc(root, it)
                if p:
                    out.append(("ch", p, None))
            elif isinstance(it, dict) and "part" in it:
                title, intro = it["part"], None
                p = resolve_doc(root, title) if str(title).endswith((".qmd", ".md", ".Rmd", ".ipynb")) else None
                if p:
                    intro, title = p, read_title(p) or title_from_name(p.stem)
                out.append(("part", title, [x[1] for x in items(it.get("chapters"))], intro))
        return out

    chapters = items(book.get("chapters"))
    loose = []
    for i, it in enumerate(chapters):
        if it[0] == "ch":
            if i == 0 and it[1].stem == "index":
                prop.front.append(entry(prop, it[1]))
            else:
                loose.append(entry(prop, it[1]))
        else:
            if loose:
                prop.add_part(None, loose)
                loose = []
            prop.add_part(it[1], [entry(prop, p) for p in it[2]])
            if it[3]:
                prop.notes.append(f"part intro {prop.rel(it[3])} not included (add it if it has prose)")
    if loose:
        prop.add_part(None, loose)
    for it in items(book.get("appendices")):
        if it[0] == "ch":
            prop.appendix.append(entry(prop, it[1]))
    if (root / "_freeze").is_dir():
        prop.notes.append("found _freeze/: computed outputs from the last quarto render are used")
    else:
        prop.notes.append("no _freeze/ directory: code is shown without its output "
                          "(render once with `quarto render` and freeze: auto to include results)")
    return prop


def bookdown(root):
    prop = Proposal(root, "bookdown")
    files = None
    bd = root / "_bookdown.yml"
    if bd.exists():
        cfg = yaml.safe_load(bd.read_text()) or {}
        files = cfg.get("rmd_files")
        if isinstance(files, dict):
            files = files.get("latex") or files.get("html")
    if not files:
        files = sorted((p.name for p in root.glob("*.Rmd") if not p.name.startswith("_")), key=natural_key)
        if "index.Rmd" in files:
            files.remove("index.Rmd")
            files.insert(0, "index.Rmd")
    idx = root / "index.Rmd"
    if idx.exists():
        m = re.match(r"---\s*\n(.*?)\n---", idx.read_text(errors="replace"), re.S)
        if m:
            meta = yaml.safe_load(m.group(1)) or {}
            prop.meta.update(title=meta.get("title"), subtitle=meta.get("subtitle"),
                             author=", ".join(meta["author"]) if isinstance(meta.get("author"), list)
                             else meta.get("author"), bibliography=meta.get("bibliography"),
                             csl=meta.get("csl"))
    paths = [root / f for f in files if (root / f).exists()]
    if paths and paths[0].name == "index.Rmd":
        prop.front.append(entry(prop, paths[0]))
        paths = paths[1:]
    prop.add_part(None, [entry(prop, p) for p in paths])
    prop.notes.append("bookdown chunks are not run: code is shown without its output, and "
                      "'# (PART) Title {-}' headings in the files start parts only if you move them into book.yaml")
    return prop


# ---------------------------------------------------------------------------
# MkDocs
# ---------------------------------------------------------------------------

class _Loader(yaml.SafeLoader):
    pass


def _any_tag(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


_Loader.add_multi_constructor("!", _any_tag)
_Loader.add_multi_constructor("tag:yaml.org,2002:python/", _any_tag)


def mkdocs(root):
    cfg = yaml.load((root / "mkdocs.yml").read_text(), Loader=_Loader) or {}
    docs = root / cfg.get("docs_dir", "docs")
    prop = Proposal(docs, "MkDocs")
    prop.meta.update(title=cfg.get("site_name"), author=cfg.get("site_author"),
                     subtitle=cfg.get("site_description"))
    repo = cfg.get("repo_url")
    if repo and "github.com" in repo:
        m = re.match(r"(?:edit|blob)/([^/]+)/", str(cfg.get("edit_uri") or ""))
        prop.meta["link_base"] = repo.rstrip("/") + "/blob/" + (m.group(1) if m else "main") + "/"

    def walk(nav):
        out = []
        for it in nav or []:
            if isinstance(it, str):
                p = resolve_doc(docs, it)
                if p:
                    out.append(("ch", p, None))
            elif isinstance(it, dict):
                for title, val in it.items():
                    if isinstance(val, str):
                        if re.match(r"^https?://", val):
                            continue
                        p = resolve_doc(docs, val)
                        if p:
                            out.append(("ch", p, title))
                    elif isinstance(val, list):
                        out.append(("sec", title, walk(val)))
        return out

    nav = walk(cfg.get("nav"))
    if not nav:
        return docs_folder(docs, prop)
    loose = []
    for i, it in enumerate(nav):
        if it[0] == "ch":
            if not prop.front and i == 0 and it[1].stem.lower() in ("index", "readme"):
                prop.front.append(entry(prop, it[1], "Introduction" if (it[2] or "").lower() in ("home", "") else it[2]))
            else:
                loose.append(entry(prop, it[1], it[2]))
        else:
            if loose:
                prop.add_part(None, loose)
                loose = []
            chapters = []
            for sub in it[2]:
                if sub[0] == "ch":
                    chapters.append(entry(prop, sub[1], sub[2]))
                else:                                     # deeper nesting: a chapter with sections
                    files = [s[1] for s in flatten(sub[2])]
                    if files:
                        chapters.append({"path": prop.rel(files[0]), "title": sub[1],
                                         "sections": [prop.rel(f) for f in files[1:]]}
                                        if len(files) > 1 else entry(prop, files[0], sub[1]))
            prop.add_part(it[1], chapters)
    if loose:
        prop.add_part(None, loose)
    for part in prop.parts:
        part["chapters"] = split_back_matter(prop, part["chapters"])
    prop.parts = [p for p in prop.parts if p["chapters"]]
    return prop


def flatten(items):
    for it in items:
        if it[0] == "ch":
            yield it
        else:
            yield from flatten(it[2])


# ---------------------------------------------------------------------------
# mdBook, GitBook
# ---------------------------------------------------------------------------

def summary_md(root, summary):
    prop = Proposal(summary.parent, "mdBook/GitBook")
    toml = root / "book.toml"
    if toml.exists():
        text = toml.read_text()
        for key in ("title", "description"):
            m = re.search(rf'^{key}\s*=\s*"(.*)"', text, re.M)
            if m:
                prop.meta["title" if key == "title" else "subtitle"] = m.group(1)
        m = re.search(r'^authors\s*=\s*\[(.*?)\]', text, re.M | re.S)
        if m:
            prop.meta["author"] = ", ".join(re.findall(r'"([^"]+)"', m.group(1)))
    bj = root / "book.json"
    if bj.exists():
        try:
            data = json.loads(bj.read_text())
            prop.meta.update(title=data.get("title"), author=data.get("author"))
        except Exception:
            pass
    part, chapters, seen_numbered = None, [], False
    current = None
    for line in summary.read_text(errors="replace").split("\n"):
        h = re.match(r"^#{1,3}\s+(.+?)\s*$", line)
        if h and not re.match(r"^#\s*summary\s*$", line, re.I):
            if chapters:
                prop.add_part(part, chapters)
            part, chapters, current = h.group(1).strip(), [], None
            continue
        m = re.match(r"^(\s*)([-*+]|\d+\.)?\s*\[([^\]]+)\]\(([^)]*)\)", line)
        if not m or not m.group(4) or m.group(4).startswith("http"):
            continue
        indent, bullet, title, target = len(m.group(1).expandtabs(4)), m.group(2), m.group(3), m.group(4)
        p = resolve_doc(summary.parent, target.split("#")[0])
        if not p:
            continue
        if not bullet:                                     # prefix/suffix chapters
            (prop.appendix if seen_numbered else prop.front).append(entry(prop, p, title))
            continue
        seen_numbered = True
        if indent == 0 or current is None:
            current = {"path": prop.rel(p), "title": title}
            chapters.append(current)
        else:
            current.setdefault("sections", []).append(prop.rel(p))
    if chapters:
        prop.add_part(part, chapters)
    return prop


# ---------------------------------------------------------------------------
# Sphinx
# ---------------------------------------------------------------------------

def conf_value(text, name):
    m = re.search(rf"^{name}\s*=\s*(['\"])(.*?)\1", text, re.M)
    if m:
        return m.group(2)
    m = re.search(rf"^{name}\s*=\s*f?(['\"])(.*?)\1", text, re.M)
    return m.group(2) if m else None


TOCTREE_RST = re.compile(r"^\.\. toctree::[ \t]*\n((?:[ \t]+.*\n|[ \t]*\n)*)", re.M)
TOCTREE_MYST = re.compile(r"^(```|:::)\{toctree\}[^\n]*\n(.*?)^\1\s*$", re.M | re.S)


HEADING_MD = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.M)
HEADING_RST = re.compile(r"^([^\s.][^\n]*)\n([=\-~^\"'`#*+])\2{2,}\s*$", re.M)


def heading_before(text, pos, since):
    """The last heading between `since` and `pos` (a toctree's caption when
    it has no :caption: option, as in many projects' index pages)."""
    hits = [(m.start(), m.group(1)) for m in HEADING_MD.finditer(text, since, pos)]
    hits += [(m.start(), m.group(1)) for m in HEADING_RST.finditer(text, since, pos)]
    return re.sub(r"\s*\{[^}]*\}\s*$", "", max(hits)[1]).strip() if hits else None


def toctrees(path):
    """[(caption, [entries])] for the toctrees of a Sphinx document."""
    text = path.read_text(errors="replace")
    found = []
    for m in TOCTREE_RST.finditer(text + "\n"):
        found.append((m.start(), "rst", m))
    for m in TOCTREE_MYST.finditer(text):
        found.append((m.start(), "myst", m))
    found.sort(key=lambda x: x[0])
    out, since = [], 0
    for start, kind, m in found:
        caption, items = parse_toctree(kind, m)
        caption = caption or heading_before(text, start, since)
        since = m.end()
        out.append((caption, items))
    return out


def parse_toctree(kind, m):
    if kind == "rst":
        caption, items = None, []
        for line in m.group(1).split("\n"):
            s = line.strip()
            if not s:
                continue
            o = re.match(r"^:(\w[\w-]*):\s*(.*)$", s)
            if o:
                if o.group(1) == "caption":
                    caption = o.group(2)
                continue
            items.append(s)
        return caption, items
    caption, items = None, []
    if True:
        for line in m.group(2).split("\n"):
            s = line.strip()
            if not s or s == "---":
                continue
            o = re.match(r"^:?(\w[\w-]*):\s*(.*)$", s)
            if o and not s.endswith((".md", ".rst", ".ipynb")) and "/" not in o.group(1) and \
                    o.group(1) in ("caption", "maxdepth", "hidden", "glob", "titlesonly", "numbered",
                                   "name", "reversed", "includehidden"):
                if o.group(1) == "caption":
                    caption = o.group(2)
                continue
            items.append(s)
    return caption, items


def toc_target(base_dir, srcdir, item):
    m = re.match(r"^(.*?)\s*<([^>]+)>$", item)
    title, target = (m.group(1), m.group(2)) if m else (None, item)
    if target.startswith(("http://", "https://")) or target == "self":
        return None, None
    base = srcdir if target.startswith("/") else base_dir
    if "*" in target:
        return title, sorted(base.glob(target.lstrip("/") + "*"), key=natural_key)
    return title, resolve_doc(base, target.lstrip("/"))


def sphinx(conf):
    srcdir = conf.parent
    text = conf.read_text(errors="replace")
    prop = Proposal(srcdir, "Sphinx")
    prop.meta["title"] = conf_value(text, "project")
    prop.meta["author"] = conf_value(text, "author")
    cr = conf_value(text, "copyright")
    if cr:
        prop.meta["copyright"] = "Copyright © " + cr.replace("%Y", "")
    root_name = conf_value(text, "root_doc") or conf_value(text, "master_doc") or "index"
    root_doc = resolve_doc(srcdir, root_name)
    if not root_doc:
        return docs_folder(srcdir, prop)
    if word_count_md(root_doc) >= 40:
        prop.front.append(entry(prop, root_doc, "Introduction"))
    seen = {root_doc.resolve()}

    def sub_sections(path, depth=0):
        found = []
        if depth > 2:
            return found
        for _cap, items in toctrees(path):
            for it in items:
                _t, target = toc_target(path.parent, srcdir, it)
                for p in (target if isinstance(target, list) else [target]):
                    if p and p.resolve() not in seen and not HTML_ONLY.search(p.with_suffix("").as_posix()):
                        seen.add(p.resolve())
                        found.append(p)
                        found.extend(sub_sections(p, depth + 1))
        return found

    for caption, items in toctrees(root_doc):
        chapters = []
        for it in items:
            title, target = toc_target(root_doc.parent, srcdir, it)
            for p in (target if isinstance(target, list) else [target]):
                if not p or p.resolve() in seen or HTML_ONLY.search(p.with_suffix("").as_posix()):
                    continue
                seen.add(p.resolve())
                secs = sub_sections(p)
                chapters.append(entry(prop, p, title, secs))
        chapters = split_back_matter(prop, chapters)
        prop.add_part(caption, chapters)
    if not prop.parts:
        return docs_folder(srcdir, prop)
    myst = re.search(r"myst_parser|myst_nb|sphinx_design", text)
    if myst:
        prop.meta["myst"] = True
    roots = [r for r in (srcdir.parent / "src", srcdir.parent) if r.is_dir()]
    prop.meta["code_roots"] = [os.path.relpath(r, srcdir) for r in roots]
    return prop


# ---------------------------------------------------------------------------
# A folder of documents, or of code
# ---------------------------------------------------------------------------

def walk_files(base, want):
    out = []
    for p in sorted(base.rglob("*"), key=lambda q: natural_key(q.relative_to(base))):
        rel = p.relative_to(base)
        if any(part in SKIP_DIRS or part.startswith(".") for part in rel.parts[:-1]):
            continue
        if p.is_file() and not p.name.startswith(".") and p.name not in SKIP_FILES and want(p):
            out.append(p)
    return out


def front_sort(paths):
    """README/index first in each folder."""
    def key(p):
        lead = p.stem.lower() in ("readme", "index", "_index", "intro", "introduction", "preface")
        return (natural_key(p.parent), 0 if lead else 1, natural_key(p.name))
    return sorted(paths, key=key)


def docs_folder(base, prop=None):
    base = Path(base)
    prop = prop or Proposal(base, "docs folder")
    prop.kind = "docs folder"
    docs = [p for p in walk_files(base, lambda p: fmt_of(p) in ("md", "ipynb", "rst", "qmd", "rmd",
                                                                   "html", "docx", "odt", "tex", "latex",
                                                                   "org", "textile", "adoc", "asciidoc"))]
    docs = [p for p in docs if not HTML_ONLY.search(p.with_suffix("").as_posix())]
    docs = front_sort(docs)
    if not docs:
        return prop
    groups = {}
    for p in docs:
        groups.setdefault(p.parent, []).append(p)
    top = groups.pop(base, [])
    if top and top[0].stem.lower() in ("readme", "index", "_index", "intro", "introduction", "preface"):
        prop.front.append(entry(prop, top[0], None if top[0].stem.lower() not in ("readme", "index", "_index")
                                else "Introduction"))
        top = top[1:]
    prop.add_part(None, split_back_matter(prop, [entry(prop, p) for p in top]))
    for folder, files in sorted(groups.items(), key=lambda kv: natural_key(kv[0])):
        intro = files[0] if files[0].stem.lower() in ("readme", "index", "_index") else None
        title = (read_title(intro) if intro else None) or title_from_name(folder.name)
        chapters = [entry(prop, p) for p in files]
        prop.add_part(title, split_back_matter(prop, chapters))
    if all(len(p["chapters"]) == 1 for p in prop.parts if p["title"]):
        flat = [c for p in prop.parts for c in p["chapters"]]
        prop.parts = []
        prop.add_part(None, flat)
    return prop


def code_book(base):
    base = Path(base)
    prop = Proposal(base, "code book")
    files = walk_files(base, lambda p: bool(code_language(p)))
    files = [p for p in files if p.stat().st_size < 400_000]
    readme = next((base / n for n in ("README.md", "README.rst", "README.txt", "README", "readme.md")
                   if (base / n).exists()), None)
    if readme:
        prop.front.append(entry(prop, readme, "Introduction"))
    dirs = {}
    for p in files:
        dirs.setdefault(p.parent, []).append(p)
    tests, main, config = [], [], []
    for d in sorted(dirs, key=natural_key):
        rel = prop.rel(d) if d != base else "."
        title = rel if rel != "." else "Top-level files"
        e = {"code": rel, "title": title}
        if re.search(r"(^|/)(tests?|testing|specs?|__tests__)(/|$)", rel):
            tests.append(e)
        elif d == base and all(code_language(p) in ("yaml", "toml", "ini", "json", "makefile",
                                                      "dockerfile", "cmake") for p in dirs[d]):
            config.append(e)
        else:
            main.append(e)
    name = project_name(base) or base.name
    main.sort(key=lambda e: (e["code"].split("/")[0].lower() != name.lower().replace("-", "_")
                             and e["code"].split("/")[0].lower() != name.lower(), natural_key(e["code"])))
    prop.add_part("Source", main)
    prop.add_part("Tests", tests)
    if config:
        prop.appendix.extend(config)
    for lic in ("LICENSE", "LICENSE.txt", "LICENSE.md", "LICENCE", "COPYING"):
        if (base / lic).exists():
            prop.appendix.append(entry(prop, base / lic, "License"))
            break
    pj = base / "pyproject.toml"
    if pj.exists():
        t = pj.read_text(errors="replace")
        m = re.search(r'^name\s*=\s*"([^"]+)"', t, re.M)
        d = re.search(r'^description\s*=\s*"([^"]+)"', t, re.M)
        a = re.search(r'^authors\s*=\s*\[(.*?)\]', t, re.M | re.S)
        names = re.findall(r'name\s*=\s*"([^"]+)"', a.group(1)) if a else []
        prop.meta.update(title=m.group(1) if m else None, subtitle=d.group(1) if d else None,
                         author=", ".join(names) or None)
    sc = base / "setup.cfg"
    if sc.exists():
        t = sc.read_text(errors="replace")
        for key, field in (("name", "title"), ("description", "subtitle"), ("author", "author")):
            m = re.search(rf"^{key}\s*=\s*(.+)$", t, re.M)
            if m and not prop.meta.get(field):
                prop.meta[field] = m.group(1).strip()
    pk = base / "package.json"
    if pk.exists():
        try:
            data = json.loads(pk.read_text())
            prop.meta.update(title=data.get("name"), subtitle=data.get("description"),
                             author=data.get("author") if isinstance(data.get("author"), str) else None)
        except Exception:
            pass
    prop.meta.setdefault("title", base.name)
    if not prop.meta.get("title"):
        prop.meta["title"] = base.name
    prop.meta["code_book"] = True
    return prop


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def project_name(base):
    for f, pat in (("pyproject.toml", r'^name\s*=\s*"([^"]+)"'), ("setup.cfg", r"^name\s*=\s*(\S+)"),
                   ("package.json", r'"name"\s*:\s*"([^"]+)"'), ("Cargo.toml", r'^name\s*=\s*"([^"]+)"')):
        p = Path(base) / f
        if p.exists():
            m = re.search(pat, p.read_text(errors="replace"), re.M)
            if m:
                return m.group(1)
    return None


def find_docs_root(base):
    for name in ("docs", "doc", "documentation", "book", "manual", "guide", "site-src"):
        d = base / name
        if d.is_dir():
            return d
    return None


MARKERS = ("_toc.yml", "_quarto.yml", "_bookdown.yml", "mkdocs.yml", "book.toml", "SUMMARY.md", "conf.py")


def marked_dirs(src, depth=2):
    """Folders below src (shallowest first) that hold a book or site config."""
    found = []
    for d in sorted((p for p in src.rglob("*") if p.is_dir()), key=lambda p: (len(p.parts), str(p))):
        rel = d.relative_to(src).parts
        if len(rel) > depth or any(part in SKIP_DIRS or part.startswith(".") for part in rel):
            continue
        if any((d / m).exists() for m in MARKERS):
            found.append(d)
    return found


def propose(source):
    src = Path(source).resolve()
    if src.is_file():
        prop = Proposal(src.parent, "single file")
        prop.parts = [{"title": None, "chapters": [{"path": src.name, "split": True}]}]
        prop.meta["title"] = read_title(src) or title_from_name(src.stem)
        prop.notes.append("the file is split into chapters at its top-level headings; "
                          "headings that start with 'Part' become parts, 'Appendix' ones appendices")
        return prop
    for base in [src] + [d for d in [find_docs_root(src)] if d] + marked_dirs(src):
        if (base / "_toc.yml").exists():
            return jupyter_book(base)
        q = base / "_quarto.yml"
        if q.exists() and re.search(r"type:\s*book", q.read_text(errors="replace")):
            return quarto_book(base)
        if (base / "_bookdown.yml").exists() or (base / "index.Rmd").exists():
            return bookdown(base)
        if (base / "mkdocs.yml").exists():
            return mkdocs(base)
        for s in (base / "src" / "SUMMARY.md", base / "SUMMARY.md"):
            if s.exists():
                return summary_md(base, s)
    for conf in [src / "conf.py", src / "docs" / "conf.py", src / "doc" / "conf.py",
                 src / "docs" / "source" / "conf.py", src / "doc" / "source" / "conf.py",
                 src / "source" / "conf.py"] + [d / "conf.py" for d in marked_dirs(src)]:
        if conf.exists() and re.search(r"^(project|extensions|html_theme)\s*=", conf.read_text(errors="replace"), re.M):
            return sphinx(conf)
    docs_root = find_docs_root(src)
    if docs_root and walk_files(docs_root, lambda p: fmt_of(p) in ("md", "rst", "ipynb", "qmd", "html")):
        return docs_folder(docs_root)
    docs = walk_files(src, lambda p: fmt_of(p) in ("md", "rst", "ipynb", "qmd", "rmd", "docx", "tex", "html")
                      and not PROJECT_FILES.match(p.stem))
    code = walk_files(src, lambda p: bool(code_language(p)) and code_language(p) not in
                      ("yaml", "toml", "ini", "json", "xml"))
    if docs and len(docs) * 3 >= len(code):
        return docs_folder(src)
    return code_book(src)


# Files every repository has; they do not make a folder a documentation set.
PROJECT_FILES = re.compile(r"^(readme|license|licence|copying|notice|authors|contributors|maintainers|"
                           r"changelog|changes|history|news|contributing|code_of_conduct|security|"
                           r"support|governance|citation|funding)([-_.].*)?$", re.I)

"""Text-level preparation of Markdown (CommonMark, GFM, MyST, Quarto, R
Markdown, Jupyter) and reStructuredText before pandoc parses them.

pandoc reads plain Markdown and core reStructuredText well; what it does not
know are the extensions documentation sites are written in: MyST and Sphinx
directives and roles, Jupyter's MathJax habits, Quarto chunks, GitHub
alerts.  This module rewrites those into constructs pandoc understands:

  * admonitions and other block directives  -> fenced divs  ::: {.name arg="..."}
  * roles ({func}`x`, :ref:`y`)              -> `x`{.interpreted-text role="func"}
  * code-like directives                      -> fenced code blocks
  * images and figures                        -> ![alt](src){width=...}
  * maths the MathJax way                     -> $...$ / $$...$$ that TeX accepts

postprocess.py then turns the divs and roles into book elements.
"""

import csv
import io
import re
from pathlib import Path

# MyST/Sphinx admonition-like directives; the value is the default label.
ADMONITIONS = {
    "note": "Note", "tip": "Tip", "hint": "Hint", "important": "Important",
    "warning": "Warning", "caution": "Caution", "attention": "Attention",
    "danger": "Danger", "error": "Error", "seealso": "See also", "todo": "To do",
    "admonition": "Note", "versionadded": "New in version", "versionchanged":
    "Changed in version", "deprecated": "Deprecated since version",
    "versionremoved": "Removed in version", "sidebar": "Sidebar", "topic": "Topic",
    "margin": "Note", "important-note": "Important",
    # Material for MkDocs, Docusaurus, VitePress
    "abstract": "Abstract", "summary": "Summary", "tldr": "TL;DR", "info": "Info",
    "success": "Success", "check": "Check", "done": "Done", "question": "Question",
    "help": "Help", "faq": "FAQ", "failure": "Failure", "fail": "Failure",
    "missing": "Missing", "bug": "Bug", "example": "Example", "quote": "Quote",
    "cite": "Quote", "details": "Details", "secondary": "Note", "callout": "Note",
}
# Kinds whose directive argument is a title rather than the first line of text.
TITLED = {"admonition", "sidebar", "topic", "details", "dropdown"}
# Directives that only steer the HTML build.
DROP = {"toctree", "contents", "tableofcontents", "index", "highlight", "currentmodule",
        "module", "default-role", "default-domain", "sectionauthor", "codeauthor", "meta",
        "testsetup", "testcleanup", "tabularcolumns", "py:currentmodule", "py:module",
        "autosummary", "jupyter-kernel", "raw", "plot-directive-options", "title"}
# Directives whose body is code.
CODE = {"code-block": None, "code": None, "sourcecode": None, "code-cell": None,
        "testcode": "python", "doctest": "pycon", "ipython": "python",
        "jupyter-execute": "python", "parsed-literal": "plain", "prompt": "bash",
        "mermaid": "plain", "graphviz": "dot", "dot": "dot", "plantuml": "plain",
        "testoutput": "plain"}
AUTODOC = {"autoobject", "automodule", "autoclass", "autofunction", "automethod", "autoattribute",
           "autodata", "autoexception", "autoproperty", "autodecorator",
           "py:function", "py:class", "py:method", "py:attribute", "py:data",
           "py:exception", "function", "class", "method", "attribute", "data",
           "exception", "decorator", "property"}
# Containers whose content is kept as it is (tabs, cards, grids ...).
UNWRAP = {"only", "ifconfig", "container", "div", "tab-set", "tab-item", "tabs", "tab",
          "grid", "grid-item", "grid-item-card", "card", "card-carousel", "dropdown",
          "centered", "hlist", "rst-class", "cssclass", "table", "glossary",
          "epigraph", "pull-quote", "highlights", "compound", "line-block",
          "list-table-wrapper", "admonition-group"}

FENCE = re.compile(r"^(?P<indent> {0,3})(?P<fence>`{3,}|~{3,}|:{3,})(?P<info>.*)$")


# ---------------------------------------------------------------------------
# Fences
# ---------------------------------------------------------------------------

def split_fences(text):
    """Split Markdown into runs: (None, text) for prose, or (fence_match,
    lines) for a fenced block (backticks, tildes or MyST colon fences)."""
    runs, buf = [], []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        m = FENCE.match(lines[i])
        colon = m and m.group("fence")[0] == ":"
        if m and (not colon or re.match(r"\s*\{", m.group("info") or "")):
            if buf:
                runs.append((None, "\n".join(buf)))
                buf = []
            fence = m.group("fence")
            body, j, depth = [], i + 1, 0
            while j < len(lines):
                mm = FENCE.match(lines[j])
                if mm and mm.group("fence")[0] == fence[0]:
                    info = mm.group("info").strip()
                    if not info and len(mm.group("fence")) >= len(fence) and depth == 0:
                        break
                    if colon and info.startswith("{"):
                        depth += 1                   # nested colon fence
                    elif colon and not info and depth:
                        depth -= 1
                body.append(lines[j])
                j += 1
            runs.append((m, body))
            i = j + 1
            continue
        buf.append(lines[i])
        i += 1
    if buf:
        runs.append((None, "\n".join(buf)))
    return runs


def fence(text, info=""):
    f = "```"
    while f in text:
        f += "`"
    return f"{f}{info}\n{text}\n{f}"


def parse_directive_options(body):
    """MyST options: leading ':key: value' lines, or a '---' YAML block."""
    opts, i = {}, 0
    if body and body[0].strip() == "---":
        j = 1
        while j < len(body) and body[j].strip() != "---":
            m = re.match(r"\s*([\w-]+)\s*:\s*(.*)$", body[j])
            if m:
                opts[m.group(1)] = m.group(2).strip().strip("'\"")
            j += 1
        return opts, body[j + 1:]
    while i < len(body):
        m = re.match(r"\s*:([\w-]+):\s*(.*)$", body[i])
        if not m:
            break
        opts[m.group(1)] = m.group(2).strip()
        i += 1
    if i < len(body) and not body[i].strip():
        i += 1
    return opts, body[i:]


# ---------------------------------------------------------------------------
# Maths
# ---------------------------------------------------------------------------

def tokenize_math(par, warn, strict=False):
    """Split a paragraph into text and maths tokens (MathJax-style dollars).

    strict: pandoc's rule for inline maths ($ followed by a non-space, closed
    by a $ after a non-space and before no digit), so that "$HOME and $PATH"
    stay text.  Notebooks are lenient, as MathJax is ("$ x $")."""
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
            bad = k < 0 or (not display and par.startswith("$$", k) and k == i + 1)
            if not bad and strict and not display:
                body = par[i + 1:k]
                bad = (not body or body[0].isspace() or body[-1].isspace()
                       or (k + 1 < n and par[k + 1].isdigit()))
            if bad:
                # not maths: a price, a shell variable, or a typo
                if not re.match(r"\$\s?[\d(]|\$[A-Za-z_{]", par[i:i + 3]):
                    warn(f"unmatched $ kept as text in: {par[max(0, i - 40):i + 40]!r}")
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
    """MathJax lets align & co. sit inside $$; in TeX they become aligned.
    MathJax-only commands are removed."""
    body = body.strip()
    body = re.sub(r"\\(begin|end)\{(align|gather)\*?\}", r"\\\1{\2ed}", body)
    body = re.sub(r"\\(begin|end)\{(eqnarray|split)\*?\}", r"\\\1{aligned}", body)
    body = re.sub(r"\\(begin|end)\{equation\*?\}", "", body)
    body = re.sub(r"\\require\{[^}]*\}", "", body)
    body = re.sub(r"\\(nonumber|notag)\b", "", body)
    body = re.sub(r"\\(class|cssId|style)\{[^}]*\}", "", body)
    return body.strip()


CURRENCY_BR = re.compile(r"(?<![A-Za-z\\$])R\$(?=\s?\d)|(?<=\d )R\$")
LABELLED = re.compile(r"\$\$\s*\(([\w:.-]+)\)[ \t]*$", re.M)


def normalize_math(text, warn, strict=False):
    """Make MathJax-style maths acceptable to pandoc and TeX.

    Jupyter accepts "$ x $" and "$" alone on a line around a display; pandoc
    needs "$x$" and "$$...$$".  A paragraph made only of maths is a display.
    Prices ("R$ 6.52") are not maths.
    """
    text = CURRENCY_BR.sub(r"R\\$", text)
    text = LABELLED.sub(lambda m: f"\\label{{{m.group(1)}}}$$", text)   # MyST "$$ ... $$ (label)"
    pieces = re.split(r"(\n[ \t]*\n)", text)
    out = []
    for par in pieces:
        if not par.strip() or re.fullmatch(r"\n[ \t]*\n", par) or "$" not in par:
            out.append(par)
            continue
        tokens = tokenize_math(par, warn, strict)
        math_only = all(t == "text" and not v.strip() or t != "text" for t, v in tokens) \
            and any(t != "text" for t, _ in tokens)
        res = []
        for kind, val in tokens:
            if kind == "text":
                res.append(val)
                continue
            body = fix_math_body(val)
            if not body:
                continue
            res.append(("$$" + body + "$$") if (math_only or kind == "display") else ("$" + body + "$"))
        out.append("".join(res))
    return "".join(out)


BARE_ENV = re.compile(r"(?ms)^(\\begin\{(align|align\*|equation|equation\*|gather|gather\*|"
                      r"multline|multline\*|eqnarray|eqnarray\*)\}.*?\\end\{\2\})[ \t]*$")


def wrap_bare_environments(text):
    """MyST's amsmath extension allows bare \\begin{align} blocks (but many
    notebooks put the same environments inside $$ ... $$: leave those)."""
    def repl(m):
        if text[:m.start()].rstrip().endswith("$$") or text[m.end():].lstrip().startswith("$$"):
            return m.group(0)
        return "$$" + m.group(1) + "$$"
    return BARE_ENV.sub(repl, text)


# ---------------------------------------------------------------------------
# Roles and small inline rewrites
# ---------------------------------------------------------------------------

MYST_ROLE = re.compile(r"\{(?P<role>[\w:+-]+)\}`(?P<body>[^`]+)`")


def convert_myst_roles(text):
    def repl(m):
        role, body = m.group("role"), m.group("body")
        if role == "math":
            return f"${body}$"
        body_esc = body.replace('"', "&quot;")
        return f"`{body}`{{.interpreted-text role=\"{role}\"}}" if "`" not in body else body_esc
    return MYST_ROLE.sub(repl, text)


HTML_IMG = re.compile(r"<img\s+([^>]*?)/?>", re.I | re.S)
HTML_ATTR = re.compile(r"([\w-]+)\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)")


def html_img_to_md(m):
    attrs = {k.lower(): v.strip("\"'") for k, v in HTML_ATTR.findall(m.group(1))}
    src = attrs.get("src")
    if not src:
        return ""
    alt = attrs.get("alt", "").replace("]", "")
    kv = []
    for key in ("width", "height"):
        v = attrs.get(key)
        if v:
            if re.fullmatch(r"\d+(\.\d+)?", v):
                v += "px"
            kv.append(f"{key}={v}")
    return f"![{alt}]({src})" + ("{" + " ".join(kv) + "}" if kv else "")


GH_ALERT = re.compile(r"^> \[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t]*\n((?:>.*(?:\n|$))*)", re.M)


def convert_alerts(text):
    def repl(m):
        body = re.sub(r"^> ?", "", m.group(2), flags=re.M)
        return f"::: {{.{m.group(1).lower()}}}\n{body}\n:::\n"
    return GH_ALERT.sub(repl, text)


QUARTO_XREF = re.compile(r"(?<![\w@\[])@((?:sec|fig|tbl|eq|lst|thm|lem|cor|prp|cnj|def|exm|exr|sol|rem)-[\w-]*\w)")
BOOKDOWN_XREF = re.compile(r"\\@ref\(([\w:.-]+)\)")


def quarto_xrefs(text):
    """Quarto's @sec-x and bookdown's \\@ref(x): cross-references, not citations."""
    text = QUARTO_XREF.sub(lambda m: f"[](#{m.group(1)}){{.book-xref}}", text)
    return BOOKDOWN_XREF.sub(lambda m: f"[](#{m.group(1).split(':', 1)[-1]}){{.book-xref}}", text)


def prose_rewrites(text, myst, quarto=False):
    """Rewrites for prose runs (outside code fences)."""
    if quarto:
        text = quarto_xrefs(text)
    text = text.replace("\r\n", "\n").replace("\ufeff", "")
    for ch in "\u202a\u202b\u202c\u202d\u202e\u200e\u200f":
        text = text.replace(ch, "")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = HTML_IMG.sub(html_img_to_md, text)
    # wrappers that only centre or align things in HTML
    text = re.sub(r"</?(center|font)[^>]*>", "", text, flags=re.I)
    text = re.sub(r"<(p|div)\s+align=[\"']?\w+[\"']?\s*>", "", text, flags=re.I)
    text = re.sub(r"<summary>(.*?)</summary>", r"**\1**", text, flags=re.I | re.S)
    text = re.sub(r"</?details[^>]*>", "", text, flags=re.I)
    text = re.sub(r"<kbd>(.*?)</kbd>", r"`\1`", text, flags=re.I)
    text = convert_alerts(text)
    if myst:
        text = re.sub(r"^%.*$\n?", "", text, flags=re.M)                 # comments
        text = re.sub(r"^\{[.#][^}\n]*\}[ \t]*$\n?", "", text, flags=re.M)  # attribute lines
        # (label)= targets become the next heading's identifier
        text = re.sub(r"^\(([\w:.-]+)\)=[ \t]*\n+(#+ .*?)[ \t]*$",
                      lambda m: f"{m.group(2)} {{#{m.group(1)}}}", text, flags=re.M)
        text = re.sub(r"^\([\w:.-]+\)=[ \t]*$\n?", "", text, flags=re.M)
        text = convert_myst_roles(text)
    return text


# ---------------------------------------------------------------------------
# Front matter
# ---------------------------------------------------------------------------

def split_front_matter(text):
    import yaml
    if not text.startswith("---"):
        return {}, text
    m = re.match(r"---[ \t]*\n(.*?)\n(---|\.\.\.)[ \t]*(\n|$)", text, re.S)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except Exception:
        return {}, text
    return (meta if isinstance(meta, dict) else {}), text[m.end():]


# ---------------------------------------------------------------------------
# MyST directives
# ---------------------------------------------------------------------------

def size_attr(opts):
    kv = []
    for key in ("width", "height", "scale"):
        if key in opts and opts[key]:
            v = opts[key].strip()
            if re.fullmatch(r"\d+(\.\d+)?", v):
                v += "px"
            kv.append(f"{key}={v}")
    return kv


def read_include(path, opts):
    text = path.read_text(errors="replace")
    if "start-after" in opts:
        k = text.find(opts["start-after"])
        if k >= 0:                          # keep what follows the marker's line
            text = text[k + len(opts["start-after"]):].split("\n", 1)[-1]
    if "end-before" in opts:
        k = text.find(opts["end-before"])
        if k >= 0:
            text = text[:k]
    if "lines" in opts:
        keep = []
        all_lines = text.split("\n")
        for part in opts["lines"].split(","):
            part = part.strip()
            if "-" in part:
                a, b = part.split("-", 1)
                a = int(a or 1)
                b = int(b) if b else len(all_lines)
                keep.extend(all_lines[a - 1:b])
            elif part.isdigit():
                keep.append(all_lines[int(part) - 1])
        text = "\n".join(keep)
    if "dedent" in opts:
        import textwrap
        text = textwrap.dedent(text)
    return text.strip("\n")


def list_table_to_md(body):
    """MyST list-table (a list of lists) as a pipe table."""
    rows, cur = [], None
    for line in body:
        m1 = re.match(r"^\*\s+-\s+(.*)$", line) or re.match(r"^-\s+-\s+(.*)$", line)
        m2 = re.match(r"^\s{2,}-\s+(.*)$", line)
        if m1:
            cur = [m1.group(1).strip()]
            rows.append(cur)
        elif m2 and cur is not None:
            cur.append(m2.group(1).strip())
        elif line.strip() and cur:
            cur[-1] += " " + line.strip()
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    esc = lambda c: c.replace("|", "\\|")
    out = ["| " + " | ".join(esc(c) for c in rows[0]) + " |",
           "|" + "---|" * width]
    out += ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows[1:]]
    return "\n".join(out)


def csv_table_to_md(text, header_rows=1):
    rows = list(csv.reader(io.StringIO(text.strip()), skipinitialspace=True))
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    if header_rows == 0:
        rows = [[""] * width] + rows
    esc = lambda c: c.replace("|", "\\|").strip()
    out = ["| " + " | ".join(esc(c) for c in rows[0]) + " |", "|" + "---|" * width]
    out += ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows[1:]]
    return "\n".join(out)


def div(name, body_md, **kv):
    attrs = " ".join(f'{k}="{str(v).replace(chr(34), "&quot;")}"' for k, v in kv.items() if v)
    colons = ":::"
    while colons in body_md:
        colons += ":"
    return f"\n{colons} {{.{name}{(' ' + attrs) if attrs else ''}}}\n{body_md}\n{colons}\n"


def myst_directive(name, arg, body, src, ctx, myst=True):
    """Markdown for one MyST directive (```{name} arg)."""
    opts, body = parse_directive_options(body)
    action = ctx.directive_action(name)
    text = "\n".join(body)
    here = Path(src).parent
    if name in ("currentmodule", "module", "py:currentmodule", "py:module"):
        ctx.current_module = arg.strip() or None
        return ""
    if action == "drop" or (action is None and name in DROP):
        return ""
    if action and action.startswith("code") or (action is None and name in CODE):
        lang = (action.split(":", 1)[1] if action and ":" in action else None) \
            or arg.strip() or opts.get("language") or CODE.get(name) or ctx.default_lang
        if name == "code-cell" and arg.strip() in ("ipython3", "ipython", "python3"):
            lang = "python"
        body_lines = [l for l in body if not l.startswith("#| ")]
        return fence("\n".join(body_lines).rstrip("\n"), lang)
    if name == "literalinclude":
        path = (here / arg.strip()).resolve()
        if not path.exists():
            ctx.warn(f"{src}: literalinclude {arg.strip()} not found")
            return ""
        lang = opts.get("language") or ctx.language_for(path)
        return fence(read_include(path, opts), lang)
    if name == "include":
        path = (here / arg.strip()).resolve()
        if not path.exists():
            ctx.warn(f"{src}: include {arg.strip()} not found")
            return ""
        inc = read_include(path, opts)
        if path.suffix in (".rst", ".rest", ".txt") and not path.suffix == ".md":
            return ctx.rst_to_markdown(inc, path)
        return preprocess_markdown(inc, path, ctx, myst=True)[0]
    if name in ("image", "figure"):
        alt = opts.get("alt", "")
        caption = text.strip() if name == "figure" else ""
        kv = size_attr(opts)
        if caption:
            kv.append('book-caption="yes"')
            alt = caption.replace("\n", " ").replace("]", "")
        return f"\n![{alt}]({arg.strip()})" + ("{" + " ".join(kv) + "}" if kv else "") + "\n"
    if name == "math":
        return "\n$$" + fix_math_body(text) + "$$\n"
    if name == "eval-rst":
        return ctx.rst_to_markdown(text, src)
    if name == "list-table":
        title = f"\n**{arg.strip()}**\n\n" if arg.strip() else ""
        return title + list_table_to_md(body) + "\n"
    if name == "csv-table":
        data = text
        if "file" in opts:
            p = (here / opts["file"]).resolve()
            data = p.read_text(errors="replace") if p.exists() else ""
        head = ""
        if "header" in opts:
            head = opts["header"] + "\n"
        title = f"\n**{arg.strip()}**\n\n" if arg.strip() else ""
        return title + csv_table_to_md(head + data) + "\n"
    if name in AUTODOC or (name.startswith("auto") and name[4:] in ("module", "class", "function")):
        rst = ctx.autodoc_rst(name, arg.strip(), opts, src, module=getattr(ctx, "current_module", None),
                              body=body)
        return ctx.rst_to_markdown(rst, src) if rst else ""
    if name in ADMONITIONS and name not in TITLED and not name.startswith(("version", "deprecated")) \
            and arg.strip():
        text = arg.strip() + "\n" + text           # ```{note} Some text -> content
        arg = ""
    inner = preprocess_markdown(text, src, ctx, myst=myst)[0]
    if name in ADMONITIONS or (action or "").startswith("aside"):
        label = (action.split(":", 1)[1] if action and ":" in action else None)
        return div("admonition-src", inner, kind=name, arg=arg.strip(), label=label or "")
    if action == "keep" or name in UNWRAP:
        title = f"**{arg.strip()}**\n\n" if arg.strip() and name in (
            "tab-item", "tab", "card", "grid-item-card", "dropdown", "table") else ""
        return "\n" + title + inner + "\n"
    ctx.note_unknown_directive(name, src)
    return "\n" + inner + "\n"


QUARTO_CHUNK = re.compile(r"^\{(?P<lang>[A-Za-z][\w+-]*)(?P<rest>[^}]*)\}\s*$")
QUARTO_LANGS = {"python", "r", "julia", "bash", "sh", "sql", "ojs", "mermaid", "dot", "js",
                "javascript", "stan", "cpp", "rcpp", "observable"}


def code_fence_run(m, body, src, ctx, myst):
    info = (m.group("info") or "").strip()
    text = "\n".join(body)
    if m.group("fence")[0] == ":" and re.match(r"^\{\s*[.#]", info):
        # a pandoc fenced div (Quarto callouts and the like)
        inner = preprocess_markdown(text, src, ctx, myst)[0]
        colons = m.group("fence")
        while colons in inner:
            colons += ":"
        return f"{colons} {info}\n{inner}\n{colons}"
    if info.startswith("{"):
        mm = re.match(r"^\{(?P<name>[^}\s]+)\}\s*(?P<arg>.*)$", info)
        q = QUARTO_CHUNK.match(info)
        if q and q.group("lang").lower() in QUARTO_LANGS:
            opts = q.group("rest")
            lines = body
            chunk_opts = {}
            while lines and lines[0].startswith("#| "):
                k, _, v = lines[0][3:].partition(":")
                chunk_opts[k.strip()] = v.strip()
                lines = lines[1:]
            hidden = re.search(r"\b(include|echo)\s*=\s*F(ALSE)?\b", opts) or \
                chunk_opts.get("echo") == "false" or chunk_opts.get("include") == "false"
            if hidden:
                return ""
            return fence("\n".join(lines), q.group("lang").lower())
        if mm:
            name = mm.group("name")
            if name.startswith("{") or name.startswith("="):
                return fence(text, info)                          # raw attribute block
            return myst_directive(name, mm.group("arg"), body, src, ctx, myst)
    # ```note -- an admonition written as a code fence
    plain = info.split()[0] if info else ""
    if plain in ("note", "tip", "warning", "important", "caution", "hint", "attention",
                 "danger", "seealso"):
        return div("admonition-src", preprocess_markdown(text, src, ctx, myst)[0], kind=plain)
    return fence(text, info)


# ---------------------------------------------------------------------------
# MkDocs (Python-Markdown, pymdown-extensions, mkdocstrings), Docusaurus and
# VitePress syntax -> MyST-style directives that myst_directive understands
# ---------------------------------------------------------------------------

MK_ADMON = re.compile(r'^(?P<mark>!!!|\?\?\?\+?)[ \t]+(?P<kind>[\w-]+)(?:[ \t]+[\w-]+)*'
                      r'(?:[ \t]+"(?P<title>[^"]*)")?[ \t]*$')
MK_TAB = re.compile(r'^===\+?[ \t]+"(?P<title>[^"]*)"[ \t]*$')
COLON_ADMON = re.compile(r"^(?P<colons>:{3,})[ \t]*(?P<kind>[A-Za-z][\w-]*)(?:\[(?P<t1>[^\]]*)\])?"
                         r"(?:[ \t]+(?P<t2>[^{].*?))?[ \t]*$")
COLON_KINDS = {"note", "tip", "info", "warning", "danger", "caution", "important", "details",
               "success", "question", "failure", "bug", "example", "quote", "abstract", "hint",
               "attention", "error", "seealso", "secondary"}
MKDOCSTRINGS = re.compile(r"^:::[ \t]+(?P<target>[A-Za-z_][\w.]*)[ \t]*$")
SNIPPET = re.compile(r'^(?P<indent>[ \t]*)-{1,2}8<-{1,2}[ \t]+"(?P<path>[^"]+)"[ \t]*$')


def indented_block(lines, i, width=4):
    """Lines from i on that are indented by `width` (or blank); dedented."""
    body = []
    while i < len(lines) and (not lines[i].strip() or lines[i].startswith(" " * width) or
                              lines[i].startswith("\t")):
        body.append(lines[i][width:] if lines[i].startswith(" " * width) else lines[i].lstrip("\t"))
        i += 1
    while body and not body[-1].strip():
        body.pop()
        i -= 1
    return body, i


def colon_wrap(head, body):
    colons = ":::"
    while any(l.startswith(colons) for l in body):
        colons += ":"
    return [f"{colons}{head}", *body, colons, ""]


def snippet_text(path, src, ctx):
    for base in (Path(src).parent, ctx.root, ctx.root.parent, ctx.root.parent.parent):
        p = (base / path)
        if p.is_file():
            return p.read_text(errors="replace").rstrip("\n").split("\n")
    ctx.warn(f"{src}: snippet {path} not found")
    return []


def convert_site_syntax(text, src, ctx):
    lines = text.split("\n")
    out, i, fence_mark = [], 0, None
    mdx = str(src).endswith(".mdx")
    while i < len(lines):
        line = lines[i]
        f = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if fence_mark:
            out.append(line)
            if f and f.group(1)[0] == fence_mark[0] and len(f.group(1)) >= len(fence_mark) \
                    and not line.strip()[len(f.group(1)):].strip():
                fence_mark = None
            i += 1
            continue
        if f:
            fence_mark = f.group(1)
            out.append(line)
            i += 1
            continue
        m = MK_ADMON.match(line)
        if m:
            body, i = indented_block(lines, i + 1)
            kind, title = m.group("kind").lower(), m.group("title")
            # a custom title replaces the kind's label; "" (no title bar) keeps it
            out += colon_wrap("{admonition} " + title if title else "{" + kind + "}", body)
            continue
        m = MK_TAB.match(line)
        if m:
            body, i = indented_block(lines, i + 1)
            out += [f"**{m.group('title')}**", "", *body, ""]
            continue
        m = MKDOCSTRINGS.match(line)
        if m:
            _opts, i = indented_block(lines, i + 1)
            out += colon_wrap("{autoobject} " + m.group("target"), [":members:"])
            continue
        m = SNIPPET.match(line)
        if m:
            out += [m.group("indent") + l for l in snippet_text(m.group("path"), src, ctx)]
            i += 1
            continue
        m = COLON_ADMON.match(line)
        if m and m.group("kind").lower() in COLON_KINDS:
            kind, title = m.group("kind").lower(), (m.group("t1") or m.group("t2") or "").strip()
            out.append(f"{m.group('colons')}{{admonition}} {title}" if title else f"{m.group('colons')}{{{kind}}}")
            i += 1
            continue
        if re.match(r"^:{3,}[ \t]*code-group[ \t]*$", line):
            i += 1                                    # VitePress code groups: keep the blocks
            depth = 1
            while i < len(lines) and depth:
                if re.match(r"^:{3,}[ \t]*$", lines[i]):
                    depth -= 1
                    i += 1
                    continue
                out.append(lines[i])
                i += 1
            continue
        if mdx:
            if re.match(r"^(import|export)\s.*$", line):
                i += 1
                continue
            t = re.match(r'^\s*<TabItem\b[^>]*?label=["\']([^"\']+)["\'][^>]*>\s*$', line)
            if t:
                out += [f"**{t.group(1)}**", ""]
                i += 1
                continue
            if re.match(r"^\s*</?[A-Z][\w.]*(\s[^>]*)?/?>\s*$", line):
                i += 1
                continue
        line = re.sub(r"^\[TOC\]\s*$", "", line)
        line = re.sub(r"^\*\[[^\]]+\]:.*$", "", line)                       # abbreviations
        line = re.sub(r":(material|octicons|fontawesome|simple)-[\w-]+:(\{[^}]*\})?", "", line)
        line = re.sub(r"\{:\s*([^}]*)\}", lambda mm: "{" + mm.group(1).strip() + "}", line)
        line = re.sub(r"\{\s+([.#][^}]*?)\s*\}", lambda mm: "{" + mm.group(1) + "}", line)
        out.append(line)
        i += 1
    return "\n".join(out)


SITE_SYNTAX = re.compile(r"^(!!!|\?\?\?|===\+? \"|:::[ \t]*[A-Za-z]|-{1,2}8<-{1,2} )", re.M)


def preprocess_markdown(text, src, ctx, myst=None):
    """Prepared Markdown and its front-matter metadata."""
    meta, text = split_front_matter(text)
    if SITE_SYNTAX.search(text) or str(src).endswith(".mdx"):
        text = convert_site_syntax(text, src, ctx)
    if myst is None:
        myst = bool(re.search(r"^ {0,3}(`{3,}|:{3,})\{[\w:-]+\}|\{[\w:+-]+\}`", text, re.M)) \
            or str(src).endswith(".md") and ctx.myst_project
    out = []
    for m, body in split_fences(text):
        if m is None:
            prose = prose_rewrites(body, myst, quarto=str(src).lower().endswith((".qmd", ".rmd")))
            prose = wrap_bare_environments(prose)
            out.append(normalize_math(prose, ctx.warn, strict=not str(src).endswith(".ipynb")))
        else:
            out.append(m.group("indent") + code_fence_run(m, body, src, ctx, myst))
    return "\n".join(out), meta


# ---------------------------------------------------------------------------
# reStructuredText
# ---------------------------------------------------------------------------

# Directives whose body is not reStructuredText.
VERBATIM = {"code-block", "code", "sourcecode", "math", "raw", "csv-table", "productionlist",
            "graphviz", "digraph", "graph", "parsed-literal", "testcode", "testoutput", "doctest",
            "highlight", "ipython", "jupyter-execute", "plot", "mermaid", "uml", "plantuml",
            "literalinclude", "include", "code-cell", "prompt", "tabularcolumns", "image", "figure"}
RST_LIST_DIRECTIVE = re.compile(r"^([ \t]*)([*+-]|\d+[.)]|#\.)([ \t]+)(\.\.[ \t]+[\w:+.-]+::.*)$")
RST_DIRECTIVE = re.compile(r"^(?P<indent>[ \t]*)\.\.[ \t]+(?P<name>[\w:+.-]+)::(?P<arg>.*)$")


def rst_blocks(lines, start, indent):
    """Option and body lines of a directive starting at `start`."""
    opts, j = {}, start + 1
    base = len(indent.expandtabs())
    while j < len(lines):
        m = re.match(r"^([ \t]+):([^:]+):\s*(.*)$", lines[j])
        if m and len(m.group(1).expandtabs()) > base:
            opts[m.group(2).strip()] = m.group(3).strip()
            j += 1
        else:
            break
    body = []
    while j < len(lines):
        line = lines[j]
        if line.strip() and len(line) - len(line.lstrip()) <= base:
            break
        body.append(line)
        j += 1
    while body and not body[-1].strip():
        body.pop()
    while body and not body[0].strip():
        body.pop(0)
    if body:
        cut = min(len(l) - len(l.lstrip()) for l in body if l.strip())
        body = [l[cut:] for l in body]
    return opts, body, j


def looks_like_code(body):
    lines = [l for l in body if l.strip()]
    if not lines:
        return False
    codey = sum(bool(re.search(r"[=(){}\[\];]|^\s*(def|class|import|from|return|for|if)\b|^\$|^>>>", l))
                for l in lines)
    return codey >= max(2, 0.6 * len(lines))


def indent_lines(lines, n):
    pad = " " * n
    return [pad + l if l.strip() else "" for l in lines]


def preprocess_rst(text, src, ctx, module=None):
    """Rewrite Sphinx directives pandoc does not know into ones it does."""
    lines = text.replace("\r\n", "\n").split("\n")
    out, i = [], 0
    state = {"module": module or getattr(ctx, "current_module", None)}
    while i < len(lines):
        bullet = None
        li = RST_LIST_DIRECTIVE.match(lines[i])
        if li:                      # "*   .. autoclass:: X": a directive as a list item's body
            bullet = li.group(1) + li.group(2)
            lines[i] = " " * len(bullet + li.group(3)) + li.group(4)
        m = RST_DIRECTIVE.match(lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        indent, name, arg = m.group("indent"), m.group("name").lower(), m.group("arg").strip()
        opts, body, j = rst_blocks(lines, i, indent)
        action = ctx.directive_action(name)
        here = Path(src).parent
        rep = None
        if name in ("currentmodule", "module", "py:currentmodule", "py:module"):
            state["module"] = arg or None
            ctx.current_module = state["module"]
            rep = []
        elif action == "drop" or (action is None and name in DROP):
            rep = []
        elif name == "only":
            rep = [] if re.search(r"\bhtml\b|\bepub\b", arg) and "latex" not in arg else \
                indent_lines(preprocess_rst("\n".join(body), src, ctx, state["module"]).split("\n"), 0)
        elif name == "literalinclude":
            path = (here / arg).resolve()
            code = read_include(path, opts) if path.exists() else ""
            if not path.exists():
                ctx.warn(f"{src}: literalinclude {arg} not found")
            lang = opts.get("language") or ctx.language_for(path)
            rep = [f".. code-block:: {lang}", ""] + indent_lines(code.split("\n"), 3)
        elif name == "include" and not arg.startswith("<"):
            path = (here / arg).resolve()
            if path.exists():
                rep = preprocess_rst(read_include(path, opts), path, ctx, state["module"]).split("\n")
            else:
                ctx.warn(f"{src}: include {arg} not found")
                rep = []
        elif (action or "").startswith("code") or (action is None and name in CODE and name != "code-block") \
                or (action is None and name not in ADMONITIONS and name not in UNWRAP
                    and name not in AUTODOC and name not in ("code-block", "figure", "image", "math",
                                                             "table", "list-table", "csv-table", "note",
                                                             "warning", "rubric", "glossary")
                    and looks_like_code(body)):
            lang = (action.split(":", 1)[1] if action and ":" in action else None) or \
                CODE.get(name) or arg or ctx.default_lang
            if name not in CODE and not action:
                ctx.note_unknown_directive(name, src, "set as code")
            rep = [f".. code-block:: {lang}", ""] + indent_lines(body, 3)
        elif name in ("versionadded", "versionchanged", "deprecated", "versionremoved"):
            version, _, first = arg.partition(" ")
            label = f"{ADMONITIONS[name]} {version}".strip()
            content = ([first] if first else []) + body
            rep = [f".. admonition:: {label}", ""] + indent_lines(
                preprocess_rst("\n".join(content), src, ctx, state["module"]).split("\n"), 3)
        elif name in AUTODOC:
            rst = ctx.autodoc_rst(name, arg, opts, src, module=state["module"], body=body)
            rep = rst.split("\n") if rst else []
        elif name == "rubric":
            rep = [f"**{arg}**", ""]
        if rep is None and name not in VERBATIM and body:
            # a directive pandoc knows (container, note, table ...): keep it,
            # but prepare the directives nested in its body as well
            n_opts = len(opts)
            inner = preprocess_rst("\n".join(body), src, ctx, state["module"]).split("\n")
            pad = len(indent.expandtabs()) + 3
            rep_lines = [lines[i]] + lines[i + 1:i + 1 + n_opts] + [""] + indent_lines(inner, pad) + [""]
        elif rep is None:
            rep_lines = [lines[i]] + lines[i + 1:j]
        else:
            rep_lines = (indent_lines(rep, len(indent.expandtabs())) if indent else rep) + [""]
        if bullet is not None:
            first = next((k for k, l in enumerate(rep_lines) if l.strip()), None)
            if first is None:
                rep_lines = []
            else:
                rep_lines[first] = bullet + rep_lines[first][len(bullet):]
        out.extend(rep_lines)
        i = j
    return "\n".join(out)

"""Small helpers for pandoc's JSON document tree.

pandoc -t json gives {"pandoc-api-version": [...], "meta": {...},
"blocks": [...]}; every element is {"t": Type, "c": contents}.  These
helpers read, walk, build and write such trees without any third-party
library.
"""

import json
import subprocess

PANDOC = "pandoc"


class PandocError(RuntimeError):
    pass


def run_pandoc(args, text=None, cwd=None):
    res = subprocess.run([PANDOC, *args], input=text, capture_output=True, text=True, cwd=cwd)
    if res.returncode:
        raise PandocError(res.stderr.strip() or f"pandoc {' '.join(args)} failed")
    return res.stdout, res.stderr.strip()


def read(text_or_path, fmt, extra=(), cwd=None, is_path=False):
    """Parse a document with pandoc; return (doc, warnings)."""
    args = ["-f", fmt, "-t", "json", *extra]
    if is_path:
        out, err = run_pandoc([*args, str(text_or_path)], cwd=cwd)
    else:
        out, err = run_pandoc(args, text=text_or_path, cwd=cwd)
    return json.loads(out), err


def write(doc, fmt, extra=(), cwd=None):
    out, err = run_pandoc(["-f", "json", "-t", fmt, *extra], text=json.dumps(doc), cwd=cwd)
    return out, err


def empty_doc(api=None):
    return {"pandoc-api-version": api or [1, 23, 1], "meta": {}, "blocks": []}


# --- element constructors ------------------------------------------------

def el(t, c=None):
    return {"t": t} if c is None else {"t": t, "c": c}


def attr(ident="", classes=(), kv=()):
    return [ident, list(classes), [list(p) for p in kv]]


def Str(s):
    return el("Str", s)


def Space():
    return el("Space")


def text_inlines(s):
    """Inlines for plain text, split into Str and Space."""
    out = []
    for i, word in enumerate(s.split(" ")):
        if i:
            out.append(Space())
        if word:
            out.append(Str(word))
    return out


def Para(inlines):
    return el("Para", inlines)


def Plain(inlines):
    return el("Plain", inlines)


def Strong(inlines):
    return el("Strong", inlines)


def Code(text, a=None):
    return el("Code", [a or attr(), text])


def CodeBlock(text, classes=(), kv=(), ident=""):
    return el("CodeBlock", [attr(ident, classes, kv), text])


def RawBlock(fmt, text):
    return el("RawBlock", [fmt, text])


def RawInline(fmt, text):
    return el("RawInline", [fmt, text])


def Div(blocks, classes=(), kv=(), ident=""):
    return el("Div", [attr(ident, classes, kv), blocks])


def Header(level, inlines, ident="", classes=(), kv=()):
    return el("Header", [level, attr(ident, classes, kv), inlines])


def Link(inlines, target, title=""):
    return el("Link", [attr(), inlines, [target, title]])


def Math(kind, text):
    return el("Math", [{"t": kind}, text])


# --- reading elements ----------------------------------------------------

def get_attr(node):
    """The attribute triple of an element that has one, else None."""
    t, c = node.get("t"), node.get("c")
    if t in ("Code", "CodeBlock", "Div", "Span", "Figure", "Table"):
        return c[0]
    if t == "Header":
        return c[1]
    if t in ("Image", "Link"):
        return c[0]
    return None


def classes(node):
    a = get_attr(node)
    return a[1] if a else []


def attrs(node):
    a = get_attr(node)
    return dict(a[2]) if a else {}


def set_attr_kv(node, key, value):
    a = get_attr(node)
    kv = [p for p in a[2] if p[0] != key]
    if value is not None:
        kv.append([key, value])
    a[2] = kv


def stringify(x):
    """Plain text of an element or a list of elements."""
    if isinstance(x, list):
        return "".join(stringify(i) for i in x)
    if not isinstance(x, dict):
        return ""
    t, c = x.get("t"), x.get("c")
    if t == "Str":
        return c
    if t in ("Space", "SoftBreak", "LineBreak"):
        return " "
    if t in ("Code", "Math"):
        return c[1]
    if t in ("RawInline", "RawBlock"):
        return ""
    if t in ("Emph", "Strong", "Strikeout", "Underline", "SmallCaps", "Superscript",
             "Subscript", "Para", "Plain"):
        return stringify(c)
    if t == "Quoted":
        q = '"' if c[0]["t"] == "DoubleQuote" else "'"
        return q + stringify(c[1]) + q
    if t in ("Link", "Image"):
        return stringify(c[1])
    if t == "Span":
        return stringify(c[1])
    if t == "Header":
        return stringify(c[2])
    if t == "Div":
        return " ".join(stringify(b) for b in c[1])
    if t == "Cite":
        return stringify(c[1])
    if t == "Note":
        return ""
    if t == "CodeBlock":
        return c[1]
    if t in ("BulletList", "OrderedList"):
        items = c if t == "BulletList" else c[1]
        return " ".join(stringify(b) for item in items for b in item)
    if t == "BlockQuote":
        return " ".join(stringify(b) for b in c)
    return ""


# --- walking ---------------------------------------------------------------

def walk(x, fn):
    """Bottom-up transform.  fn(node) returns None (keep), a node, or a list
    of nodes to splice in place of it (an empty list deletes it)."""
    if isinstance(x, list):
        out = []
        for item in x:
            res = walk(item, fn)
            if isinstance(res, list) and isinstance(item, dict) and "t" in item:
                out.extend(res)
            else:
                out.append(res)
        return out
    if isinstance(x, dict):
        if "t" in x:
            if "c" in x:
                x["c"] = walk(x["c"], fn)
            res = fn(x)
            return x if res is None else res
        return {k: walk(v, fn) for k, v in x.items()}
    return x


def iter_nodes(x):
    if isinstance(x, list):
        for i in x:
            yield from iter_nodes(i)
    elif isinstance(x, dict):
        if "t" in x:
            yield x
            c = x.get("c")
            if isinstance(c, (list, dict)):
                yield from iter_nodes(c)
        else:
            for v in x.values():
                if isinstance(v, (list, dict)):
                    yield from iter_nodes(v)


def meta_text(meta, key):
    """A metadata value as plain text."""
    v = meta.get(key)
    if v is None:
        return None
    t, c = v.get("t"), v.get("c")
    if t == "MetaString":
        return c
    if t in ("MetaInlines",):
        return stringify(c)
    if t == "MetaBlocks":
        return " ".join(stringify(b) for b in c)
    if t == "MetaList":
        return ", ".join(meta_text({"x": i}, "x") or "" for i in c)
    if t == "MetaMap":
        return meta_text(c, "name") or meta_text(c, "title")
    if t == "MetaBool":
        return str(c)
    return None

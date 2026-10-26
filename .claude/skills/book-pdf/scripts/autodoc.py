"""Static stand-in for Sphinx autodoc.

API reference pages in Sphinx projects are mostly `.. autoclass::`,
`.. autofunction::` and friends, which Sphinx fills by importing the
package.  This module reads the package's source with `ast` instead (no
code is imported or run) and returns reStructuredText for each entry: a
`bookapi` container holding the signature as a literal, then the docstring.
Google- and NumPy-style docstring sections are turned into definition lists.

Anything it cannot find is reported, and the book gets a short note instead.
"""

import ast
import re
import textwrap
from pathlib import Path


class Autodoc:
    def __init__(self, roots, warn):
        self.roots = [Path(r) for r in roots if Path(r).is_dir()]
        self.warn = warn
        self.trees = {}
        self.missing = []

    # --- locating code ---------------------------------------------------

    def module_path(self, dotted):
        parts = dotted.split(".")
        for root in self.roots:
            base = root.joinpath(*parts)
            for cand in (base / "__init__.py", base.with_suffix(".py"), base.with_suffix(".pyi"),
                         base / "__init__.pyi"):
                if cand.is_file():
                    return cand
        return None

    def tree(self, path):
        if path not in self.trees:
            try:
                self.trees[path] = ast.parse(path.read_text(errors="replace"))
            except SyntaxError:
                self.trees[path] = ast.Module(body=[], type_ignores=[])
        return self.trees[path]

    @staticmethod
    def defined(scope, name):
        for stmt in scope:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and stmt.name == name:
                return stmt
            if isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in stmt.targets):
                return stmt
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.target.id == name:
                return stmt
        return None

    def follow_import(self, path, mod, name, hops):
        """`from .x import name` in module `mod` -> (path, module, node)."""
        if hops <= 0:
            return None
        pkg = mod if path.name.startswith("__init__") else mod.rpartition(".")[0]
        for stmt in self.tree(path).body:
            if not isinstance(stmt, ast.ImportFrom):
                continue
            for alias in stmt.names:
                if (alias.asname or alias.name) != name:
                    continue
                if stmt.level:
                    base = pkg.split(".")
                    base = base[:len(base) - stmt.level + 1] if stmt.level > 1 else base
                    src = ".".join(base + ([stmt.module] if stmt.module else []))
                else:
                    src = stmt.module or ""
                p2 = self.module_path(src)
                if p2:
                    node = self.defined(self.tree(p2).body, alias.name)
                    if node is not None:
                        return p2, src, node
                    hit = self.follow_import(p2, src, alias.name, hops - 1)
                    if hit:
                        return hit
                sub = self.module_path(f"{src}.{alias.name}")
                if sub:
                    return sub, f"{src}.{alias.name}", None
        return None

    def resolve(self, target, module=None):
        """(path, module name, node or None for a module itself, qualname)."""
        target = target.strip().lstrip("~!").split("(")[0].strip()
        cands = [target] + ([f"{module}.{target}"] if module and not target.startswith(module + ".") else [])
        for cand in cands:
            parts = cand.split(".")
            for k in range(len(parts), 0, -1):
                mod, rest = ".".join(parts[:k]), parts[k:]
                path = self.module_path(mod)
                if not path:
                    continue
                if not rest:
                    return path, mod, None, mod
                node = self.defined(self.tree(path).body, rest[0])
                p, m = path, mod
                if node is None:
                    hit = self.follow_import(path, mod, rest[0], 3)
                    if not hit:
                        continue
                    p, m, node = hit
                    if node is None:
                        if len(rest) == 1:
                            return p, m, None, m
                        continue
                for name in rest[1:]:
                    if not isinstance(node, ast.ClassDef):
                        node = None
                        break
                    node = self.defined(node.body, name)
                    if node is None:
                        break
                if node is not None:
                    return p, m, node, cand
        return None

    # --- rendering -------------------------------------------------------

    @staticmethod
    def signature(node, name, is_method):
        if isinstance(node, ast.ClassDef):
            init = next((s for s in node.body if isinstance(s, ast.FunctionDef) and s.name == "__init__"), None)
            if init is None:
                return f"class {name}"
            return f"class {name}" + Autodoc.signature(init, "", True)[0:]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            if is_method and (args.posonlyargs or args.args):
                first = (args.posonlyargs or args.args)[0].arg
                if first in ("self", "cls", "mcs", "metacls"):
                    args = ast.arguments(posonlyargs=args.posonlyargs[1:] if args.posonlyargs else [],
                                         args=args.args[1:] if not args.posonlyargs else args.args,
                                         vararg=args.vararg, kwonlyargs=args.kwonlyargs,
                                         kw_defaults=args.kw_defaults, kwarg=args.kwarg,
                                         defaults=args.defaults)
            try:
                sig = ast.unparse(args)
            except Exception:
                sig = "..."
            ret = ""
            if node.returns is not None:
                try:
                    ret = " -> " + ast.unparse(node.returns)
                except Exception:
                    pass
            prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
            return f"{prefix}{name}({sig}){ret}"
        return name

    @staticmethod
    def docstring(node, path=None):
        if node is None:
            return ""
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            return ast.get_docstring(node, clean=True) or ""
        return ""

    def member_docs(self, scope, owner_tree=None):
        """Docstrings that follow attribute assignments (Sphinx convention)."""
        docs = {}
        for a, b in zip(scope, scope[1:]):
            if isinstance(a, (ast.Assign, ast.AnnAssign)) and isinstance(b, ast.Expr) \
                    and isinstance(getattr(b, "value", None), ast.Constant) and isinstance(b.value.value, str):
                names = [t.id for t in (a.targets if isinstance(a, ast.Assign) else [a.target])
                         if isinstance(t, ast.Name)]
                for n in names:
                    docs[n] = textwrap.dedent(b.value.value).strip()
        return docs

    def members(self, node_or_module, opts, module_all=None):
        scope = node_or_module.body
        wanted = opts.get("members")
        if wanted is None:
            return []
        undoc = "undoc-members" in opts
        exclude = {x.strip() for x in opts.get("exclude-members", "").split(",") if x.strip()}
        special = {x.strip() for x in opts.get("special-members", "").split(",") if x.strip()}
        attr_docs = self.member_docs(scope)
        names = [w.strip() for w in wanted.split(",") if w.strip()] if wanted.strip() else None
        out = []
        for stmt in scope:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                n = stmt.name
            elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                n = next((t.id for t in targets if isinstance(t, ast.Name)), None)
                if n is None:
                    continue
            else:
                continue
            if names is not None:
                if n not in names:
                    continue
            else:
                if module_all is not None and n not in module_all:
                    continue
                if n.startswith("_") and n not in special:
                    continue
            if n in exclude:
                continue
            doc = self.docstring(stmt) if not isinstance(stmt, (ast.Assign, ast.AnnAssign)) else attr_docs.get(n, "")
            if not doc and not undoc and names is None:
                continue
            out.append((n, stmt, doc))
        if names is not None:
            order = {n: i for i, n in enumerate(names)}
            out.sort(key=lambda x: order.get(x[0], 0))
        return out

    @staticmethod
    def module_all(tree):
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in stmt.targets):
                try:
                    return [x for x in ast.literal_eval(stmt.value) if isinstance(x, str)]
                except Exception:
                    return None
        return None

    def entry(self, sig, doc, children=(), depth=0):
        lines = [".. container:: bookapi", ""]
        lit = sig.replace("``", "` `")
        lines.append(f"   ``{lit}``")
        lines.append("")
        body = napoleon(doc).split("\n") if doc else []
        lines += ["   " + l if l.strip() else "" for l in body]
        for child in children:
            lines.append("")
            lines += ["   " + l if l.strip() else "" for l in child.split("\n")]
        return "\n".join(lines) + "\n"

    def render(self, directive, target, opts, module=None):
        kind = directive.split(":")[-1].replace("auto", "")
        if kind in ("module",):
            hit = self.resolve(target)
            if not hit:
                return None
            path, mod, _node, _q = hit
            tree = self.tree(path)
            doc = ast.get_docstring(tree, clean=True) or ""
            kids = []
            for n, stmt, d in self.members(tree, opts, self.module_all(tree)):
                kids.append(self.render_node(stmt, n, d, False, opts if isinstance(stmt, ast.ClassDef) else {}))
            text = (napoleon(doc) + "\n\n" if doc else "") + "\n".join(kids)
            return text
        hit = self.resolve(target, module)
        if not hit:
            return None
        path, mod, node, qual = hit
        name = qual.split(".")[-1] if kind not in ("class", "exception") else qual.split(".")[-1]
        display = target.lstrip("~!").split("(")[0].strip()
        return self.render_node(node, display, None, kind in ("method",), opts)

    def render_node(self, node, name, doc, is_method, opts):
        if doc is None:
            doc = self.docstring(node)
        if isinstance(node, ast.ClassDef):
            kids = [self.render_node(stmt, n, d, True, {}) for n, stmt, d in self.members(node, opts)]
            return self.entry(self.signature(node, name, False), doc, kids)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            deco = {ast.unparse(d) for d in node.decorator_list} if node.decorator_list else set()
            sig = self.signature(node, name, is_method)
            if "property" in deco or any(d.endswith(".setter") for d in deco):
                sig = f"property {name}"
            elif "staticmethod" in deco:
                sig = "static " + sig
            elif "classmethod" in deco:
                sig = "classmethod " + sig
            return self.entry(sig, doc)
        return self.entry(name, doc)


SECTION = re.compile(r"^(Args|Arguments|Parameters|Params|Keyword Args|Keyword Arguments|"
                     r"Other Parameters|Returns|Return|Yields|Yield|Raises|Raise|Attributes|"
                     r"Examples?|Notes?|Warnings?|See Also|Todo|References|Methods)\s*:\s*$")
NUMPY_SECTION = re.compile(r"^(Parameters|Other Parameters|Returns|Yields|Raises|Attributes|"
                           r"Examples?|Notes?|Warnings?|See Also|References|Methods)\s*$")
ITEMS = {"Args", "Arguments", "Parameters", "Params", "Keyword Args", "Keyword Arguments",
         "Other Parameters", "Raises", "Raise", "Attributes", "Methods"}


FIELD = re.compile(r"^:(param|parameter|arg|argument|key|keyword|kwarg|kwparam|type|raises|raise|"
                   r"except|exception|returns|return|rtype|returntype|yields|yield|ytype|var|ivar|"
                   r"cvar|vartype|meta)(?:\s+([^:]+?))?:\s*(.*)$")


def plain_type(t):
    t = re.sub(r":[\w:]+:`~?!?([^`]+)`", r"\1", t)
    return t.replace("`", "").replace("*", "").strip()


def info_fields(lines):
    """Sphinx info field lists (:param x: ..., :returns: ...) -> Parameters,
    Returns and Raises sections like napoleon's."""
    out, i = [], 0
    while i < len(lines):
        m = FIELD.match(lines[i]) if lines[i].strip() else None
        if not m:
            out.append(lines[i])
            i += 1
            continue
        fields = []
        while i < len(lines):
            line = lines[i]
            m = FIELD.match(line)
            if m:
                fields.append([m.group(1), (m.group(2) or "").strip(), m.group(3).strip()])
            elif line.strip() and line[:1] in " \t" and fields:
                fields[-1][2] += " " + line.strip()
            elif not line.strip() and i + 1 < len(lines) and FIELD.match(lines[i + 1]):
                pass
            else:
                break
            i += 1
        params, types, returns, rtype, raises, attrs = [], {}, [], "", [], []
        for kind, name, text in fields:
            if kind in ("param", "parameter", "arg", "argument", "key", "keyword", "kwarg", "kwparam"):
                parts = name.split()
                if len(parts) >= 2:
                    types[parts[-1]] = " ".join(parts[:-1])
                params.append((parts[-1] if parts else name, text))
            elif kind == "type":
                types[name] = text
            elif kind in ("returns", "return", "yields", "yield"):
                returns.append(text)
            elif kind in ("rtype", "returntype", "ytype"):
                rtype = text
            elif kind in ("raises", "raise", "except", "exception"):
                raises.append((name, text))
            elif kind in ("var", "ivar", "cvar"):
                attrs.append((name, text))
            elif kind == "vartype":
                types[name] = text

        def deflist(title, items):
            res = ["", f"**{title}**", ""]
            for n, t in items:
                ty = plain_type(types.get(n, ""))
                res.append(f"``{n}``" + (f" (*{ty}*)" if ty else ""))
                res.append("   " + (t or "\\"))
            return res + [""]
        if params:
            out += deflist("Parameters", params)
        if attrs:
            out += deflist("Attributes", attrs)
        if returns or rtype:
            ty = plain_type(rtype)
            out += ["", "**Returns**", "", (f"*{ty}*" + (" -- " if returns else "") if ty else "") +
                    " ".join(returns), ""]
        if raises:
            res = ["", "**Raises**", ""]
            for n, t in raises:
                res += [f"``{plain_type(n)}``", "   " + (t or "\\")]
            out += res + [""]
    return out


def napoleon(doc):
    """Google/NumPy docstring sections -> rST that pandoc reads well."""
    lines = info_fields(doc.split("\n"))
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        g = SECTION.match(line.strip()) if not line.startswith(" ") else None
        n = NUMPY_SECTION.match(line.strip()) if i + 1 < len(lines) and \
            re.fullmatch(r"-{3,}\s*", lines[i + 1].strip() or "x") else None
        if g or n:
            title = (g or n).group(1)
            out += ["", f"**{title}**", ""]
            i += 2 if n else 1
            block = []
            while i < len(lines) and (not lines[i].strip() or lines[i].startswith((" ", "\t")) or n):
                if n and lines[i].strip() and i + 1 < len(lines) and \
                        re.fullmatch(r"-{3,}\s*", lines[i + 1].strip() or "x"):
                    break
                if g and lines[i].strip() and not lines[i].startswith((" ", "\t")):
                    break
                if n and SECTION.match(lines[i].strip()):
                    break
                block.append(lines[i])
                i += 1
            block = textwrap.dedent("\n".join(block)).strip("\n").split("\n")
            if title in ITEMS:
                out += items_to_deflist(block, numpy=bool(n))
            else:
                out += block
            out.append("")
            continue
        out.append(line)
        i += 1
    return "\n".join(out)


def items_to_deflist(block, numpy):
    out, cur = [], None
    for line in block:
        if not line.strip():
            continue
        if not line.startswith((" ", "\t")):
            if numpy:
                name, _, typ = line.partition(":")
            else:
                m = re.match(r"^(\*{0,2}[\w.\[\], *]+?)\s*(\(([^)]*)\))?\s*:\s*(.*)$", line)
                if m:
                    name, typ, desc = m.group(1), m.group(3) or "", m.group(4)
                else:
                    name, typ, desc = line, "", ""
            term = f"``{name.strip()}``" + (f" (*{typ.strip()}*)" if typ.strip() else "")
            out.append(term)
            cur = []
            if not numpy and desc:
                out.append("   " + desc)
        else:
            out.append("   " + line.strip())
    return out

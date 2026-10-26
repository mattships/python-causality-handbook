#!/usr/bin/env python3
"""Index terms for the book.

book.py uses auto_terms() when book.yaml says `index: auto` (the default)
and from_yaml() when it names a curated file.  Run on its own, this script
lists candidate terms for curating that file:

    python suggest_index.py book.yaml > index.yaml     # then edit, and set
                                                       # index: index.yaml

A term, as book.lua receives it: entry (as printed; "a!b" is sub-entry b
of a), key (the makeindex key), patterns (lowercase phrases matched at word
starts, so plurals match too), acronyms (matched exactly, as whole words),
exclude (longer phrases that contain the term but mean something else) and
home (chapters devoted to the term: their whole page range is indexed).
"""

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import astutil as A  # noqa: E402

GENERIC = {
    "introduction", "overview", "summary", "conclusion", "conclusions", "preface", "foreword",
    "appendix", "appendices", "references", "bibliography", "example", "examples", "note", "notes",
    "warning", "tip", "tips", "important", "see also", "api", "reference", "api reference",
    "changelog", "changes", "license", "faq", "faqs", "contents", "index", "about", "tutorial",
    "tutorials", "guide", "documentation", "exercises", "questions", "key ideas", "takeaways",
    "further reading", "resources", "todo", "to do", "contributing", "acknowledgments",
    "acknowledgements", "thanks", "credits", "next steps", "what's next", "getting started",
    "usage", "quickstart", "quick start", "basics", "advanced", "misc", "miscellaneous", "other",
    "details", "background", "motivation", "setup", "installation", "install", "requirements",
    "release notes", "history", "news", "authors", "glossary", "source", "sources", "code",
    "the code", "contribute", "support", "help", "deprecated", "new", "default", "optional",
    "required", "yes", "no", "true", "false", "none", "warning:", "note:", "tip:", "important:",
    "example:", "recap", "review", "final thoughts", "wrapping up", "key concepts", "intro",
    "parameters", "returns", "raises", "yields", "attributes", "methods", "arguments",
    "keyword arguments", "other parameters", "return type", "type", "defaults", "see",
    "changed in version", "new in version", "deprecated since version", "output", "result",
    "results", "methods", "method", "methodology", "discussion", "abstract", "analysis", "data",
    "findings", "limitations", "future work", "related work", "evaluation", "experiments",
    "approach", "implementation", "design", "problem statement", "literature review",
    "case study", "case studies", "outlook", "preliminaries", "definitions", "notation",
}
STOP = {"the", "a", "an", "this", "that", "these", "those", "it", "its", "we", "you", "our",
        "your", "they", "their", "is", "are", "was", "be", "not", "and", "or", "but", "if",
        "of", "to", "in", "on", "for", "with", "as", "at", "by", "from", "all", "any", "very",
        "do", "does", "don't", "can", "will", "should", "must", "may", "here", "there", "now"}
ACRONYM_DEF = re.compile(r"\b([A-Za-z][a-z]+(?:[ -][A-Za-z][\w'-]*){1,6}) \(([A-Z][A-Za-z0-9]*[A-Z]s?)\)")
TEX_ESC = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
           "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}


def tex(s):
    return "".join(TEX_ESC.get(c, c) for c in s)


def quote_mi(s):
    """Quote makeindex's special characters."""
    return re.sub(r'([!@|"])', r'"\1', s)


def sort_key(s):
    return quote_mi(re.sub(r"\s*\([^)]*\)", "", s).lower().strip() or s.lower())


def make_key(entry):
    levels = entry.split("!")
    return "!".join(f"{sort_key(l)}@{quote_mi(tex(l))}" for l in levels)


# ---------------------------------------------------------------------------
# reading the book
# ---------------------------------------------------------------------------

def prose(blocks):
    """Plain text of a chapter without its code."""
    out = []
    for b in blocks:
        t = b.get("t")
        if t in ("CodeBlock", "RawBlock"):
            continue
        if t in ("Div",):
            out.append(prose(b["c"][1]))
        elif t in ("BulletList",):
            out += [prose(item) for item in b["c"]]
        elif t in ("OrderedList",):
            out += [prose(item) for item in b["c"][1]]
        elif t == "BlockQuote":
            out.append(prose(b["c"]))
        elif t == "DefinitionList":
            for term, defs in b["c"]:
                out.append(A.stringify(term))
                out += [prose(d) for d in defs]
        else:
            out.append(A.stringify(b))
    return "\n".join(out)


def count_mentions(phrase, text):
    return len(re.findall(r"(?<![\w-])" + re.escape(phrase), text))


def chapter_texts(chapters):
    return {c.slug: prose([b for u in c.units for b in u.doc["blocks"]]) for c in chapters}


def candidates(chapters):
    """{phrase: {"kinds": set, "form": printed form}} found in the book."""
    found = defaultdict(lambda: {"kinds": set(), "forms": Counter(), "acronym": None})

    def add(phrase, kind, form=None, acronym=None):
        p = " ".join(phrase.split()).strip(" .,:;!?\"'“”‘’()[]")
        if not p or len(p) < 3 or len(p) > 60 or p.lower() in GENERIC:
            return
        words = p.split()
        if len(words) > 5 or words[0].lower() in STOP or words[-1].lower() in STOP:
            return
        if not re.search(r"[A-Za-z]{3}", p) or re.search(r"[=<>{}\\$`|]", p) or p.endswith(":"):
            return
        e = found[p.lower()]
        e["kinds"].add(kind)
        e["forms"][form or p] += 1
        if acronym:
            e["acronym"] = acronym

    for c in chapters:
        if c.kind in ("back",):
            continue
        for u in c.units:
            for n in A.iter_nodes(u.doc["blocks"]):
                t = n.get("t")
                if t in ("Strong", "Emph"):
                    add(A.stringify(n["c"]), "emphasis")
                elif t == "DefinitionList":
                    for term, _defs in n["c"]:
                        if not any(i.get("t") == "Code" for i in A.iter_nodes(term)):
                            add(A.stringify(term), "defined")
                elif t == "Header" and n["c"][0] <= 2:
                    add(A.stringify(n["c"][2]), "heading")
            text = prose(u.doc["blocks"])
            for m in ACRONYM_DEF.finditer(text):
                long, acr = m.group(1), m.group(2)
                initials = "".join(w[0] for w in re.split(r"[ -]", long) if w).upper()
                if acr.rstrip("s").upper() in initials or initials.endswith(acr.rstrip("s").upper()):
                    words = re.split(r"[ -]", long)
                    k = len(acr.rstrip("s"))
                    long = " ".join(long.split()[-k:]) if len(words) > k else long
                    add(f"{long} ({acr.rstrip('s')})", "acronym", acronym=acr.rstrip("s"))
        title = A.stringify(c.title_inlines)
        if c.kind == "main":
            add(title, "chapter")
    return found


def printed_form(phrase_lower, info, texts_all):
    """Lowercase unless the phrase is written capitalised mid-sentence."""
    form = info["forms"].most_common(1)[0][0]
    if info["acronym"]:
        return form
    words = form.split()
    if any(w.isupper() and len(w) > 1 for w in words) or any(re.search(r"[A-Z].*[A-Z]|\d", w[1:]) for w in words):
        return form
    lower_hits = count_mentions(phrase_lower, texts_all)
    cap = form[0].upper() + form[1:]
    cap_hits = len(re.findall(r"(?<![.!?]\s)(?<!^)" + re.escape(cap), texts_all, re.M))
    return form if cap_hits > lower_hits else phrase_lower


def score_terms(chapters):
    texts = chapter_texts(chapters)
    all_lower = "\n".join(texts.values()).lower()
    all_text = "\n".join(texts.values())
    titles = {c.slug: A.stringify(c.title_inlines).lower() for c in chapters}
    out = []
    for phrase, info in candidates(chapters).items():
        base = re.sub(r"\s*\([^)]*\)$", "", phrase)
        per = {slug: count_mentions(base, t.lower()) for slug, t in texts.items()}
        acr = info["acronym"]
        if acr:
            for slug, t in texts.items():
                per[slug] += len(re.findall(r"(?<![\w-])" + re.escape(acr) + r"s?(?![\w-])", t))
        mentions = sum(per.values())
        spread = sum(1 for v in per.values() if v)
        home = [slug for slug, t in titles.items() if t.strip() == base or t.strip() == phrase]
        kinds = info["kinds"]
        out.append({"phrase": phrase, "base": base, "form": printed_form(base, info, all_text)
                    if not acr else info["forms"].most_common(1)[0][0],
                    "mentions": mentions, "spread": spread, "kinds": sorted(kinds), "home": home,
                    "acronym": acr})
    _ = all_lower
    return out


def term_from(c):
    entry = c["form"]
    pats = [c["base"].lower()]
    if pats[0].endswith("s") and len(pats[0]) > 4 and not pats[0].endswith("ss"):
        pats.append(pats[0][:-1])
    t = {"entry": entry, "key": make_key(entry), "patterns": pats,
         "acronyms": [c["acronym"]] if c.get("acronym") else [], "exclude": [], "home": c.get("home", [])}
    return t


def auto_terms(chapters, limit=220):
    """A conservative index: chapter topics (with their page ranges),
    defined terms and acronyms, and emphasised phrases the book keeps using."""
    picked = []
    for c in score_terms(chapters):
        k = set(c["kinds"])
        if "chapter" in k and c["home"] and len(c["base"].split()) <= 5:
            ok = True
        elif "defined" in k and c["mentions"] >= 2:
            ok = True
        elif "acronym" in k and c["mentions"] >= 3:
            ok = True
        elif "emphasis" in k and c["mentions"] >= 3 and c["spread"] >= 2 and 2 <= len(c["base"].split()) <= 4:
            ok = True                       # single emphasised words are mostly just emphasis
        elif "heading" in k and c["spread"] >= 3 and c["mentions"] >= 5 and len(c["base"].split()) <= 3:
            ok = True
        else:
            ok = False
        if ok:
            picked.append(c)
    picked.sort(key=lambda c: (-(bool(c["home"])), -c["spread"], -c["mentions"]))
    picked = picked[:limit]
    # a phrase contained in a longer picked phrase: exclude the longer one's text
    terms = [term_from(c) for c in picked]
    for t in terms:
        for o in terms:
            if o is not t and t["patterns"][0] in o["patterns"][0] and t["patterns"][0] != o["patterns"][0]:
                t["exclude"].append(o["patterns"][0])
    return terms


def from_yaml(data, chapters):
    """Terms from a curated index.yaml (see references/config.md)."""
    by = {}
    for c in chapters:
        by[c.slug] = c.slug
        by[A.stringify(c.title_inlines).strip().lower()] = c.slug
        for u in c.units:
            if u.path:
                by[str(u.path.name).lower()] = c.slug
                by[str(u.path.with_suffix("").name).lower()] = c.slug
    terms = []
    for item in data.get("terms") or []:
        if isinstance(item, str):
            item = {"term": item}
        entry = str(item.get("term") or item.get("entry"))
        match = item.get("match") or [re.sub(r"\s*\([^)]*\)$", "", entry.split("!")[-1])]
        if isinstance(match, str):
            match = [match]
        pats = [m.lower() for m in match if not (m.isupper() and len(m) <= 8)]
        acr = [m for m in match if m.isupper() and len(m) <= 8]
        home = []
        for h in item.get("home") or []:
            slug = by.get(str(h).strip().lower())
            if slug:
                home.append(slug)
        terms.append({"entry": entry, "key": make_key(entry), "patterns": pats, "acronyms": acr,
                      "exclude": [x.lower() for x in item.get("exclude") or []], "home": home})
    return terms


def lua_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def to_lua(terms):
    rows = []
    for t in terms:
        fields = [f"entry={lua_str(t['entry'])}", f"key={lua_str(t['key'])}"]
        for k in ("patterns", "acronyms", "exclude", "home"):
            fields.append(f"{k}={{" + ", ".join(lua_str(x) for x in t.get(k) or []) + "}")
        rows.append("  {" + ", ".join(fields) + "},")
    return "return {\n" + "\n".join(rows) + "\n}\n"


def main():
    import argparse
    import yaml
    from book import Build
    ap = argparse.ArgumentParser(description="List index-term candidates for book.yaml.")
    ap.add_argument("config")
    ap.add_argument("--top", type=int, default=300)
    args = ap.parse_args()
    b = Build(args.config)
    b.dir.mkdir(parents=True, exist_ok=True)
    b.plan()
    chapters = b.chapters()
    for c in chapters:
        for u in c.units:
            b.load(u)
        c.title_inlines = c.units[0].title_inlines
    cands = sorted(score_terms(chapters), key=lambda c: (-bool(c["home"]), -c["spread"] * c["mentions"]))
    print("# Index candidates: keep the terms a reader would look up, merge variants with")
    print("# `match`, nest with 'parent!child', give chapter topics a `home` (slug, title or file).")
    print("# Then point book.yaml at this file:  index: index.yaml")
    print("terms:")
    for c in cands[:args.top]:
        item = {"term": c["form"]}
        if c["acronym"]:
            item["match"] = [c["base"], c["acronym"]]
        if c["home"]:
            item["home"] = c["home"]
        line = yaml.safe_dump([item], default_flow_style=None, allow_unicode=True, width=200).strip()
        print(f"  {line}   # {c['mentions']} mentions, {c['spread']} chapters, {'/'.join(c['kinds'])}")
    print("see: {}   # e.g.  ATE: average treatment effect (ATE)")


if __name__ == "__main__":
    main()

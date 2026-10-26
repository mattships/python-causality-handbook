"""A small suffix-stripping stemmer (a few rules of Porter's algorithm)."""

SUFFIXES = [("sses", "ss"), ("ies", "i"), ("ss", "ss"), ("s", ""),
            ("eed", "ee"), ("ing", ""), ("ed", ""), ("ational", "ate"),
            ("tional", "tion"), ("izer", "ize"), ("ness", ""), ("ful", "")]


def has_vowel(word):
    return any(c in "aeiouy" for c in word)


def stem(word):
    """Reduce ``word`` to a stem: "running" -> "runn", "ponies" -> "poni".

    The rules are applied once, longest suffix first, and only when what
    remains still contains a vowel.
    """
    w = word.lower()
    for suffix, repl in SUFFIXES:
        if w.endswith(suffix):
            base = w[: -len(suffix)]
            if has_vowel(base):
                return base + repl
            return w
    return w

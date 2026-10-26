"""Word frequencies."""
from collections import Counter

STOPWORDS = frozenset("""a an and are as at be but by for from has he her his i in is it its
of on or she that the their they this to was were will with you""".split())


def word_counts(words, skip_stopwords=True):
    """Count the words of a token list, optionally without stop words."""
    return Counter(w for w in words if not (skip_stopwords and w in STOPWORDS))


def top_words(words, n=10, skip_stopwords=True):
    """The ``n`` most frequent words as (word, count) pairs, most frequent first.

    Ties are broken alphabetically so that the result does not depend on
    the order of the input.
    """
    counts = word_counts(words, skip_stopwords)
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]


def type_token_ratio(words):
    """Distinct words divided by all words: a crude measure of vocabulary richness."""
    return len(set(words)) / len(words) if words else 0.0

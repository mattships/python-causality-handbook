"""Comparing documents."""
import math
from collections import Counter


def cosine_similarity(a, b):
    """Cosine of the angle between the word-count vectors of two token lists.

    Returns a number between 0 (no words in common) and 1 (the same
    proportions of the same words).
    """
    ca, cb = Counter(a), Counter(b)
    dot = sum(ca[w] * cb[w] for w in ca.keys() & cb.keys())
    norm = math.sqrt(sum(v * v for v in ca.values())) * math.sqrt(sum(v * v for v in cb.values()))
    return dot / norm if norm else 0.0


def jaccard(a, b):
    """Shared distinct words divided by all distinct words of the two lists."""
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb) if sa | sb else 1.0

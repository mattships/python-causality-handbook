"""textkit: counting and comparing words in text."""
from .tokenize import tokenize, sentences
from .stem import stem
from .stats import word_counts, top_words
from .similarity import cosine_similarity, jaccard

__all__ = ["tokenize", "sentences", "stem", "word_counts", "top_words",
           "cosine_similarity", "jaccard"]
__version__ = "0.4.0"

from textkit import tokenize, sentences, stem, top_words, cosine_similarity, jaccard


def test_tokenize_keeps_apostrophes():
    assert tokenize("Don't stop, believing!") == ["don't", "stop", "believing"]


def test_sentences_skip_abbreviations():
    assert sentences("Dr. Watson came. He sat down.") == ["Dr. Watson came.", "He sat down."]


def test_stem():
    assert stem("ponies") == "poni"
    assert stem("caresses") == "caress"


def test_top_words_breaks_ties_alphabetically():
    assert top_words(["b", "a", "b", "a", "c"], n=2) == [("a", 2), ("b", 2)]


def test_similarity_bounds():
    assert cosine_similarity(["x"], ["y"]) == 0.0
    assert jaccard(["x", "y"], ["y", "z"]) == 1 / 3

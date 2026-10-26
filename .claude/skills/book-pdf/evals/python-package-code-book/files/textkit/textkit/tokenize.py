"""Splitting text into words and sentences."""
import re

WORD = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")
ABBREVIATIONS = {"mr", "mrs", "dr", "st", "vs", "etc", "e.g", "i.e"}


def tokenize(text, lower=True):
    """Return the words of ``text`` as a list.

    Apostrophes inside words are kept ("don't"), everything else that is
    not a letter separates words.
    """
    words = WORD.findall(text)
    return [w.lower() for w in words] if lower else words


def sentences(text):
    """Split ``text`` into sentences, without splitting after common abbreviations."""
    parts, buf = [], ""
    for piece in SENTENCE_END.split(text.strip()):
        buf = f"{buf} {piece}".strip() if buf else piece
        last = buf.rstrip(".!?").split()[-1].lower() if buf.split() else ""
        if last not in ABBREVIATIONS:
            parts.append(buf)
            buf = ""
    if buf:
        parts.append(buf)
    return parts

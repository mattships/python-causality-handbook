"""The ``textkit`` command."""
import argparse
import sys

from . import tokenize, top_words, cosine_similarity


def main(argv=None):
    parser = argparse.ArgumentParser(prog="textkit", description="Count and compare words.")
    sub = parser.add_subparsers(dest="command", required=True)
    top = sub.add_parser("top", help="most frequent words of a file")
    top.add_argument("path")
    top.add_argument("--n", type=int, default=10)
    cmp_ = sub.add_parser("compare", help="cosine similarity of two files")
    cmp_.add_argument("first")
    cmp_.add_argument("second")
    args = parser.parse_args(argv)
    if args.command == "top":
        with open(args.path, encoding="utf-8") as f:
            for word, count in top_words(tokenize(f.read()), n=args.n):
                print(f"{count:>8}  {word}")
    else:
        with open(args.first, encoding="utf-8") as f1, open(args.second, encoding="utf-8") as f2:
            print(f"{cosine_similarity(tokenize(f1.read()), tokenize(f2.read())):.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

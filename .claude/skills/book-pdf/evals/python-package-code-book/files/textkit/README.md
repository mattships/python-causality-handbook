# textkit

Small, dependency-free tools for counting and comparing words in text:
tokenising, stemming, word frequencies and document similarity.

```python
from textkit import tokenize, top_words

text = open("moby-dick.txt").read()
print(top_words(tokenize(text), n=5))
```

## Command line

```console
$ textkit top moby-dick.txt --n 5
```

## License

MIT

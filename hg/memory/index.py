"""Offline keyword retrieval (BM25) shared by memory and research. Standard library only.

No embeddings or vector database: MIID §11 asks to start simple and measurable, and add
semantic search only when a benchmark shows the need. Tokens are Unicode word characters,
lower-cased, so Vietnamese text is indexed as written.
"""
import math
import re
from collections import Counter

_TOKEN = re.compile(r"\w+", re.UNICODE)


def tokenize(text):
    return [t for t in _TOKEN.findall((text or "").lower()) if len(t) > 1 or t.isdigit()]


class Index:
    def __init__(self, *, k1=1.2, b=0.75):
        self._docs = {}          # doc_id -> Counter
        self._lengths = {}
        self._df = Counter()
        self._k1, self._b = k1, b

    def __len__(self):
        return len(self._docs)

    def add(self, doc_id, text):
        if doc_id in self._docs:
            self.remove(doc_id)
        terms = Counter(tokenize(text))
        self._docs[doc_id] = terms
        self._lengths[doc_id] = sum(terms.values())
        self._df.update(terms.keys())

    def remove(self, doc_id):
        terms = self._docs.pop(doc_id, None)
        if terms is None:
            return
        self._lengths.pop(doc_id, None)
        for term in terms:
            self._df[term] -= 1
            if self._df[term] <= 0:
                del self._df[term]

    def search(self, query, *, limit=10, allowed=None):
        """[(doc_id, score)] best first; `allowed` optionally restricts candidate ids."""
        terms = set(tokenize(query))
        if not terms or not self._docs:
            return []
        n = len(self._docs)
        avg = sum(self._lengths.values()) / n or 1.0
        scores = {}
        for doc_id, tf in self._docs.items():
            if allowed is not None and doc_id not in allowed:
                continue
            score = 0.0
            for term in terms:
                f = tf.get(term)
                if not f:
                    continue
                idf = math.log(1 + (n - self._df[term] + 0.5) / (self._df[term] + 0.5))
                norm = f * (self._k1 + 1) / (f + self._k1 * (1 - self._b + self._b * self._lengths[doc_id] / avg))
                score += idf * norm
            if score > 0:
                scores[doc_id] = score
        return sorted(scores.items(), key=lambda kv: (-kv[1], str(kv[0])))[:limit]

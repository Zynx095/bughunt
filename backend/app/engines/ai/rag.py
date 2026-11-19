"""Retrieval for RAG: chunking + TF-IDF cosine retrieval over SQLite-stored chunks.

TF-IDF keeps retrieval fully local and deterministic. Dense embeddings can be
added behind the same `retrieve()` signature.
"""
from __future__ import annotations

import threading
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.engines.text import split_sentences


def chunk_text(text: str, max_chars: int = 900, overlap_sentences: int = 1) -> list[str]:
    sentences = split_sentences(text)
    chunks: list[str] = []
    cur: list[str] = []
    for s in sentences:
        if cur and sum(len(x) + 1 for x in cur) + len(s) > max_chars:
            chunks.append(" ".join(cur))
            cur = cur[-overlap_sentences:] if overlap_sentences else []
        cur.append(s)
    if cur:
        chunks.append(" ".join(cur))
    return chunks


class RetrievalIndex:
    def __init__(self, store) -> None:
        self.store = store
        self._cache: dict[str, tuple[Any, Any, list[dict]]] = {}
        self._lock = threading.Lock()

    def invalidate(self, collection: str) -> None:
        with self._lock:
            self._cache.pop(collection, None)

    def _index(self, collection: str):
        with self._lock:
            if collection not in self._cache:
                chunks = self.store.list_chunks(collection)
                if not chunks:
                    return None
                vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
                matrix = vec.fit_transform([c["text"] for c in chunks])
                self._cache[collection] = (vec, matrix, chunks)
            return self._cache[collection]

    def retrieve(self, collection: str, query: str, top_k: int = 4) -> list[dict[str, Any]]:
        idx = self._index(collection)
        if idx is None:
            return []
        vec, matrix, chunks = idx
        sims = cosine_similarity(vec.transform([query]), matrix).ravel()
        order = sims.argsort()[::-1][:top_k]
        return [{"citation": f"{chunks[i]['doc_id']}#{chunks[i]['chunk_index']}", "doc_id": chunks[i]["doc_id"],
                 "title": chunks[i]["meta"].get("title"), "text": chunks[i]["text"], "score": round(float(sims[i]), 4)}
                for i in order if sims[i] > 0]

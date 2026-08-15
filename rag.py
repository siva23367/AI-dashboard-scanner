"""
Lightweight local RAG retriever.

Splits knowledge-base .txt files into paragraph-level chunks and does
TF-IDF + cosine-similarity semantic search over them. This avoids needing
to download a large embedding model at runtime — it works fully offline
and is enough to ground the LLM's judgments in specific written guidelines
instead of letting it answer purely from memory.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import List

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


@dataclass
class Chunk:
    source: str
    text: str


class KnowledgeBase:
    def __init__(self, kb_dir: str):
        self.chunks: List[Chunk] = []
        self._load(kb_dir)
        self._vectorizer = TfidfVectorizer(stop_words="english")
        self._matrix = self._vectorizer.fit_transform([c.text for c in self.chunks]) \
            if self.chunks else None

    def _load(self, kb_dir: str):
        if not os.path.isdir(kb_dir):
            return
        for fname in sorted(os.listdir(kb_dir)):
            if not fname.endswith(".txt"):
                continue
            path = os.path.join(kb_dir, fname)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            # split into paragraphs (blank-line separated)
            paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if p.strip()]
            for p in paragraphs:
                self.chunks.append(Chunk(source=fname, text=p))

    def retrieve(self, query: str, top_k: int = 3) -> List[Chunk]:
        if not self.chunks or self._matrix is None:
            return []
        query_vec = self._vectorizer.transform([query])
        sims = cosine_similarity(query_vec, self._matrix)[0]
        ranked_idx = sims.argsort()[::-1][:top_k]
        return [self.chunks[i] for i in ranked_idx if sims[i] > 0]

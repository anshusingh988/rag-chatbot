"""Pluggable embedders. Default 'hash' needs no download or API key.

Hashing embedder = word+bigram hashing into a fixed-size L2-normalised vector.
It is stateless, so new documents can be added without re-fitting/re-indexing.
For true semantic similarity set EMBEDDER=st (sentence-transformers) or openai.
"""
from typing import List

import numpy as np

from . import config


class Embedder:
    name = "base"

    def embed(self, texts: List[str]) -> np.ndarray:  # (n, dim) float32, L2-normalised
        raise NotImplementedError


class HashEmbedder(Embedder):
    name = "hash-1024"

    def __init__(self, dim: int = 1024):
        from sklearn.feature_extraction.text import HashingVectorizer

        self.vec = HashingVectorizer(
            n_features=dim, ngram_range=(1, 2), alternate_sign=False,
            norm="l2", stop_words="english", lowercase=True,
        )

    def embed(self, texts):
        return self.vec.transform(texts).toarray().astype(np.float32)


class STEmbedder(Embedder):
    def __init__(self):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(config.ST_MODEL)
        self.name = f"st-{config.ST_MODEL}"

    def embed(self, texts):
        return np.asarray(self.model.encode(texts, normalize_embeddings=True), dtype=np.float32)


class OpenAIEmbedder(Embedder):
    def __init__(self):
        from openai import OpenAI

        self.client = OpenAI(api_key=config.OPENAI_API_KEY)
        self.name = f"openai-{config.OPENAI_EMBED_MODEL}"

    def embed(self, texts):
        out = []
        for i in range(0, len(texts), 96):
            r = self.client.embeddings.create(model=config.OPENAI_EMBED_MODEL, input=texts[i:i + 96])
            out.extend(d.embedding for d in r.data)
        arr = np.asarray(out, dtype=np.float32)
        return arr / np.maximum(np.linalg.norm(arr, axis=1, keepdims=True), 1e-9)


def make_embedder() -> Embedder:
    kind = config.EMBEDDER
    try:
        if kind == "st":
            return STEmbedder()
        if kind == "openai":
            return OpenAIEmbedder()
    except Exception as e:  # missing package / no network -> fall back, don't crash
        print(f"[embeddings] {kind} unavailable ({e}); falling back to hash embedder")
    return HashEmbedder()

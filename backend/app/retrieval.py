"""Hybrid retrieval: dense cosine + BM25 -> reciprocal rank fusion -> re-rank."""
import re
import threading
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
from rank_bm25 import BM25Okapi

from . import config
from .db import DB
from .embeddings import Embedder

_STOP = set(
    "a an the is are was were be been of to in on for and or but with at by from as it this that "
    "what which who whom how why when where do does did can could should would will shall i you we "
    "they he she me my our your their its about into than then so if not no yes please tell give".split()
)


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9_\-\.]+", text.lower())


def content_tokens(text: str) -> List[str]:
    return [t.strip(".-") for t in tokenize(text) if t.strip(".-") and t not in _STOP]


@dataclass
class Hit:
    chunk_id: int
    doc_id: int
    doc_title: str
    text: str
    heading: str
    page: Optional[int]
    dense: float = 0.0
    bm25: float = 0.0
    rrf: float = 0.0
    score: float = 0.0  # final re-rank score


class HybridIndex:
    def __init__(self, db: DB, embedder: Embedder):
        self.db, self.embedder = db, embedder
        self._lock = threading.Lock()
        self.rows: list = []
        self.matrix = np.zeros((0, 1), dtype=np.float32)
        self.bm25: Optional[BM25Okapi] = None
        self._ensure_embedder_matches()
        self.rebuild()

    # ----- indexing -----
    def _ensure_embedder_matches(self):
        """If the embedder changed since chunks were stored, re-embed everything."""
        cur = self.db.one("SELECT value FROM meta WHERE key='embedder'")
        if cur and cur["value"] == self.embedder.name:
            return
        rows = self.db.all("SELECT id,text FROM chunks")
        if rows:
            vecs = self.embedder.embed([r["text"] for r in rows])
            with self.db.tx() as c:
                for r, v in zip(rows, vecs):
                    c.execute("UPDATE chunks SET embedding=? WHERE id=?", (v.tobytes(), r["id"]))
        self.db.run("INSERT OR REPLACE INTO meta(key,value) VALUES('embedder',?)", (self.embedder.name,))

    def add_document_chunks(self, doc_id: int, chunks) -> int:
        vecs = self.embedder.embed([c.text for c in chunks])
        with self.db.tx() as c:
            for i, (ch, v) in enumerate(zip(chunks, vecs)):
                c.execute(
                    "INSERT INTO chunks(doc_id,idx,text,heading,page,embedding) VALUES(?,?,?,?,?,?)",
                    (doc_id, i, ch.text, ch.heading, ch.page, v.tobytes()),
                )
        self.rebuild()
        return len(chunks)

    def rebuild(self):
        rows = self.db.all(
            "SELECT c.id,c.doc_id,c.text,c.heading,c.page,c.embedding,d.title "
            "FROM chunks c JOIN documents d ON d.id=c.doc_id WHERE d.status='ready' ORDER BY c.id"
        )
        if rows:
            matrix = np.vstack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
            bm25 = BM25Okapi([content_tokens(r["text"]) or ["_"] for r in rows])
        else:
            matrix, bm25 = np.zeros((0, 1), dtype=np.float32), None
        with self._lock:
            self.rows, self.matrix, self.bm25 = rows, matrix, bm25

    # ----- search -----
    def search(self, query: str, k: int = None, pool: int = 20) -> List[Hit]:
        k = k or config.TOP_K
        with self._lock:
            rows, matrix, bm25 = self.rows, self.matrix, self.bm25
        if not rows:
            return []

        qv = self.embedder.embed([query])[0]
        dense = matrix @ qv
        qtok = content_tokens(query)
        bm = bm25.get_scores(qtok) if qtok else np.zeros(len(rows))

        dense_rank = np.argsort(-dense)[:pool]
        bm_rank = [i for i in np.argsort(-bm)[:pool] if bm[i] > 0]

        rrf = {}
        for r, i in enumerate(dense_rank):
            rrf[int(i)] = rrf.get(int(i), 0) + 1.0 / (60 + r + 1)
        for r, i in enumerate(bm_rank):
            rrf[int(i)] = rrf.get(int(i), 0) + 1.0 / (60 + r + 1)

        cands = sorted(rrf, key=lambda i: -rrf[i])[:15]
        hits = []
        for i in cands:
            r = rows[i]
            hits.append(Hit(r["id"], r["doc_id"], r["title"], r["text"], r["heading"], r["page"],
                            float(dense[i]), float(bm[i]), rrf[i]))
        return self.rerank(query, hits)[:k]

    @staticmethod
    def rerank(query: str, hits: List[Hit]) -> List[Hit]:
        """Lightweight re-ranker: query-term coverage + dense similarity.
        (Swap in a cross-encoder here for production — same interface.)"""
        qtok = set(content_tokens(query))
        for h in hits:
            ctok = set(content_tokens(h.text + " " + h.heading))
            coverage = len(qtok & ctok) / len(qtok) if qtok else 0.0
            h.score = 0.6 * coverage + 0.4 * max(h.dense, 0.0)
        return sorted(hits, key=lambda h: -h.score)

    @staticmethod
    def has_evidence(hits: List[Hit]) -> bool:
        return bool(hits) and hits[0].score >= config.MIN_EVIDENCE_SCORE

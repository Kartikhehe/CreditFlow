"""Hybrid retrieval: dense and sparse candidates, fused, then reranked.

Reciprocal rank fusion is used instead of a weighted score blend because cosine
similarity and BM25 are not on a comparable scale and normalising them requires
a corpus-dependent calibration that would have to be redone whenever a document
is added. Fusing on rank sidesteps the question entirely.

The cross-encoder reranks the fused shortlist. A bi-encoder embeds the query and
the passage separately, so it can only measure whether they occupy similar
regions of the space; the cross-encoder reads both at once and is far more
precise about which of twenty plausible passages actually answers the question.
Loading it is expensive, so the components are constructed lazily and cached.
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

import chromadb
from chromadb.utils import embedding_functions
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder

from rag.index import BM25_CORPUS_PATH, COLLECTION_NAME, EMBEDDING_MODEL, STORE

RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

DENSE_CANDIDATES = 20
SPARSE_CANDIDATES = 20
FUSED_SHORTLIST = 20
FINAL_RESULTS = 5

# Rank-fusion damping constant. Large enough that the top few ranks do not
# dominate the fused ordering outright.
RRF_K = 60


@lru_cache(maxsize=1)
def _collection():
    if not STORE.exists():
        raise FileNotFoundError(
            f"{STORE} not found. Run `python -m rag.index` to build the retrieval index."
        )
    embedder = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL
    )
    client = chromadb.PersistentClient(path=str(STORE))
    return client.get_collection(COLLECTION_NAME, embedding_function=embedder)


@lru_cache(maxsize=1)
def _corpus() -> list[dict[str, str]]:
    if not BM25_CORPUS_PATH.exists():
        raise FileNotFoundError(
            f"{BM25_CORPUS_PATH} not found. Run `python -m rag.index` first."
        )
    return json.loads(BM25_CORPUS_PATH.read_text())


@lru_cache(maxsize=1)
def _bm25() -> BM25Okapi:
    return BM25Okapi([chunk["text"].lower().split() for chunk in _corpus()])


@lru_cache(maxsize=1)
def _reranker() -> CrossEncoder:
    return CrossEncoder(RERANKER_MODEL)


def _dense_ids(query: str) -> list[str]:
    response = _collection().query(query_texts=[query], n_results=DENSE_CANDIDATES)
    return list(response["ids"][0])


def _sparse_ids(query: str) -> list[str]:
    corpus = _corpus()
    scores = _bm25().get_scores(query.lower().split())
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    return [corpus[i]["chunk_id"] for i in ranked[:SPARSE_CANDIDATES]]


def reciprocal_rank_fusion(*ranked_lists: list[str]) -> list[str]:
    fused: dict[str, float] = {}
    for ranked in ranked_lists:
        for position, chunk_id in enumerate(ranked):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (RRF_K + position + 1)
    return sorted(fused, key=lambda chunk_id: fused[chunk_id], reverse=True)


def retrieve(query: str, k: int = FINAL_RESULTS) -> list[dict[str, Any]]:
    """Return the k passages most likely to answer the query."""
    if not query.strip():
        raise ValueError("retrieval query is empty")

    by_id = {chunk["chunk_id"]: chunk for chunk in _corpus()}
    fused = reciprocal_rank_fusion(_dense_ids(query), _sparse_ids(query))
    candidates = [by_id[chunk_id] for chunk_id in fused[:FUSED_SHORTLIST] if chunk_id in by_id]
    if not candidates:
        return []

    scores = _reranker().predict([(query, chunk["text"]) for chunk in candidates])
    reranked = [
        chunk
        for _, chunk in sorted(
            zip(scores, candidates), key=lambda pair: pair[0], reverse=True
        )
    ]
    return reranked[:k]


if __name__ == "__main__":
    import sys

    question = " ".join(sys.argv[1:]) or "expectations for ongoing model monitoring"
    for passage in retrieve(question):
        print(f"[{passage['source']}] {passage['text'][:300]}\n")

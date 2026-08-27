"""Build a hybrid retrieval index over the supervisory guidance corpus.

Chunking splits on section boundaries before it splits on length. Regulatory
text is hierarchical, and a fixed-width window will routinely separate a rule
from the clause that qualifies it -- which produces answers that are fluent,
sourced, and wrong, because the retrieved passage said "banks must" without the
following sentence's exemption.

Both halves of the index are built here. The dense side handles paraphrase; the
sparse side handles the exact terminology that supervisory documents turn on,
where an embedding treats two adjacent phrases as near-identical and a
practitioner does not.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions
from pypdf import PdfReader

from src.paths import DOCS_CORPUS, PROJECT_ROOT

STORE = PROJECT_ROOT / "chroma_db"
COLLECTION_NAME = "credit_policy"
BM25_CORPUS_PATH = STORE / "bm25_corpus.json"

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DISTANCE_METRIC = "cosine"

CHUNK_WORDS = 800
OVERLAP_WORDS = 150
MIN_CHUNK_WORDS = 40

BATCH_SIZE = 256

# Matches roman-numeral headings, decimal section numbers, and all-caps titles,
# which between them cover the heading styles used across the corpus.
SECTION_PATTERN = re.compile(r"\n(?=(?:[IVX]+\.|\d+\.\d*\s+[A-Z]|[A-Z][A-Z ]{6,}\n))")
BLANK_RUN = re.compile(r"\n{3,}")


def read_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def chunk_text(text: str, source: str) -> list[dict[str, str]]:
    text = BLANK_RUN.sub("\n\n", text)

    pieces: list[str] = []
    for section in SECTION_PATTERN.split(text):
        words = section.split()
        if len(words) <= CHUNK_WORDS:
            pieces.append(section)
            continue
        step = CHUNK_WORDS - OVERLAP_WORDS
        for start in range(0, len(words), step):
            pieces.append(" ".join(words[start : start + CHUNK_WORDS]))

    return [
        {"text": piece.strip(), "source": source, "chunk_id": f"{source}::{position}"}
        for position, piece in enumerate(pieces)
        if len(piece.split()) > MIN_CHUNK_WORDS
    ]


def main() -> None:
    documents = sorted(DOCS_CORPUS.glob("*.pdf"))
    if not documents:
        raise FileNotFoundError(
            f"no PDFs found in {DOCS_CORPUS}. Add the supervisory guidance corpus "
            "described in docs/data.md before building the index."
        )

    chunks: list[dict[str, str]] = []
    for document in documents:
        chunks.extend(chunk_text(read_pdf(document), document.stem))
    if not chunks:
        raise ValueError(
            "text extraction produced no usable chunks; the PDFs may be scanned "
            "images rather than text, which this pipeline does not OCR"
        )
    print(f"{len(chunks)} chunks from {len(documents)} documents")

    STORE.mkdir(parents=True, exist_ok=True)
    embedder = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBEDDING_MODEL
    )
    client = chromadb.PersistentClient(path=str(STORE))
    if COLLECTION_NAME in {c.name for c in client.list_collections()}:
        client.delete_collection(COLLECTION_NAME)
    collection = client.create_collection(
        COLLECTION_NAME,
        embedding_function=embedder,
        metadata={"hnsw:space": DISTANCE_METRIC},
    )

    for start in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[start : start + BATCH_SIZE]
        collection.add(
            ids=[chunk["chunk_id"] for chunk in batch],
            documents=[chunk["text"] for chunk in batch],
            metadatas=[{"source": chunk["source"]} for chunk in batch],
        )

    BM25_CORPUS_PATH.write_text(json.dumps(chunks))
    print(f"index written to {STORE}")


if __name__ == "__main__":
    main()

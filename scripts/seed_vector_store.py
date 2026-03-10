#!/usr/bin/env python3
"""
Qdrant seeding script — load tenant documents into the vector store.

Usage:
    python scripts/seed_vector_store.py \\
        --collection iroko_knowledge \\
        --docs-dir ./data/iroko/

What it does:
  1. Reads all .md and .txt files from the given directory.
  2. Chunks each file into paragraphs (double-newline split).
  3. Embeds each chunk using LiteLLM (text-embedding-3-small by default).
  4. Upserts to Qdrant — safe to re-run (idempotent via point IDs).

Chunking strategy:
  Simple paragraph splitting for now.
  Each non-empty paragraph becomes one Qdrant point.
  Phase 5 will add smarter chunking (sliding window, sentence-aware).

Idempotency:
  Point IDs are a hash of (collection, chunk_index, text[:50]).
  Re-running with the same files updates existing points — no duplicates.

Environment:
  QDRANT_URL            — Qdrant server URL (default: http://localhost:6333)
  OPENAI_API_KEY        — for text-embedding-3-small (or set LITELLM_EMBED_MODEL)
  LITELLM_EMBED_MODEL   — override embedding model (default: text-embedding-3-small)

Example:
    # Seed Iroko FAQ documents
    QDRANT_URL=http://localhost:6333 \\
    OPENAI_API_KEY=sk-... \\
    python scripts/seed_vector_store.py \\
        --collection iroko_knowledge \\
        --docs-dir ./data/iroko/

    # Dry run — chunk and count without uploading
    python scripts/seed_vector_store.py \\
        --collection iroko_knowledge \\
        --docs-dir ./data/iroko/ \\
        --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import os
import sys
import uuid
from pathlib import Path

# ─── Chunking ─────────────────────────────────────────────────────────────────

def chunk_file(path: Path) -> list[str]:
    """
    Split a file into chunks at double-newline boundaries.

    Each paragraph (block of text separated by blank lines) becomes one chunk.
    Chunks shorter than 20 characters are skipped (headers, blank lines, etc.).
    """
    text = path.read_text(encoding="utf-8")
    raw_chunks = text.split("\n\n")
    return [c.strip() for c in raw_chunks if len(c.strip()) >= 20]


def chunk_csv_file(path: Path) -> list[str]:
    """
    Convert a CSV product file into text chunks — one chunk per row.

    Expected columns (Hebrew headers): שם המוצר, תיאור, מתי להמליץ עליו, קישור למוצר
    Each row is formatted as a short product description block.
    """
    chunks = []
    with path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("שם המוצר", "").strip()
            desc = row.get("תיאור", "").strip()
            when = row.get("מתי להמליץ עליו", "").strip()
            link = row.get("קישור למוצר", "").strip()
            if not name:
                continue
            parts = [f"## {name}"]
            if desc:
                parts.append(desc)
            if when:
                parts.append(f"מתי להמליץ: {when}")
            if link:
                parts.append(f"קישור: {link}")
            chunks.append("\n".join(parts))
    return chunks


def chunk_directory(docs_dir: Path) -> list[tuple[str, str]]:
    """
    Read all .md, .txt, and .csv files in a directory and return (source, chunk) pairs.
    """
    chunks = []
    for ext in ("*.md", "*.txt"):
        for file_path in sorted(docs_dir.glob(ext)):
            file_chunks = chunk_file(file_path)
            for chunk in file_chunks:
                chunks.append((file_path.name, chunk))
    for file_path in sorted(docs_dir.glob("*.csv")):
        file_chunks = chunk_csv_file(file_path)
        for chunk in file_chunks:
            chunks.append((file_path.name, chunk))
    return chunks


def make_point_id(collection: str, source: str, chunk_idx: int) -> str:
    """
    Deterministic UUID based on (collection, source file, chunk index).
    Re-seeding the same file produces the same point IDs → upsert is idempotent.
    """
    key = f"{collection}:{source}:{chunk_idx}"
    h = hashlib.md5(key.encode()).hexdigest()
    return str(uuid.UUID(h))


# ─── Embedding ────────────────────────────────────────────────────────────────

async def embed_batch(texts: list[str], model: str) -> list[list[float]]:
    """
    Embed a batch of texts using LiteLLM.

    Returns a list of embedding vectors (one per text).
    """
    import litellm

    response = await litellm.aembedding(model=model, input=texts)
    return [item["embedding"] for item in response.data]


# ─── Qdrant upsert ────────────────────────────────────────────────────────────

async def ensure_collection(client, collection: str, vector_size: int) -> None:
    """Create the Qdrant collection if it doesn't exist."""
    from qdrant_client.models import Distance, VectorParams

    existing = await client.get_collections()
    names = [c.name for c in existing.collections]
    if collection not in names:
        await client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )
        print(f"Created collection: {collection}")
    else:
        print(f"Collection exists: {collection}")


async def upsert_chunks(
    client,
    collection: str,
    chunks: list[tuple[str, str]],  # (source, text)
    embed_model: str,
    batch_size: int = 50,
) -> None:
    """
    Embed and upsert all chunks into Qdrant in batches.

    Args:
        client:      AsyncQdrantClient
        collection:  Collection name
        chunks:      (source_file, text) pairs
        embed_model: LiteLLM embedding model string
        batch_size:  How many chunks to embed at once (OpenAI limit: 2048)
    """
    from qdrant_client.models import PointStruct

    total = len(chunks)
    uploaded = 0

    for batch_start in range(0, total, batch_size):
        batch = chunks[batch_start : batch_start + batch_size]
        texts = [text for _, text in batch]

        print(f"Embedding batch {batch_start // batch_size + 1} ({len(texts)} chunks)...")
        vectors = await embed_batch(texts, embed_model)

        points = [
            PointStruct(
                id=make_point_id(collection, source, batch_start + i),
                vector=vector,
                payload={"text": text, "source": source},
            )
            for i, ((source, text), vector) in enumerate(zip(batch, vectors))
        ]

        await client.upsert(collection_name=collection, points=points)
        uploaded += len(points)
        print(f"  Uploaded {uploaded}/{total} chunks")

    print(f"\nDone. {uploaded} chunks in '{collection}'.")


# ─── Main ─────────────────────────────────────────────────────────────────────

async def main(collection: str, docs_dir: Path, dry_run: bool, embed_model: str) -> None:
    # Step 1: collect and chunk all documents
    print(f"Reading documents from: {docs_dir}")
    chunks = chunk_directory(docs_dir)

    if not chunks:
        print("No .md, .txt, or .csv files found. Nothing to do.")
        sys.exit(0)

    print(f"Found {len(chunks)} chunks across {len({s for s, _ in chunks})} files")

    if dry_run:
        for i, (source, text) in enumerate(chunks[:5]):
            print(f"\n[{i}] {source}: {text[:80]}...")
        print(f"\n(dry-run) Would upload {len(chunks)} chunks to '{collection}'")
        return

    # Step 2: connect to Qdrant
    from qdrant_client import AsyncQdrantClient

    qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    client = AsyncQdrantClient(url=qdrant_url)

    # Step 3: get vector size from a test embedding
    print(f"Probing embedding size for model: {embed_model}")
    import litellm
    probe = await litellm.aembedding(model=embed_model, input=["probe"])
    vector_size = len(probe.data[0]["embedding"])
    print(f"Vector size: {vector_size}")

    # Step 4: ensure collection exists
    await ensure_collection(client, collection, vector_size)

    # Step 5: embed and upsert
    await upsert_chunks(client, collection, chunks, embed_model)

    await client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed Qdrant with tenant documents")
    parser.add_argument("--collection", required=True, help="Qdrant collection name (e.g. iroko_knowledge)")
    parser.add_argument("--docs-dir", required=True, type=Path, help="Directory with .md/.txt/.csv files")
    parser.add_argument("--dry-run", action="store_true", help="Print chunks without uploading")
    parser.add_argument(
        "--embed-model",
        default=os.environ.get("LITELLM_EMBED_MODEL", "text-embedding-3-small"),
        help="LiteLLM embedding model (default: text-embedding-3-small)",
    )
    args = parser.parse_args()

    if not args.docs_dir.is_dir():
        print(f"Error: {args.docs_dir} is not a directory")
        sys.exit(1)

    asyncio.run(
        main(
            collection=args.collection,
            docs_dir=args.docs_dir,
            dry_run=args.dry_run,
            embed_model=args.embed_model,
        )
    )

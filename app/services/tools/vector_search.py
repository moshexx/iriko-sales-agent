"""
Vector search tool — query the tenant's Qdrant collection for relevant knowledge.

How it works:
  1. Embed the query text using LiteLLM (same model abstraction as LLM calls).
  2. Search the tenant's Qdrant collection for the top-k most similar chunks.
  3. Return the chunk texts for injection into the LLM prompt.

Why per-tenant collections?
  Each tenant has their own Qdrant collection (e.g. "iroko_faq", "dng_protocols").
  This gives full isolation — Iroko's knowledge never leaks to DNG's agent.

Phase 4 will add:
  - Seeding scripts to populate Qdrant from tenant documents
  - Metadata filtering (e.g. filter by document type or language)
  - Reranking (cross-encoder) for better relevance
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# Qdrant client is lazily initialized to avoid connection at import time
_qdrant_client = None


def _get_qdrant():
    global _qdrant_client
    if _qdrant_client is None:
        from qdrant_client import AsyncQdrantClient

        url = os.environ.get("QDRANT_URL", "http://localhost:6333")
        _qdrant_client = AsyncQdrantClient(url=url)
    return _qdrant_client


async def vector_search(
    query: str,
    collection: str,
    top_k: int = 5,
) -> list[str]:
    """
    Search the tenant's Qdrant collection and return the top-k chunk texts.

    Args:
        query:      The user's message (will be embedded).
        collection: The tenant's Qdrant collection name.
        top_k:      How many results to return.

    Returns:
        List of relevant text chunks (strings), ordered by relevance.
        Empty list if the collection is empty or an error occurs.
    """
    try:
        import litellm

        # Step 1: embed the query
        embed_response = await litellm.aembedding(
            model="text-embedding-3-small",   # OpenAI default; configurable later
            input=[query],
        )
        vector = embed_response.data[0]["embedding"]

        # Step 2: search Qdrant (qdrant-client >= 1.7 uses query_points)
        client = _get_qdrant()
        response = await client.query_points(
            collection_name=collection,
            query=vector,
            limit=top_k,
            with_payload=True,
        )

        # Step 3: extract text from payload
        chunks = []
        for hit in response.points:
            text = hit.payload.get("text", "") if hit.payload else ""
            if text:
                chunks.append(text)

        logger.debug(
            "vector_search collection=%s query_len=%d results=%d",
            collection,
            len(query),
            len(chunks),
        )
        return chunks

    except Exception:
        # If Qdrant is down or collection doesn't exist yet, don't crash the agent.
        # Phase 4 will add proper error handling and alerting.
        logger.exception("vector_search failed collection=%s", collection)
        return []

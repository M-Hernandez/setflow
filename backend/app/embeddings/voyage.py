"""Voyage AI embedding wrapper for setflow.

Thin async wrapper around voyageai.AsyncClient with batch support
and input_type differentiation (document vs query).

Model: voyage-3 (1024 dimensions)
Rate limit: 300 RPM, 1M tokens/min on free tier
Batch size: up to 128 texts per API call
"""

import logging

import voyageai

from app.config import settings

logger = logging.getLogger(__name__)

MODEL = "voyage-3"
DIMENSIONS = 1024
BATCH_SIZE = 128


class VoyageEmbedder:
    """Async Voyage AI embedder with batch support."""

    def __init__(self) -> None:
        if not settings.voyage_api_key:
            raise RuntimeError("VOYAGE_API_KEY is not set")
        self._client = voyageai.AsyncClient(api_key=settings.voyage_api_key)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts for storage (document input_type).

        Automatically batches into chunks of BATCH_SIZE.
        """
        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i : i + BATCH_SIZE]
            result = await self._client.embed(
                texts=batch,
                model=MODEL,
                input_type="document",
            )
            all_embeddings.extend(result.embeddings)
            logger.info(
                "Embedded batch %d-%d (%d texts)",
                i,
                i + len(batch),
                len(batch),
            )
        return all_embeddings

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query text for search (query input_type)."""
        result = await self._client.embed(
            texts=[text],
            model=MODEL,
            input_type="query",
        )
        return result.embeddings[0]

"""Throwaway routes to verify Anthropic + Voyage SDK wiring."""

import anthropic
import voyageai
from fastapi import APIRouter

from app.config import settings

router = APIRouter()


@router.get("/test-claude")
async def test_claude():
    if not settings.anthropic_api_key:
        return {"status": "error", "detail": "ANTHROPIC_API_KEY is not set"}

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=64,
            messages=[{"role": "user", "content": "Say hello in one sentence."}],
        )
        return {
            "status": "ok",
            "model": message.model,
            "response": message.content[0].text,
        }
    except anthropic.APIError as e:
        return {"status": "error", "detail": str(e)}


@router.get("/test-embed")
async def test_embed():
    if not settings.voyage_api_key:
        return {"status": "error", "detail": "VOYAGE_API_KEY is not set"}

    client = voyageai.AsyncClient(api_key=settings.voyage_api_key)
    try:
        result = await client.embed(
            texts=["Melodic techno with deep pads and driving bass"],
            model="voyage-3",
        )
        vector = result.embeddings[0]
        return {
            "status": "ok",
            "model": "voyage-3",
            "dimensions": len(vector),
            "preview": vector[:5],
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}

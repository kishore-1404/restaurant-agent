# core/embeddings.py
"""
Unified embedding interface.
Supports Gemini API, llama.cpp server, Ollama, and generic OpenAI-compatible APIs.
"""

from __future__ import annotations
import logging
import asyncio
from typing import Optional
from config import settings

logger = logging.getLogger(__name__)


async def generate_embedding(text: str) -> Optional[list[float]]:
    """Generate embedding for a single text string."""
    embeddings = await generate_embeddings_batch([text])
    return embeddings[0] if embeddings else None


async def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """Batch generate embeddings for a list of strings."""
    if not texts:
        return []

    provider = settings.embedding_provider.lower()

    if provider == "gemini":
        from google import genai
        from google.genai import types
        api_key = settings.embedding_api_key or settings.gemini_api_key
        if not api_key:
            raise ValueError("No Gemini API key found in settings (embedding_api_key or gemini_api_key)")

        client = genai.Client(api_key=api_key)
        results = []
        for text_str in texts:
            result = await client.aio.models.embed_content(
                model=settings.embedding_model,
                contents=text_str,
                config=types.EmbedContentConfig(
                    output_dimensionality=768
                )
            )
            results.append(result.embeddings[0].values)
            await asyncio.sleep(0.05)  # gentle rate limiting
        return results

    elif provider in ("openai_compatible", "llamacpp", "ollama"):
        import httpx
        
        # Resolve endpoint URL based on provider
        base_url = settings.embedding_base_url
        if not base_url:
            if provider == "llamacpp":
                # For llamacpp, default to llamacpp_base_url or local port 8081 if configured
                base_url = settings.llamacpp_base_url
            elif provider == "ollama":
                base_url = settings.ollama_base_url

        if not base_url:
            raise ValueError(f"No base URL configured for embedding provider: {provider}")

        # Ensure base_url ends with /v1 if using llamacpp/openai-style path
        if not base_url.endswith("/v1") and provider in ("openai_compatible", "llamacpp"):
            # Strip trailing slash first if any
            base_url = base_url.rstrip("/")
            if not base_url.endswith("/v1"):
                base_url = f"{base_url}/v1"

        api_key = settings.embedding_api_key or "none"
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{base_url}/embeddings",
                json={"input": texts, "model": settings.embedding_model},
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            # Sort by index to preserve order
            return [d["embedding"] for d in sorted(data, key=lambda x: x.get("index", 0))]

    else:
        raise ValueError(f"Unknown embedding provider: {provider}")

# db/embedding_gen.py
"""
Generate and store embeddings for:
1. All menu items (semantic search)
2. All intent definitions (pgvector pre-dispatch)

Run once after seeding:
    uv run python -m db.embedding_gen

Re-run when: new menu items added, intent definitions changed.
"""

import asyncio
import logging
from sqlalchemy import text, select
from db.base import AsyncSessionFactory
from db.models import MenuItem
from config import settings

logger = logging.getLogger(__name__)


async def _embed_batch(texts: list[str]) -> list[list[float]]:
    """Batch embedding generation — rate-limited, with retry."""
    from core.embeddings import generate_embeddings_batch
    return await generate_embeddings_batch(texts)


def _item_text(item: MenuItem) -> str:
    """
    Text to embed for a menu item.
    Combines semantic-rich fields. Does NOT include ingredients/allergens
    (those are for structured queries, not semantic similarity).
    """
    parts = [item.name]
    if item.description:
        parts.append(item.description)
    if item.tags:
        parts.append("Tags: " + ", ".join(item.tags))
    # Category context helps: "Mains: BBQ Ribs" vs "Drinks: Coke"
    return ". ".join(parts)


async def embed_menu_items():
    """Embed all menu items that don't have embeddings yet."""
    async with AsyncSessionFactory() as db:
        result = await db.execute(
            select(MenuItem).where(MenuItem.embedding.is_(None))
        )
        items = result.scalars().all()

        if not items:
            logger.info("All menu items already have embeddings.")
            return

        logger.info(f"Generating embeddings for {len(items)} menu items...")

        # Process in batches of 20
        batch_size = 20
        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            texts = [_item_text(item) for item in batch]
            embeddings = await _embed_batch(texts)

            for item, embedding in zip(batch, embeddings):
                await db.execute(
                    text("UPDATE menu_items SET embedding = CAST(:emb AS vector) WHERE id = :id"),
                    {"emb": "[" + ",".join(str(v) for v in embedding) + "]", "id": item.id}
                )

            await db.commit()
            logger.info(f"  Embedded items {i+1}–{min(i+batch_size, len(items))}")

    logger.info("Menu item embeddings complete.")


async def embed_intent_definitions():
    """Embed all intent definitions that don't have embeddings yet."""
    async with AsyncSessionFactory() as db:
        result = await db.execute(
            text("SELECT id, example_query FROM intent_definitions WHERE embedding IS NULL")
        )
        rows = result.fetchall()

        if not rows:
            logger.info("All intent definitions already have embeddings.")
            return

        logger.info(f"Generating embeddings for {len(rows)} intent definitions...")

        texts = [row.example_query for row in rows]
        embeddings = await _embed_batch(texts)

        for row, embedding in zip(rows, embeddings):
            await db.execute(
                text("UPDATE intent_definitions SET embedding = CAST(:emb AS vector) WHERE id = :id"),
                {"emb": "[" + ",".join(str(v) for v in embedding) + "]", "id": row.id}
            )

        await db.commit()
        logger.info("Intent definition embeddings complete.")


async def run_embedding():
    await embed_menu_items()
    await embed_intent_definitions()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_embedding())

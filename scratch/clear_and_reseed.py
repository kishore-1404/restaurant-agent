# scratch/clear_and_reseed.py
import asyncio
import logging
from sqlalchemy import text
from db.base import engine, Base
# Import models so they register with Base.metadata
from db.models import (
    Restaurant, MenuCategory, MenuItem,
    PriceRule, OrderRule, CustomerProfile,
    Order, OrderItem, ItemAffinity, IntentDefinition
)
from db.migrations import run_custom_migrations
from db.seed import run_seed
from db.embedding_gen import embed_menu_items, embed_intent_definitions

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_reset():
    # 1. Drop materialized view first (due to dependencies)
    logger.info("Dropping materialized views and dependent objects...")
    async with engine.begin() as conn:
        await conn.execute(text("DROP MATERIALIZED VIEW IF EXISTS top_pairings CASCADE;"))
        await conn.execute(text("DROP VIEW IF EXISTS active_price_rules CASCADE;"))
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE;"))

    # 2. Drop all tables
    logger.info("Dropping all database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    # 3. Recreate tables
    logger.info("Creating tables using Base.metadata.create_all...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 4. Apply custom SQL migrations (RLS, triggers, etc. on core tables)
    logger.info("Running custom triggers and policies migration from db/migrations.py...")
    await run_custom_migrations()

    # 5. Apply migrations_v2.sql (contains materialized views, triggers, RLS policies for v2 tables)
    logger.info("Running migrations_v2.sql...")
    with open("db/migrations_v2.sql", "r") as f:
        v2_sql = f.read()
    
    async with engine.connect() as conn:
        raw_dbapi_conn = await conn.get_raw_connection()
        raw_conn = raw_dbapi_conn.driver_connection
        await raw_conn.execute(v2_sql)

    # 6. Apply migrations_intelligence.sql (contains our intelligence SQL functions like get_active_offers)
    logger.info("Running migrations_intelligence.sql...")
    with open("db/migrations_intelligence.sql", "r") as f:
        intelligence_sql = f.read()
    
    async with engine.connect() as conn:
        raw_dbapi_conn = await conn.get_raw_connection()
        raw_conn = raw_dbapi_conn.driver_connection
        await raw_conn.execute(intelligence_sql)

    # 7. Run seed.py to seed the database
    logger.info("Running seed script...")
    await run_seed()

    # 8. Generate embeddings for menu items and intent definitions
    logger.info("Generating embeddings for menu items...")
    await embed_menu_items()
    logger.info("Generating embeddings for intent definitions...")
    await embed_intent_definitions()

    logger.info("Database completely cleared, re-seeded, and embedded successfully!")

if __name__ == "__main__":
    asyncio.run(run_reset())

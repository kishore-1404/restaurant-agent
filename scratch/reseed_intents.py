# scratch/reseed_intents.py
import asyncio
import logging
from db.intent_seed import seed_intent_definitions
from db.embedding_gen import embed_intent_definitions

async def main():
    logging.basicConfig(level=logging.INFO)
    print("Force seeding intent definitions...")
    await seed_intent_definitions()
    print("Generating embeddings for new intents...")
    await embed_intent_definitions()
    print("Done!")

if __name__ == "__main__":
    asyncio.run(main())

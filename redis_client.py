import json
import logging
import redis.asyncio as aioredis
from config import settings

logger = logging.getLogger(__name__)

# Single shared connection pool
redis_pool = aioredis.ConnectionPool.from_url(
    settings.redis_url,
    max_connections=20,
    decode_responses=True,
)


def get_redis() -> aioredis.Redis:
    return aioredis.Redis(connection_pool=redis_pool)


# ── Key conventions ────────────────────────────────────────────
# menu:{restaurant_id}            → full menu JSON, TTL 5 min
# session:{session_id}            → LangGraph state JSON
# ratelimit:{api_key}:{minute}    → request count integer
# lock:order:{order_id}           → distributed lock
# popular:{restaurant_id}         → sorted set (item_id → score)


class CacheKeys:
    @staticmethod
    def menu(restaurant_id: int) -> str:
        return f"menu:{restaurant_id}"

    @staticmethod
    def session(session_id: str) -> str:
        return f"session:{session_id}"

    @staticmethod
    def popular(restaurant_id: int) -> str:
        return f"popular:{restaurant_id}"

    @staticmethod
    def order_lock(order_id: int) -> str:
        return f"lock:order:{order_id}"


class RedisCache:
    def __init__(self):
        from monitoring.hooks import InstrumentedRedis
        self.client = InstrumentedRedis(get_redis())

    async def get_json(self, key: str) -> dict | None:
        try:
            value = await self.client.get(key)
            return json.loads(value) if value else None
        except Exception as e:
            logger.error(f"Redis GET error for {key}: {e}")
            return None

    async def set_json(self, key: str, value: dict, ttl: int = None) -> bool:
        try:
            serialized = json.dumps(value, default=str)
            if ttl:
                await self.client.setex(key, ttl, serialized)
            else:
                await self.client.set(key, serialized)
            return True
        except Exception as e:
            logger.error(f"Redis SET error for {key}: {e}")
            return False

    async def delete(self, key: str):
        await self.client.delete(key)

    async def acquire_lock(self, key: str, ttl_ms: int = 5000) -> bool:
        """Distributed lock using SET NX PX — atomic, no race conditions."""
        result = await self.client.set(key, "1", nx=True, px=ttl_ms)
        return result is True

    async def release_lock(self, key: str):
        await self.client.delete(key)

    async def increment_popular(self, restaurant_id: int, item_id: int, by: int = 1):
        """Track popular items via Redis sorted set."""
        key = CacheKeys.popular(restaurant_id)
        await self.client.zincrby(key, by, str(item_id))

    async def get_popular_items(self, restaurant_id: int, limit: int = 5) -> list[int]:
        """Get top N most ordered item IDs."""
        key = CacheKeys.popular(restaurant_id)
        results = await self.client.zrevrange(key, 0, limit - 1)
        return [int(item_id) for item_id in results]


cache = RedisCache()

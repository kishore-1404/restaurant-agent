from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import Restaurant


class RestaurantService:

    @staticmethod
    async def get_by_id(db: AsyncSession, restaurant_id: int) -> Restaurant | None:
        result = await db.execute(
            select(Restaurant).where(
                Restaurant.id == restaurant_id,
                Restaurant.is_active == True
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list_active(db: AsyncSession) -> list[Restaurant]:
        result = await db.execute(
            select(Restaurant)
            .where(Restaurant.is_active == True)
            .order_by(Restaurant.name)
        )
        return list(result.scalars().all())

    @staticmethod
    async def set_tenant_context(db: AsyncSession, restaurant_id: int):
        """
        Set the PostgreSQL session variable that Row-Level Security policies read.
        MUST be called before any tenant-scoped query.
        """
        await db.execute(
            text("SELECT set_config('app.restaurant_id', :rid, true)"),
            {"rid": str(restaurant_id)}
        )

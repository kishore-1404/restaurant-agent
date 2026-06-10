from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import CustomerProfile


class ProfileService:

    @staticmethod
    async def get_by_phone(db: AsyncSession, phone: str) -> CustomerProfile | None:
        result = await db.execute(
            select(CustomerProfile).where(CustomerProfile.phone == phone)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_order_history_summary(
        db: AsyncSession, phone: str, restaurant_id: int, limit: int = 5
    ) -> str:
        """Returns a human-readable summary: 'Usually orders: BBQ Ribs, Loaded Fries'"""
        result = await db.execute(
            text("""
                SELECT oi.name_snapshot, count(*) AS freq
                FROM   order_items oi
                JOIN   orders o ON o.id = oi.order_id
                WHERE  o.customer_phone = :phone
                  AND  o.restaurant_id  = :rid
                  AND  o.status         = 'completed'
                GROUP  BY oi.name_snapshot
                ORDER  BY freq DESC
                LIMIT  :lim
            """),
            {"phone": phone, "rid": restaurant_id, "lim": limit}
        )
        rows = result.fetchall()
        if not rows:
            return ""
        top = ", ".join(r.name_snapshot for r in rows)
        return f"Frequent orders at this restaurant: {top}"

    @staticmethod
    async def upsert_profile(db: AsyncSession, profile_data: dict) -> CustomerProfile:
        """Create or update profile. Uses phone as the unique key."""
        phone = profile_data.get("phone")
        if not phone:
            raise ValueError("Phone number is required for profile upsert.")

        result = await db.execute(
            select(CustomerProfile).where(CustomerProfile.phone == phone)
        )
        profile = result.scalar_one_or_none()

        if profile:
            # Update fields
            for key, val in profile_data.items():
                if hasattr(profile, key) and key != "id":
                    setattr(profile, key, val)
        else:
            profile = CustomerProfile(**profile_data)
            db.add(profile)

        await db.flush()
        return profile

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class AllergenService:

    @staticmethod
    async def check_item_allergens(
        db: AsyncSession,
        item_id: int,
        customer_allergens: list[str],
    ) -> list[str]:
        """Return list of allergens the item has that match the customer's list."""
        result = await db.execute(
            text("SELECT allergens FROM menu_items WHERE id = :id"),
            {"id": item_id}
        )
        row = result.fetchone()
        if not row or not row.allergens:
            return []
        return list(set(row.allergens) & set(customer_allergens))

    @staticmethod
    async def get_safe_items(
        db: AsyncSession,
        restaurant_id: int,
        allergens_to_avoid: list[str],
        dietary_restrictions: list[str],
    ) -> list[int]:
        """Return item IDs that are safe for this customer."""
        # Build exclusion clause from allergens
        # tags is JSONB, so we use the '?' operator to check if tags contain the dietary restriction
        result = await db.execute(
            text("""
                SELECT id FROM menu_items
                WHERE  restaurant_id = :rid
                  AND  is_available  = true
                  AND  NOT (allergens && (:allergens)::varchar[])
                  AND  (:vegan = false OR tags ? 'vegan')
                  AND  (:vegetarian = false OR tags ? 'vegetarian' OR tags ? 'vegan')
                  AND  (:gluten_free = false OR tags ? 'gluten-free')
            """),
            {
                "rid": restaurant_id,
                "allergens": allergens_to_avoid,
                "vegan":       "vegan" in dietary_restrictions,
                "vegetarian":  "vegetarian" in dietary_restrictions,
                "gluten_free": "gluten-free" in dietary_restrictions,
            }
        )
        return [row.id for row in result.fetchall()]

    @staticmethod
    def format_allergen_warning(item_name: str, allergens: list[str]) -> str:
        if not allergens:
            return ""
        allergen_str = ", ".join(allergens)
        return f"Heads up — {item_name} contains {allergen_str}."

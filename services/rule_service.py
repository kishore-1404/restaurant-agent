from decimal import Decimal
from datetime import datetime, time
from sqlalchemy import select, or_, cast, Integer, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from db.models import PriceRule, OrderRule, MenuItem, Order, OrderItem


class RuleService:

    @staticmethod
    async def get_active_price_rules(
        db: AsyncSession, restaurant_id: int, at: datetime
    ) -> list[PriceRule]:
        # Query rules for the restaurant
        result = await db.execute(
            select(PriceRule)
            .where(
                PriceRule.restaurant_id == restaurant_id,
                PriceRule.is_active == True
            )
            .order_by(PriceRule.priority.desc())
        )
        rules = result.scalars().all()

        active_rules = []
        current_date = at.date()
        current_time = at.time()
        pg_day = int(at.strftime('%w'))  # 0=Sun..6=Sat

        for rule in rules:
            if rule.valid_date_from and rule.valid_date_from > current_date:
                continue
            if rule.valid_date_until and rule.valid_date_until < current_date:
                continue
            if rule.valid_days is not None and pg_day not in rule.valid_days:
                continue
            if rule.valid_from and rule.valid_from > current_time:
                continue
            if rule.valid_until and rule.valid_until < current_time:
                continue
            active_rules.append(rule)

        return active_rules

    @staticmethod
    def apply_price_rules(
        item: MenuItem | dict, rules: list[PriceRule]
    ) -> tuple[Decimal, list[str]]:
        """
        Returns (final_price, list_of_applied_rule_labels).
        Applies highest-priority matching rule only.
        """
        item_id = item.id if hasattr(item, "id") else item.get("id")
        category_id = item.category_id if hasattr(item, "category_id") else item.get("category_id")
        price = item.price if hasattr(item, "price") else item.get("price")

        original = Decimal(str(price))
        for rule in rules:
            # Check if this rule applies to this item
            if rule.applies_to == "all":
                pass  # applies to everything
            elif rule.applies_to == "category" and category_id not in rule.applies_to_ids:
                continue
            elif rule.applies_to == "item" and item_id not in rule.applies_to_ids:
                continue

            if rule.rule_type == "percentage_off":
                return original * (1 - rule.value / 100), [rule.label]
            elif rule.rule_type == "fixed_off":
                return max(original - rule.value, Decimal("0")), [rule.label]
            elif rule.rule_type == "fixed_price":
                return rule.value, [rule.label]

        return original, []

    @staticmethod
    async def get_order_rules(db: AsyncSession, restaurant_id: int) -> list[OrderRule]:
        result = await db.execute(
            select(OrderRule).where(
                OrderRule.restaurant_id == restaurant_id,
                OrderRule.is_active == True
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def validate_order_rules(db: AsyncSession, order_id: int, restaurant_id: int) -> dict:
        """
        Validate the order against all active rules.
        Returns: {"valid": bool, "violations": [{"rule": str, "message": str, "suggestion": str}]}
        """
        # Load rules
        rules = await RuleService.get_order_rules(db, restaurant_id)
        
        # Load order with items
        result = await db.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.id == order_id)
        )
        order = result.scalar_one_or_none()
        if not order:
            return {"valid": True, "violations": []}

        violations = []
        for rule in rules:
            if rule.rule_type == "min_total":
                if order.total < rule.value:
                    violations.append({
                        "rule": rule.rule_type,
                        "message": rule.error_message or f"Order total ${order.total:.2f} is under the minimum of ${rule.value:.2f}.",
                        "suggestion": "How about adding a dessert or side to meet the minimum?"
                    })
            elif rule.rule_type == "max_total":
                if order.total > rule.value:
                    violations.append({
                        "rule": rule.rule_type,
                        "message": rule.error_message or f"Order total ${order.total:.2f} exceeds the maximum of ${rule.value:.2f}.",
                        "suggestion": "You could remove an item or choose a smaller size to stay under the limit."
                    })
            elif rule.rule_type == "max_qty_per_item":
                for item in order.items:
                    if item.quantity > rule.value:
                        violations.append({
                            "rule": rule.rule_type,
                            "message": rule.error_message or f"Quantity of {item.name_snapshot} ({item.quantity}) exceeds the limit of {int(rule.value)}.",
                            "suggestion": f"Would you like to adjust the quantity of {item.name_snapshot} to {int(rule.value)}?"
                        })
            elif rule.rule_type == "max_discounted_items":
                # Check items that have a discount (original_price is set and is different from price_snapshot)
                discounted_qty = sum(
                    item.quantity for item in order.items
                    if item.original_price is not None and item.original_price != item.price_snapshot
                )
                if discounted_qty > rule.value:
                    violations.append({
                        "rule": rule.rule_type,
                        "message": rule.error_message or f"Maximum of {int(rule.value)} discounted items are allowed.",
                        "suggestion": f"Note: Only {int(rule.value)} of your items will receive the promotional discount; the rest will be charged at standard price."
                    })

        return {
            "valid": len(violations) == 0,
            "violations": violations
        }

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from db.models import Order, OrderItem, MenuItem
from redis_client import cache, CacheKeys
from decimal import Decimal


class OrderService:

    @staticmethod
    async def _get_session_id(db: AsyncSession, order_id: int) -> str:
        for obj in db.identity_map.values():
            if isinstance(obj, Order) and obj.id == order_id:
                return obj.session_id
        res = await db.execute(select(Order.session_id).where(Order.id == order_id))
        return res.scalar_one_or_none() or ""

    @staticmethod
    async def create_order(
        db: AsyncSession,
        restaurant_id: int,
        session_id: str,
        customer_name: str = None,
        customer_phone: str = None,
        language_code: str = "en"
    ) -> Order:
        order = Order(
            restaurant_id=restaurant_id,
            session_id=session_id,
            customer_name=customer_name,
            customer_phone=customer_phone,
            language_code=language_code,
            status="pending",
            total=Decimal("0.00"),
            discount_total=Decimal("0.00")
        )
        db.add(order)
        await db.flush()   # get the id without committing

        from monitoring.hooks import emit_order_event
        emit_order_event("CREATE", order.id, session_id, {"restaurant_id": restaurant_id})

        return order

    @staticmethod
    async def add_item(
        db: AsyncSession,
        order_id: int,
        menu_item: MenuItem,
        quantity: int = 1,
        modifiers_chosen: dict = None,
        price_snapshot: Decimal = None,
        original_price: Decimal = None,
        modifications_applied: dict = None,
        allergen_warnings: list[str] = None,
        added_by: str = None,
    ) -> OrderItem:
        """
        Add an item to an order.
        If item already exists with matching modifications, update its quantity.
        """
        mod_applied = modifications_applied or {}
        orig_price = original_price if original_price is not None else menu_item.price
        pr_snapshot = price_snapshot if price_snapshot is not None else menu_item.price

        # Check if item already in order with SAME modifications
        existing = await db.execute(
            select(OrderItem).where(
                OrderItem.order_id == order_id,
                OrderItem.menu_item_id == menu_item.id,
                OrderItem.modifications_applied == mod_applied
            )
        )
        existing_item = existing.scalar_one_or_none()

        if existing_item:
            existing_item.quantity += quantity
            await db.flush()

            # Update order discount total
            await OrderService.recalculate_discounts(db, order_id)

            session_id = await OrderService._get_session_id(db, order_id)
            from monitoring.hooks import emit_order_event
            emit_order_event("ADD_ITEM", order_id, session_id, {"item": menu_item.name, "quantity": quantity})

            return existing_item

        order_item = OrderItem(
            order_id=order_id,
            menu_item_id=menu_item.id,
            name_snapshot=menu_item.name,
            price_snapshot=pr_snapshot,
            original_price=orig_price,
            quantity=quantity,
            modifiers_chosen=modifiers_chosen or {},
            modifications_applied=mod_applied,
            allergen_warnings=allergen_warnings or [],
            added_by=added_by,
            subtotal=pr_snapshot * quantity,
        )
        db.add(order_item)
        await db.flush()

        # Update order discount total
        await OrderService.recalculate_discounts(db, order_id)

        # Track popularity in Redis
        await cache.increment_popular(menu_item.restaurant_id, menu_item.id)

        session_id = await OrderService._get_session_id(db, order_id)
        from monitoring.hooks import emit_order_event
        emit_order_event("ADD_ITEM", order_id, session_id, {"item": menu_item.name, "quantity": quantity})

        return order_item

    @staticmethod
    async def remove_item(db: AsyncSession, order_id: int, menu_item_id: int, modifications_applied: dict = None):
        """
        Remove an item from order, matching modifications if specified.
        """
        query = select(OrderItem).where(
            OrderItem.order_id == order_id,
            OrderItem.menu_item_id == menu_item_id
        )
        if modifications_applied is not None:
            query = query.where(OrderItem.modifications_applied == modifications_applied)

        result = await db.execute(query)
        items = result.scalars().all()
        if items:
            # Delete matching items
            for item in items:
                item_name = item.name_snapshot
                await db.delete(item)
            await db.flush()
            
            # Recalculate discount total
            await OrderService.recalculate_discounts(db, order_id)

            session_id = await OrderService._get_session_id(db, order_id)
            from monitoring.hooks import emit_order_event
            emit_order_event("REMOVE_ITEM", order_id, session_id, {"item": item_name, "menu_item_id": menu_item_id})

    @staticmethod
    async def recalculate_discounts(db: AsyncSession, order_id: int):
        """Recalculate total discounts applied to the order."""
        result = await db.execute(
            select(Order).where(Order.id == order_id)
        )
        order = result.scalar_one_or_none()
        if not order:
            return

        result_items = await db.execute(
            select(OrderItem).where(OrderItem.order_id == order_id)
        )
        items = result_items.scalars().all()
        
        discount_total = Decimal("0.00")
        promotions_applied = []
        for item in items:
            if item.original_price is not None and item.original_price > item.price_snapshot:
                diff = item.original_price - item.price_snapshot
                discount_total += diff * item.quantity
                # Add metadata if needed

        order.discount_total = discount_total
        await db.flush()

    @staticmethod
    async def get_order_with_items(db: AsyncSession, order_id: int) -> Order | None:
        result = await db.execute(
            select(Order)
            .options(selectinload(Order.items))
            .where(Order.id == order_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def confirm_order(db: AsyncSession, order_id: int) -> Order:
        """
        Distributed lock prevents double-confirmation race condition.
        """
        lock_key = CacheKeys.order_lock(order_id)
        acquired = await cache.acquire_lock(lock_key, ttl_ms=5000)

        if not acquired:
            raise RuntimeError("Order is being processed — please wait.")

        try:
            result = await db.execute(
                select(Order).where(Order.id == order_id)
            )
            order = result.scalar_one()
            order.status = "confirmed"
            # DB trigger fires NOTIFY — kitchen display updates in real-time
            await db.flush()

            from monitoring.hooks import emit_order_event
            emit_order_event("CONFIRM", order_id, order.session_id, {"total": float(order.total)})

            return order
        finally:
            await cache.release_lock(lock_key)

    @staticmethod
    def format_receipt(order: Order) -> str:
        lines = [f"\n{'─'*40}", f"  ORDER #{order.id}", f"{'─'*40}"]
        for item in order.items:
            mod_str = ""
            if item.modifications_applied:
                # flatten modifications
                from prompts.system_prompt import _flatten_mods
                mods = _flatten_mods(item.modifications_applied)
                if mods:
                    mod_str = f" ({', '.join(mods)})"
            
            discount_str = ""
            if item.original_price is not None and item.original_price > item.price_snapshot:
                discount_str = f" [was ${float(item.original_price):.2f}]"

            lines.append(
                f"  {item.quantity}x {item.name_snapshot}{mod_str:<25} "
                f"${float(item.price_snapshot * item.quantity):.2f}{discount_str}"
            )
        lines.append(f"{'─'*40}")
        if order.discount_total and order.discount_total > 0:
            lines.append(f"  {'Discount Total':<30} -${float(order.discount_total):.2f}")
        lines.append(f"  {'TOTAL':<30} ${float(order.total):.2f}")
        lines.append(f"{'─'*40}\n")
        return "\n".join(lines)

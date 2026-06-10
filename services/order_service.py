from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from db.models import Order, OrderItem, MenuItem
from redis_client import cache, CacheKeys


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
        customer_name: str = None
    ) -> Order:
        order = Order(
            restaurant_id=restaurant_id,
            session_id=session_id,
            customer_name=customer_name,
            status="pending",
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
    ) -> OrderItem:
        """
        Add an item to an order.
        IMPORTANT: snapshot name + price at this moment — not a live reference.
        The DB trigger will auto-recalculate order.total.
        """
        # Check if item already in order — update quantity instead
        existing = await db.execute(
            select(OrderItem).where(
                OrderItem.order_id == order_id,
                OrderItem.menu_item_id == menu_item.id
            )
        )
        existing_item = existing.scalar_one_or_none()

        if existing_item:
            existing_item.quantity += quantity
            # subtotal updated by trigger

            session_id = await OrderService._get_session_id(db, order_id)
            from monitoring.hooks import emit_order_event
            emit_order_event("ADD_ITEM", order_id, session_id, {"item": menu_item.name, "quantity": quantity})

            return existing_item

        order_item = OrderItem(
            order_id=order_id,
            menu_item_id=menu_item.id,
            name_snapshot=menu_item.name,           # frozen at order time
            price_snapshot=menu_item.price,         # frozen at order time
            quantity=quantity,
            modifiers_chosen=modifiers_chosen or {},
            subtotal=menu_item.price * quantity,    # also set by trigger
        )
        db.add(order_item)
        await db.flush()

        # Track popularity in Redis
        await cache.increment_popular(menu_item.restaurant_id, menu_item.id)

        session_id = await OrderService._get_session_id(db, order_id)
        from monitoring.hooks import emit_order_event
        emit_order_event("ADD_ITEM", order_id, session_id, {"item": menu_item.name, "quantity": quantity})

        return order_item

    @staticmethod
    async def remove_item(db: AsyncSession, order_id: int, menu_item_id: int):
        result = await db.execute(
            select(OrderItem).where(
                OrderItem.order_id == order_id,
                OrderItem.menu_item_id == menu_item_id
            )
        )
        item = result.scalar_one_or_none()
        if item:
            item_name = item.name_snapshot
            await db.delete(item)
            await db.flush()
            # trigger auto-recalculates order total

            session_id = await OrderService._get_session_id(db, order_id)
            from monitoring.hooks import emit_order_event
            emit_order_event("REMOVE_ITEM", order_id, session_id, {"item": item_name, "menu_item_id": menu_item_id})

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
            lines.append(
                f"  {item.quantity}x {item.name_snapshot:<25} "
                f"${float(item.price_snapshot * item.quantity):.2f}"
            )
        lines.append(f"{'─'*40}")
        lines.append(f"  {'TOTAL':<30} ${float(order.total):.2f}")
        lines.append(f"{'─'*40}\n")
        return "\n".join(lines)

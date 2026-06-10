from celery import Celery
from config import settings
import asyncio
from sqlalchemy import text
from db.base import AsyncSessionFactory

app = Celery("tasks", broker=settings.celery_broker_url, backend=settings.celery_result_backend)


@app.task
def send_order_notification(order_id: int):
    # Stub for sending notifications to kitchen/customer
    print(f"[Celery] Sending notification for order #{order_id}")
    return True


@app.task
def refresh_analytics():
    # Stub for analytics refresh
    print("[Celery] Refreshing analytics cache...")
    return True


@app.task(name="tasks.refresh_affinities")
def refresh_affinities(restaurant_id: int):
    """Recompute item_affinity table. Run hourly."""
    async def _run():
        async with AsyncSessionFactory() as db:
            # Recompute affinities for the restaurant
            await db.execute(text("""
                INSERT INTO item_affinity (item_a_id, item_b_id, restaurant_id, co_occurrence, lift_score)
                SELECT
                    a.menu_item_id,
                    b.menu_item_id,
                    o.restaurant_id,
                    count(*)::int,
                    (count(*)::float /
                        NULLIF((SELECT count(*) FROM order_items oi2 WHERE oi2.menu_item_id = a.menu_item_id), 0)
                    )::numeric(6,3)
                FROM   order_items a
                JOIN   order_items b ON a.order_id = b.order_id AND a.menu_item_id != b.menu_item_id
                JOIN   orders o      ON o.id = a.order_id AND o.status = 'completed'
                WHERE  o.restaurant_id = :rid
                GROUP  BY a.menu_item_id, b.menu_item_id, o.restaurant_id
                ON CONFLICT (item_a_id, item_b_id) DO UPDATE
                    SET co_occurrence = EXCLUDED.co_occurrence,
                        lift_score    = EXCLUDED.lift_score,
                        last_computed = NOW()
            """), {"rid": restaurant_id})
            
            # Concurrently refresh pairings materialized view
            await db.execute(text("REFRESH MATERIALIZED VIEW CONCURRENTLY top_pairings"))
            await db.commit()
            print(f"[Celery] Affinities refreshed for restaurant {restaurant_id}")

    # Run the async function using asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    if loop.is_running():
        # Run in a separate thread/future if event loop is already running in current thread
        import threading
        t = threading.Thread(target=lambda: asyncio.run(_run()))
        t.start()
        t.join()
    else:
        loop.run_until_complete(_run())
    return True

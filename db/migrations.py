import asyncio
import logging
from db.base import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MIGRATION_SQL = """
-- ─────────────────────────────────────────────────
-- TRIGGER 1: Auto-calculate order total
-- ─────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION recalculate_order_total()
RETURNS TRIGGER AS $$
BEGIN
    -- Auto-compute subtotal on each item
    IF TG_TABLE_NAME = 'order_items' THEN
        NEW.subtotal := NEW.price_snapshot * NEW.quantity;
    END IF;

    -- Recompute order total from all items
    UPDATE orders
    SET
        total      = COALESCE((
            SELECT SUM(price_snapshot * quantity)
            FROM   order_items
            WHERE  order_id = COALESCE(NEW.order_id, OLD.order_id)
        ), 0),
        updated_at = NOW()
    WHERE id = COALESCE(NEW.order_id, OLD.order_id);

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_order_total_insert ON order_items;
CREATE TRIGGER trg_order_total_insert
BEFORE INSERT ON order_items
FOR EACH ROW EXECUTE FUNCTION recalculate_order_total();

DROP TRIGGER IF EXISTS trg_order_total_update ON order_items;
CREATE TRIGGER trg_order_total_update
BEFORE UPDATE ON order_items
FOR EACH ROW EXECUTE FUNCTION recalculate_order_total();

DROP TRIGGER IF EXISTS trg_order_total_delete ON order_items;
CREATE TRIGGER trg_order_total_delete
AFTER DELETE ON order_items
FOR EACH ROW EXECUTE FUNCTION recalculate_order_total();


-- ─────────────────────────────────────────────────
-- TRIGGER 2: Real-time NOTIFY on order status change
-- ─────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION notify_order_update()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.status IS DISTINCT FROM NEW.status THEN
        PERFORM pg_notify(
            'order_updates',
            json_build_object(
                'order_id',     NEW.id,
                'restaurant_id', NEW.id,
                'old_status',   OLD.status,
                'new_status',   NEW.status,
                'updated_at',   NOW()
            )::text
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_order_notify ON orders;
CREATE TRIGGER trg_order_notify
AFTER UPDATE OF status ON orders
FOR EACH ROW EXECUTE FUNCTION notify_order_update();


-- ─────────────────────────────────────────────────
-- TRIGGER 3: Keep FTS search_vector in sync
-- ─────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION update_menu_item_search_vector()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', coalesce(NEW.name, '')),        'A') ||
        setweight(to_tsvector('english', coalesce(NEW.description, '')), 'B') ||
        setweight(to_tsvector('english', array_to_string(
            ARRAY(SELECT jsonb_array_elements_text(NEW.tags)), ' '
        )), 'C');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_menu_item_fts ON menu_items;
CREATE TRIGGER trg_menu_item_fts
BEFORE INSERT OR UPDATE ON menu_items
FOR EACH ROW EXECUTE FUNCTION update_menu_item_search_vector();


-- ─────────────────────────────────────────────────
-- ROW-LEVEL SECURITY (multi-tenancy at DB level)
-- ─────────────────────────────────────────────────
ALTER TABLE menu_items      ENABLE ROW LEVEL SECURITY;
ALTER TABLE menu_categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders          ENABLE ROW LEVEL SECURITY;
ALTER TABLE order_items     ENABLE ROW LEVEL SECURITY;

-- Policy: each connection can only see its own restaurant's data
DROP POLICY IF EXISTS tenant_isolation ON menu_items;
CREATE POLICY tenant_isolation ON menu_items
    USING (restaurant_id = current_setting('app.restaurant_id', true)::int);

DROP POLICY IF EXISTS tenant_isolation ON menu_categories;
CREATE POLICY tenant_isolation ON menu_categories
    USING (restaurant_id = current_setting('app.restaurant_id', true)::int);

DROP POLICY IF EXISTS tenant_isolation ON orders;
CREATE POLICY tenant_isolation ON orders
    USING (restaurant_id = current_setting('app.restaurant_id', true)::int);

-- order_items is scoped through its parent order
DROP POLICY IF EXISTS tenant_isolation ON order_items;
CREATE POLICY tenant_isolation ON order_items
    USING (order_id IN (
        SELECT id FROM orders
        WHERE restaurant_id = current_setting('app.restaurant_id', true)::int
    ));

-- Superuser bypass (for admin/seed scripts)
DROP POLICY IF EXISTS admin_bypass ON menu_items;
CREATE POLICY admin_bypass ON menu_items TO postgres USING (true);

DROP POLICY IF EXISTS admin_bypass ON orders;
CREATE POLICY admin_bypass ON orders     TO postgres USING (true);
"""

async def run_custom_migrations():
    logger.info("Applying custom PostgreSQL triggers and Row-Level Security policies...")
    async with engine.connect() as conn:
        raw_dbapi_conn = await conn.get_raw_connection()
        raw_conn = raw_dbapi_conn.driver_connection
        await raw_conn.execute(MIGRATION_SQL)
    logger.info("Custom database migrations applied successfully!")

if __name__ == "__main__":
    asyncio.run(run_custom_migrations())

# Database Design & Scoping Guide

This document describes the PostgreSQL database layer of the Restaurant AI Ordering System. It is designed to give you a thorough understanding of the schema, SQL triggers, text search strategies, and how **Row-Level Security (RLS)** enforces multi-tenancy.

---

## 1. Entity-Relationship Schema

The database model consists of five core tables defined in [db/models.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/db/models.py):

```
┌─────────────────┐
│   restaurants   │ (One row per tenant restaurant)
├─────────────────┤
│ id (PK)         │◄────────┐
│ name            │         │
│ cuisine_type    │         │
│ personality     │         │
│ is_active       │         │
└─────────────────┘         │
         │                  │
         ├──────────────────┼─────────────────────────┐
         │ (1-to-many)      │ (1-to-many)             │ (1-to-many)
         ▼                  ▼                         ▼
┌─────────────────┐┌─────────────────┐      ┌─────────────────┐
│ menu_categories ││   menu_items    │      │     orders      │ (One per customer session)
├─────────────────┤├─────────────────┤      ├─────────────────┤
│ id (PK)         ││ id (PK)         │◄──┐  │ id (PK)         │◄──────┐
│ restaurant_id   ││ restaurant_id   │   │  │ restaurant_id   │       │
│ name            ││ category_id     │   │  │ session_id      │       │
│ display_order   ││ name            │   │  │ status          │       │
└─────────────────┘│ price           │   │  │ total           │       │
                   │ tags (JSONB)    │   │  └─────────────────┘       │ (1-to-many)
                   │ search_vector   │   │            │               │
                   └─────────────────┘   │            │ (1-to-many)   │
                                         │            ▼               │
                                         │  ┌─────────────────┐       │
                                         │  │   order_items   │       │
                                         │  ├─────────────────┤       │
                                         └──┤ menu_item_id    │       │
                                            │ order_id        │───────┘
                                            │ name_snapshot   │ (Locks historical menu)
                                            │ price_snapshot  │
                                            │ quantity        │
                                            │ subtotal        │
                                            └─────────────────┘
```

---

## 2. Row-Level Security (RLS) — Enforcing Multi-Tenancy

In a multi-tenant system, separating tenant data is critical. A common junior mistake is relying on application code to always remember to add `WHERE restaurant_id = X` to every database query. If a developer forgets this filter in a single query, a security breach occurs.

To solve this, we use PostgreSQL's native **Row-Level Security (RLS)**.

### How it works
1. **Enable RLS on Tables**: During database initialization, we alter our tables to enable RLS:
   ```sql
   ALTER TABLE menu_items ENABLE ROW LEVEL SECURITY;
   ```
2. **Define Security Policies**: We define a policy stating that any database session can only see records matching a session configuration variable called `app.restaurant_id`:
   ```sql
   CREATE POLICY tenant_isolation ON menu_items
       USING (restaurant_id = current_setting('app.restaurant_id', true)::int);
   ```
3. **Set the Tenant Context**: In our application, whenever we acquire a database connection, we run a session variable configuration command:
   ```python
   await db.execute(
       text("SELECT set_config('app.restaurant_id', :rid, true)"),
       {"rid": str(restaurant_id)}
   )
   ```
   *Note: The third argument (`true`) is extremely important. It marks the setting as **transaction-local**. This means the setting is discarded when the current database transaction ends, ensuring that if the database connection is returned to a connection pool, it doesn't leak the tenant ID to a subsequent connection.*

With this setup, even if you run a broad `SELECT * FROM menu_items` query, PostgreSQL will automatically rewrite the query under the hood to restrict records to the current tenant.

---

## 3. Database Triggers (Business Logic Automation)

Rather than handling manual math in the application code, we let PostgreSQL automate subtotals and order totals using triggers (configured in [db/migrations.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/db/migrations.py)):

### 3.1 Order Item Subtotal Trigger
Whenever a row is inserted or updated in `order_items`, the trigger automatically computes the subtotal as `price_snapshot * quantity`.
```sql
CREATE OR REPLACE FUNCTION calculate_item_subtotal()
RETURNS TRIGGER AS $$
BEGIN
    NEW.subtotal := NEW.price_snapshot * NEW.quantity;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

### 3.2 Order Total Aggregation Trigger
Whenever items in `order_items` are added, modified, or deleted, a secondary trigger aggregates the subtotals of all items belonging to that order and writes the sum back to the parent `orders` table.
```sql
CREATE OR REPLACE FUNCTION recalculate_order_total()
RETURNS TRIGGER AS $$
BEGIN
    -- ... gets order_id ...
    UPDATE orders
    SET total = COALESCE((SELECT SUM(subtotal) FROM order_items WHERE order_id = v_order_id), 0)
    WHERE id = v_order_id;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
```

### 3.3 Real-Time Status Notification Trigger
When an order's status transitions (e.g., from `"pending"` to `"confirmed"`), a trigger broadcasts a JSON payload using PostgreSQL's native `LISTEN/NOTIFY` system on the `order_updates` channel. External microservices can listen to this channel to trigger kitchen tickets.
```sql
CREATE OR REPLACE FUNCTION notify_order_update()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.status IS DISTINCT FROM NEW.status THEN
        PERFORM pg_notify('order_updates', json_build_object('order_id', NEW.id, 'new_status', NEW.status)::text);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

---

## 4. Text Search Strategy — FTS and Trigram Fallback

We support two search modes in [services/menu_service.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/services/menu_service.py):

### 4.1 Full-Text Search (FTS)
FTS is great for finding word roots (e.g., searching for `"ribs"` will match `"rib"`). We maintain a `tsvector` column called `search_vector` on `menu_items` using a trigger. The trigger concatenates the item's name, description, and tags, stemming them into English words:
```sql
NEW.search_vector :=
    setweight(to_tsvector('english', coalesce(NEW.name, '')),        'A') ||
    setweight(to_tsvector('english', coalesce(NEW.description, '')), 'B') ||
    setweight(to_tsvector('english', array_to_string(ARRAY(SELECT jsonb_array_elements_text(NEW.tags)), ' ')), 'C');
```
We search this index using the `@@` operator:
```sql
search_vector @@ plainto_tsquery('english', :q)
```

### 4.2 Trigram Fuzzy Search (Fallback)
If FTS returns zero results (for example, if the user made a typo like `"burgre"` instead of `"burger"`), the service falls back to a trigram similarity query:
```sql
similarity(name, :q) > 0.2
ORDER BY similarity(name, :q) DESC
```
This is enabled by the `pg_trgm` extension. It splits strings into sets of 3 characters and counts matches, making it extremely resilient to typos.

---

## 5. Migration Workflow with Alembic

We use **Alembic** to manage database schema updates.

*   **To create a new migration** (after changing `db/models.py`):
    ```bash
    uv run alembic revision --autogenerate -m "description of change"
    ```
    This generates a new script in `alembic/versions/`. Review the generated script to ensure it is correct.
*   **To apply migrations**:
    ```bash
    uv run alembic upgrade head
    ```
*   **To apply custom SQL triggers and RLS policies**:
    Because Alembic's autogenerate tool only understands tables and indexes (not triggers or RLS policies), you must run our custom database migration script after upgrading the schema:
    ```bash
    uv run python db/migrations.py
    ```

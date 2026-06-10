# Redis Caching & Distributed Locks Guide

This document describes the caching and concurrency patterns implemented in our Redis layer ([redis_client.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/redis_client.py)). If you want to understand how our application handles quick reads and ensures transaction safety, read on.

---

## 1. Key Conventions

We use Redis to manage transient data. Keys are structured using colon namespaces:

| Key Format | Type | Description | TTL (Time to Live) |
| :--- | :--- | :--- | :--- |
| `menu:{restaurant_id}` | JSON String | Formatted menu hierarchy by category. | 5 minutes (`MENU_CACHE_TTL_SECONDS`) |
| `lock:order:{order_id}` | String | Distributed lock for order placement. | 5 seconds (5000ms) |
| `popular:{restaurant_id}` | Sorted Set | Tracks total orders per menu item. | Persistent |

---

## 2. Cache-Aside Pattern (Menu Caching)

In a database-backed application, querying the menu requires joining `menu_items` and `menu_categories` and sorting them. Doing this database roundtrip on every chat message is slow and resource-heavy. 

We solve this using the **Cache-Aside Pattern** (implemented in `MenuService.get_menu` in [services/menu_service.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/services/menu_service.py)):

```
                 Application Requests Menu
                             │
                             ▼
                     Is it in Redis?
                      /           \
              (Yes)  /             \ (No: Cache Miss)
                    ▼               ▼
             Return cached menu  Query PostgreSQL DB
                                    │
                                    ├──────────────────────────┐
                                    ▼                          ▼
                             Write to Redis             Return to User
                             (TTL = 5 mins)
```

### Invalidating Cache
If a restaurant manager changes an item's price or description, the cached menu in Redis will be out of sync. To resolve this, whenever the menu is mutated, we run `MenuService.invalidate_cache(restaurant_id)` which deletes the key `menu:{restaurant_id}`. The next request will experience a cache miss, fetch the fresh data from PostgreSQL, and cache it again.

---

## 3. Distributed Lock Pattern (Order Confirmation Safety)

When a customer clicks the "Confirm & Place Order" button in the Web UI, or the AI agent triggers `confirm_and_place_order` from the chat, we write to the database to update the order's status to `"confirmed"`.

### The Problem: Race Conditions
If the user double-clicks the button, or sends two fast messages, the API might receive two concurrent requests at the exact same millisecond. If we do not protect against this, both requests will run in parallel, resulting in:
1. Two separate database writes.
2. Double-processing of payment.
3. Duplicate tickets sent to the kitchen.

### The Solution: Distributed Lock with `SET NX PX`
We use Redis to acquire an atomic lock before confirming an order (implemented in `OrderService.confirm_order` in [services/order_service.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/services/order_service.py)):

```python
# Acquire Lock
lock_key = CacheKeys.order_lock(order_id)
acquired = await cache.acquire_lock(lock_key, ttl_ms=5000)
if not acquired:
    raise HTTPException(status_code=409, detail="Order is already being processed.")
```

#### How `cache.acquire_lock` Works:
We run the Redis command `SET lock:order:123 "1" NX PX 5000`:
*   `NX`: *"Only set the key if it **does not** already exist."* If the key exists, return `None`.
*   `PX 5000`: Set a TTL of 5000 milliseconds. If the application crashes before releasing the lock, Redis will delete it automatically after 5 seconds, preventing the order from being locked forever.

Because Redis runs commands on a single-threaded event loop, this command is guaranteed to be **atomic**. One request will successfully set the key and proceed; the second concurrent request will get a failure immediately and reject the double-submission.

Once the confirmation write completes, we release the lock:
```python
await cache.release_lock(lock_key)
```

---

## 4. Popular Items Leaderboard (Sorted Sets)

When an order is confirmed, we want to update a leaderboard of popular dishes. We do this using Redis **Sorted Sets (ZSET)**.

A Sorted Set stores unique string values mapped to a numerical score. It automatically maintains sorting based on the score.

*   **zincrby**: Increment the score of an item:
    ```python
    await self.client.zincrby("popular:1", 1, "menu_item_id_4")
    ```
*   **zrevrange**: Fetch the top N items with the highest scores:
    ```python
    await self.client.zrevrange("popular:1", 0, 4)  # returns top 5 item IDs
    ```

This allows us to fetch popular items instantly, without running slow `SUM` and `GROUP BY` aggregates on historical database tables.

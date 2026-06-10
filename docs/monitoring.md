# Telemetry & Developer Monitoring Guide

This document explains our developer monitoring system, which logs and tracks system-wide database queries, cache checks, LLM performance, tool calls, and agent states, displaying them in a NiceGUI dashboard.

---

## 1. Monitoring System Flow

The monitoring system consists of three main parts:
1.  **Hooks / Listeners**: Small pieces of code injected into database queries, Redis clients, and LangGraph callbacks. They capture events (such as raw SQL, cache hits/misses, or token usages) and calculate duration.
2.  **Central Event Bus**: A thread-safe, in-memory pub/sub broker (`EventBus`) that collects events and notifies listeners.
3.  **NiceGUI UI Dashboard**: A web-based front-end that mounts inside our FastAPI app under `/monitor/` and updates in real-time.

```
┌──────────────┐┌──────────────┐┌──────────────┐┌──────────────┐
│  SQL Engine  ││ Redis Client ││  LLM Engine  ││ Agent Nodes  │ (Telemetry Hooks)
└──────┬───────┘└──────┬───────┘└──────┬───────┘└──────┬───────┘
       │               │               │               │
       └───────────────┼───────────────┼───────────────┘
                       │ Event(kind, title, detail, duration)
                       ▼
            ┌─────────────────────┐
            │   EventBus (bus)    │ (In-memory ring buffer)
            └──────────┬──────────┘
                       │ push notifications
                       ▼
            ┌─────────────────────┐
            │ NiceGUI Dashboard   │ (Polling via 200ms tick())
            └─────────────────────┘
```

---

## 2. Event Model & Event Bus ([monitoring/events.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/monitoring/events.py))

### The Event Model
An `Event` represents a single telemetric log. It is represented by a dataclass containing:
*   `kind`: The type of event (defined by the `EK` enum: `LLM`, `TOOL`, `DB`, `REDIS`, `AGENT`, `ORDER`, `ERROR`).
*   `title`: A short string displayed in the timeline (e.g., `SELECT menu_items`).
*   `detail`: A dictionary for additional, expandable details (e.g., the raw SQL query, prompt values, or tool arguments).
*   `duration_ms`: Execution time (if applicable).
*   `is_error`: Boolean indicating if the event failed.

### The Event Bus (`EventBus`)
The central event broker is a thread-safe singleton named `bus`.
*   It stores the last 2000 events in a ring buffer (`collections.deque` with `maxlen=2000`). This ensures we don't leak memory.
*   It exposes `bus.emit(event)`, which appends the event to the buffer and updates the metrics aggregator (`Metrics`).
*   It allows the dashboard to register callbacks via `bus.subscribe(callback)`.

---

## 3. Telemetry Hook Instrumentation

Our hooks are defined in [monitoring/hooks.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/monitoring/hooks.py). Here is how they are hooked into each subsystem:

### 3.1 Database Telemetry (SQLAlchemy Engine)
We hook into SQLAlchemy's event system:
*   **Before Query**: We intercept `before_cursor_execute` to record the current timestamp (`time.perf_counter()`) on the execution context.
*   **After Query**: We intercept `after_cursor_execute` to calculate the query duration. We parse the query type (`SELECT`, `INSERT`, `UPDATE`) and table name, sanitize the SQL to prevent logging passwords, and emit a `DB` event.

### 3.2 Redis Telemetry (`InstrumentedRedis`)
We created a custom subclass of `redis.asyncio.Redis` called `InstrumentedRedis`. 
*   It overrides basic commands like `get`, `set`, `delete`, and `zincrby`.
*   Before calling the actual command, it starts a timer. After the command completes, it logs the key name, command type, whether the cache request resulted in a hit or a miss (for `get` requests), and the latency.

### 3.3 LLM & Tool Telemetry (`MonitorCallback`)
We created a custom LangChain callback handler `MonitorCallback` subclassing `BaseCallbackHandler`.
*   `on_llm_start`: Captures the prompt inputs and saves a timer.
*   `on_llm_end`: Calculates the LLM response latency and extracts the generated text and token counts (prompt tokens, completion tokens, total tokens) to emit an `LLM` event.
*   `on_tool_start`: Captures the arguments of the tool call.
*   `on_tool_end` / `on_tool_error`: Emits a `TOOL` event containing the arguments, results, and latency.

### 3.4 Agent State Telemetry
Inside our nodes ([core/nodes.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/core/nodes.py)), after a node completes its execution, it calls `emit_agent_state()`. This captures a snapshot of the current state variables (`cart`, `stage`, etc.) and emits an `AGENT` event.

---

## 4. NiceGUI Dashboard Dashboard (`/monitor/`)

The dashboard is defined in [monitoring/dashboard.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/monitoring/dashboard.py) and is served inside FastAPI using `mount_dashboard(app)`.

### Connection-Specific State
Whenever a browser connects to `/monitor`, NiceGUI executes `_build_page()` which sets up a separate connection context.
*   It creates a list `pending_events: list[Event]` to collect events from the background thread.
*   It registers `on_new_event` on the `bus`.

### The Polling Loop (`tick()`)
To ensure that NiceGUI renders elements inside its correct asynchronous thread context, we use a 200ms timer to poll for new events:
```python
ui.timer(0.2, tick)
```

#### First Tick / Reload Logic
Because the `bus` stores historical data, we want to immediately display it when a user refreshes the page. However, we also don't want to run heavy rendering code continuously if no new events occur.

We solve this using a `first_tick` flag:
```python
first_tick = True

def tick():
    nonlocal first_tick
    # Return early if no new events occurred and this is NOT the page load tick
    if not pending_events and not first_tick:
        return

    first_tick = False
    
    # 1. Drain pending_events queue
    batch = pending_events[:]
    pending_events.clear()
    
    # 2. Update metric cards, error chip, and sidebar session lists
    # ...
```
On the first tick of a connection, even if `pending_events` is empty, the check is bypassed. This immediately runs the update block, reading the current cache hit rates, average query times, and active session lists from `bus`, populating the dashboard instantly. Subsequent ticks will return early if no new activities occurred.

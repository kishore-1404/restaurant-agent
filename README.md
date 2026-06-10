# Multi-Restaurant AI Ordering System

Welcome to the **Multi-Restaurant AI Ordering System**! This is a state-of-the-art, multi-tenant conversational ordering application. It lets customers browse menus, search for items using typos or conversational descriptions, build orders, and place checkout confirmations with different restaurants, guided entirely by an AI ordering assistant.

This repository is built with **FastAPI**, **PostgreSQL 16**, **Redis 7**, **LangGraph**, **Gemini API / Ollama**, and **NiceGUI**.

---

## 📖 Architectural Deep Dive Guides

If you are new to the codebase or are a junior engineer looking to understand how the components work under the hood, please read our dedicated developer guides first:

*   [System Architecture Guide](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/docs/architecture.md) — How the gateway, agent flow, service layers, and telemetry pipelines interact.
*   [Database Design & Row-Level Security (RLS) Guide](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/docs/database.md) — Explaining PostgreSQL schemas, SQL triggers, text search strategies, and tenant database isolation.
*   [LangGraph Agentic Flow Guide](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/docs/agent.md) — Detailed instructions on TypedDict states, nodes vs tools, checkpointers, and Server-Sent Events (SSE) streaming.
*   [Redis Caching & Concurrency Guide](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/docs/redis.md) — Explaining the Cache-Aside pattern, Sorted Sets for popular items, and atomic distributed locks (`SET NX PX`).
*   [Telemetry & Developer Monitoring Guide](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/docs/monitoring.md) — Real-time event bus, telemetry hooks (DB, Redis, LLM, Agent), and NiceGUI dashboard update cycles.

---

## 🛠 Prerequisites & Installation

### 1. Requirements
*   **Python 3.11+**
*   **Docker & Docker Compose**
*   **uv** — A fast Python package manager. Install it via:
    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

### 2. Install Dependencies
Run `uv sync` to create a virtual environment and install all dependencies (from [pyproject.toml](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/pyproject.toml)) in one command:
```bash
uv sync
```

### 3. Environment Secrets
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Open `.env` and fill in your keys:
*   `LLM_PROVIDER`: Set to `"gemini"`, `"ollama"`, or `"llamacpp"`.
*   `GEMINI_API_KEY`: Get a free key from [Google AI Studio](https://aistudio.google.com).
*   If using local models, ensure Ollama/llama.cpp is running and configured.

---

## 🚀 Running the Project

### 1. Run Services (Docker)
Start the PostgreSQL and Redis containers:
```bash
docker compose up -d
```

### 2. Setup the Database
Apply Alembic migrations to set up the tables, apply SQL triggers/RLS policies, and seed the database with restaurants and menu items:
```bash
# 1. Apply basic schemas
uv run alembic upgrade head

# 2. Add RLS policies & SQL Triggers
uv run python db/migrations.py

# 3. Seed restaurants (The Smokehouse, Bella Napoli, Tokyo Bites)
uv run python db/seed.py
```

### 3. Choose Your Interface to Run

#### Option A: Interactive CLI Terminal UI (Default)
Engage in a rich terminal interface that displays a side-by-side view of the conversation history, real-time cart contents, totals, and conversation stages:
```bash
uv run python main.py
```

#### Option B: Customer Web App + Developer Monitor
Starts the FastAPI backend, serving the static Customer SPA at `http://localhost:8754/` and mounting the NiceGUI Developer Monitor at `http://localhost:8754/monitor`:
```bash
uv run python main.py --web --port 8754
```

#### Option C: Standalone Developer Monitor
Starts only the developer telemetry monitor at `http://localhost:8754/monitor` (useful when testing CLI/Terminal calls in another pane):
```bash
uv run python main.py --monitor --port 8754
```

---

## 📂 Codebase Directory Map

*   [api/](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/api/) — FastAPI routing and API controllers.
    *   [dependencies.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/api/dependencies.py) — Binds active sessions and sets up tenant transaction contexts.
    *   [middleware.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/api/middleware.py) — Tenant interceptor reading the `X-Restaurant-ID` header.
    *   [routers/chat.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/api/routers/chat.py) — SSE tokens streaming and cart updates synchronization.
    *   [routers/frontend.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/api/routers/frontend.py) — Single-page application serving handler.
*   [core/](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/core/) — Stateful LangGraph agent engine.
    *   [graph.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/core/graph.py) — Compiled StateGraph orchestrating nodes.
    *   [nodes.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/core/nodes.py) — Core logic processors (`chatbot`, `tool_executor`, `update_stage`).
    *   [state.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/core/state.py) — `OrderState` TypedDict definition.
    *   [tools.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/core/tools.py) — Signature decorators for agent tool actions.
*   [db/](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/db/) — Database definition, models, and migrations.
    *   [base.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/db/base.py) — Session factories and SQLAlchemy async engines.
    *   [models.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/db/models.py) — ORM models mapped to PostgreSQL tables.
    *   [migrations.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/db/migrations.py) — SQL triggers, FTS indexes, and Row-Level Security policies.
    *   [seed.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/db/seed.py) — Mock data injector.
*   [llm/](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/llm/) — LLM adapter pattern interface.
    *   [factory.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/llm/factory.py) — Provider builder reading settings config.
*   [monitoring/](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/monitoring/) — Real-time telemetry reporting.
    *   [dashboard.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/monitoring/dashboard.py) — NiceGUI dashboard updates and polling loop.
    *   [hooks.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/monitoring/hooks.py) — Interceptors for DB, Redis, and LangGraph.
    *   [events.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/monitoring/events.py) — Shared pub/sub EventBus ring broker.
*   [services/](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/services/) — Business logic transaction layer.
    *   [menu_service.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/services/menu_service.py) — Menu fetching (cache-aside) and search fallbacks.
    *   [order_service.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/services/order_service.py) — Item additions, popularity trackers, and locked checks.
*   [static/](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/static/) — Front-end assets (HTML, scripts, styles).
*   [ui/](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/ui/) — Rich console UI definitions for terminal CLI execution.
*   [workers/](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/workers/) — Celery asynchronous queue definitions.

---

## 📈 Guide for Extending Functionality

### How to Add a New Restaurant
1. Open [db/seed.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/db/seed.py).
2. Append a new `Restaurant` record. Define its `name`, `cuisine_type`, `personality` (system prompt guidance), and JSON `metadata` (tax rates, address).
3. Populate its `MenuCategory` and `MenuItem` records.
4. Run `uv run python db/seed.py` to seed it. It will instantly show up in the web selection screen and terminal selector.

### How to Add a New Tool for the AI
1. Open [core/tools.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/core/tools.py) and declare your LangChain tool function:
   ```python
   @tool
   def apply_coupon(coupon_code: str) -> str:
       """Applies a discount coupon to the active order."""
       # return execution statement
   ```
2. Add the tool to the `ORDER_TOOLS` list inside `core/tools.py`.
3. Go to [core/nodes.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/core/nodes.py) inside the `tool_executor` node function. Add an `elif name == "apply_coupon":` branch to execute the backend/database logic.

### How to Adjust Slow Telemetry Thresholds
If you want to adjust what constitutes a "slow" query or operation in the dashboard logs:
1. Open [monitoring/events.py](file:///home/kishore/Projects/Restaurant%20AI%20Ordering%20Agent/restaurant-agent/monitoring/events.py).
2. Locate the `dur_color` property inside the `Event` class.
3. Edit the numbers inside the `thresholds` dictionary (e.g. increase `EK.DB` slow threshold from 100ms to 200ms).

---

## 🚨 Troubleshooting Common Issues

*   **Q: The Web UI starts, but `/monitor` throws a `nicegui` connection error.**
    *   **A**: NiceGUI relies on WebSockets to sync data. Ensure your network/firewall does not block WS connections on the selected port.
*   **Q: I get a `KeyError: 'menu_text'` when launching a session.**
    *   **A**: This occurs if state initialization is bypassed. Ensure you are using `/api/v1/chat/stream` which sets up the session DB records and formats menus on the first load of a new UUID.
*   **Q: Database queries throw a Row-Level Security policy error.**
    *   **A**: You are attempting to query tables without setting the tenant context first. Ensure you execute `await RestaurantService.set_tenant_context(db, restaurant_id)` inside the active transaction block before executing queries.

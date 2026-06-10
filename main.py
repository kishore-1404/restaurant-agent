import asyncio
import uuid
from langchain_core.messages import HumanMessage

from config import settings
from db.base import AsyncSessionFactory
from db.seed import run_seed
from services.restaurant_service import RestaurantService
from services.menu_service import MenuService
from services.order_service import OrderService
from core.graph import graph
from core.state import OrderState
from llm.factory import llm_provider
from ui import ui


def format_menu_for_prompt(menu: dict) -> str:
    """Convert structured menu dict to a readable string for the system prompt."""
    lines = []
    for category, items in menu.items():
        lines.append(f"\n[{category.upper()}]")
        for item in items:
            tags = f" ({', '.join(item['tags'])})" if item.get("tags") else ""
            lines.append(f"  • {item['name']} — ${item['price']:.2f}{tags}")
    return "\n".join(lines)


async def run_conversation(restaurant_id: int):
    session_id = str(uuid.uuid4())

    async with AsyncSessionFactory() as db:
        # Load restaurant config
        restaurant = await RestaurantService.get_by_id(db, restaurant_id)
        if not restaurant:
            ui.print_error(f"Restaurant {restaurant_id} not found.")
            return

        # Load menu (from cache or DB)
        menu = await MenuService.get_menu(db, restaurant_id)
        menu_text = format_menu_for_prompt(menu)

        # Create initial order in DB
        order = await OrderService.create_order(db, restaurant_id, session_id)
        await db.commit()

        # Set up terminal UI configuration
        ui.setup(restaurant.name, llm_provider.get_provider_name(), order_id=order.id)
        ui.print_menu(menu)

        # Initial state for LangGraph
        state: OrderState = {
            "messages": [],
            "restaurant_id": restaurant_id,
            "session_id": session_id,
            "language_code": "en",
            "customer_phone": None,
            "customer_name": None,
            "customer_profile": None,
            "cart": [],
            "order_id": order.id,
            "stage": "greeting",
            "menu_text": menu_text,
            "active_promotions": [],
            "order_rules": [],
            "allergen_warnings_shown": [],
            "upsells_shown": [],
            "error_message": None,
        }

        from monitoring.hooks import MonitorCallback
        config = {
            "configurable": {"thread_id": session_id},
            "callbacks": [MonitorCallback(session_id=session_id)],
        }

        # Start UI live layout
        with ui:
            # Kick off with a greeting from the agent
            initial_input = {
                **state,
                "messages": [HumanMessage(content="Hello, I'd like to order.")]
            }

            ui.begin_stream()
            async for event in graph.astream_events(initial_input, config=config, version="v2"):
                if event["event"] == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    if chunk.content:
                        ui.push_stream_token(chunk.content)
            ui.end_stream()

            # Sync initial state
            state_snapshot = await graph.aget_state(config)
            result = state_snapshot.values
            if result.get("cart"):
                cart = result["cart"]
                total = sum(i["price"] * i["quantity"] for i in cart)
                ui.update_cart(cart, total)
            if result.get("stage"):
                ui.set_stage(result["stage"])

            # Main conversation loop
            while True:
                user_input = ui.get_input().strip()

                if user_input.lower() in ("quit", "exit", "bye"):
                    break

                if not user_input:
                    continue

                # Add user message to UI chat panel
                ui.add_message("user", user_input)

                # Feed user message into graph and stream LLM response tokens
                ui.begin_stream()
                async for event in graph.astream_events(
                    {"messages": [HumanMessage(content=user_input)]},
                    config=config,
                    version="v2"
                ):
                    if event["event"] == "on_chat_model_stream":
                        chunk = event["data"]["chunk"]
                        if chunk.content:
                            ui.push_stream_token(chunk.content)
                ui.end_stream()

                # Sync updated state from checkpointer
                state_snapshot = await graph.aget_state(config)
                result = state_snapshot.values

                # Update live cart and total in sidebar
                if result.get("cart") is not None:
                    cart = result["cart"]
                    total = sum(i["price"] * i["quantity"] for i in cart)
                    ui.update_cart(cart, total)

                # Advance stage
                if result.get("stage"):
                    ui.set_stage(result["stage"])

                # Check if order was confirmed/completed
                if result.get("stage") == "done":
                    break

        # Outside the Live layout context, print the final receipt
        if result.get("stage") == "done":
            order = await OrderService.get_order_with_items(db, order.id)
            ui.print_receipt(order)


async def main():
    # Seed database if empty
    await run_seed()

    async with AsyncSessionFactory() as db:
        restaurants = await RestaurantService.list_active(db)

    # Use ui selector to choose a restaurant
    restaurant_id = ui.print_restaurant_selector(restaurants)
    await run_conversation(restaurant_id)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Restaurant AI Ordering System CLI & Servers")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--terminal", "-t", action="store_true", help="Run the interactive terminal UI (default)")
    group.add_argument("--web", "-w", action="store_true", help="Start the customer web UI + monitoring server")
    group.add_argument("--monitor", "-m", action="store_true", help="Start only the developer monitoring server")
    parser.add_argument("--port", "-p", type=int, default=8000, help="Port to run the web/monitoring server on")

    args = parser.parse_args()

    if args.web:
        import os
        os.environ["SERVE_WEB_UI"] = "true"
        import uvicorn
        from api.main import app as api_app
        print(f"Starting Web Server on http://localhost:{args.port}/")
        print(f"Developer Monitoring Dashboard available at http://localhost:{args.port}/monitor")
        uvicorn.run(api_app, host="0.0.0.0", port=args.port)
    elif args.monitor:
        import uvicorn
        from api.main import app as api_app
        print(f"Starting Developer Monitoring Server on http://localhost:{args.port}/monitor")
        uvicorn.run(api_app, host="0.0.0.0", port=args.port)
    else:
        # Default: Run the terminal client
        asyncio.run(main())

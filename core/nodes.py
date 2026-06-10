from sqlalchemy import select
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage
from core.state import OrderState
import time
from core.tools import ORDER_TOOLS
from prompts.system_prompt import build_system_prompt
from llm.factory import llm_provider
from db.base import AsyncSessionFactory
from db.models import OrderItem
from services.restaurant_service import RestaurantService
from services.menu_service import MenuService
from services.order_service import OrderService

# Bind tools to the LLM once at startup
_llm = llm_provider.get_chat_model()
_llm_with_tools = _llm.bind_tools(ORDER_TOOLS)


async def chatbot_node(state: OrderState) -> dict:
    """
    Core LLM node — processes messages and decides what to do next.
    Optionally calls tools (add item, search menu, etc.) or responds directly.
    """
    from monitoring.hooks import emit_agent_state

    emit_agent_state(state, state["session_id"], node_name="chatbot")
    # Fetch restaurant configuration for name and personality
    async with AsyncSessionFactory() as db:
        restaurant = await RestaurantService.get_by_id(db, state["restaurant_id"])
        restaurant_name = restaurant.name if restaurant else "the restaurant"
        personality = restaurant.personality if restaurant else ""

    # Build system prompt dynamically from restaurant + menu
    system_prompt = build_system_prompt(
        restaurant_id=state["restaurant_id"],
        menu_text=state["menu_text"],
        cart=state["cart"],
        stage=state["stage"],
        restaurant_name=restaurant_name,
        personality=personality,
    )

    # Prepend system message to conversation history
    messages = [SystemMessage(content=system_prompt)] + state["messages"]

    # Call LLM (may return text response or tool_call or both)
    response = await _llm_with_tools.ainvoke(messages)
    return {"messages": [response]}


async def tool_executor(state: OrderState) -> dict:
    """
    Custom tool execution node. Intercepts LLM tool calls and runs
    the actual database/service logic against PostgreSQL and Redis.
    """
    last_message = state["messages"][-1]
    tool_messages = []
    cart = state.get("cart", [])

    async with AsyncSessionFactory() as db:
        # Set tenant context for Row-Level Security
        await RestaurantService.set_tenant_context(db, state["restaurant_id"])

        for tool_call in last_message.tool_calls:
            name = tool_call["name"]
            args = tool_call["args"]
            tool_call_id = tool_call["id"]

            t0 = time.perf_counter()
            output = ""
            is_error = False
            try:
                if name == "add_item_to_order":
                    item_name = args.get("item_name")
                    quantity = args.get("quantity", 1)

                    # Search for the item in the menu
                    items = await MenuService.search_items(
                        db, state["restaurant_id"], item_name, limit=1
                    )
                    if not items:
                        output = f"Could not find item '{item_name}' on the menu."
                        is_error = True
                    else:
                        item_id = items[0]["id"]
                        menu_item = await MenuService.get_item_by_id(
                            db, item_id, state["restaurant_id"]
                        )
                        await OrderService.add_item(db, state["order_id"], menu_item, quantity)
                        output = f"Added {quantity}x {menu_item.name} to your order."

                elif name == "remove_item_from_order":
                    item_name = args.get("item_name")

                    # Search for the item in the menu
                    items = await MenuService.search_items(
                        db, state["restaurant_id"], item_name, limit=1
                    )
                    if not items:
                        output = f"Could not find item '{item_name}' on the menu."
                        is_error = True
                    else:
                        item_id = items[0]["id"]
                        await OrderService.remove_item(db, state["order_id"], item_id)
                        output = f"Removed '{item_name}' from the order."

                elif name == "modify_item_quantity":
                    item_name = args.get("item_name")
                    new_quantity = args.get("new_quantity")

                    # Search for the item
                    items = await MenuService.search_items(
                        db, state["restaurant_id"], item_name, limit=1
                    )
                    if not items:
                        output = f"Could not find item '{item_name}' on the menu."
                        is_error = True
                    else:
                        item_id = items[0]["id"]
                        # Find the existing order item to update its quantity
                        result = await db.execute(
                            select(OrderItem).where(
                                OrderItem.order_id == state["order_id"],
                                OrderItem.menu_item_id == item_id,
                            )
                        )
                        existing_item = result.scalar_one_or_none()
                        if existing_item:
                            if new_quantity <= 0:
                                await db.delete(existing_item)
                                output = f"Removed '{item_name}' from the order."
                            else:
                                existing_item.quantity = new_quantity
                                output = f"Updated '{item_name}' quantity to {new_quantity}."
                            await db.flush()
                        else:
                            output = f"Item '{item_name}' is not in the order."
                            is_error = True

                elif name == "search_menu":
                    query = args.get("query")
                    items = await MenuService.search_items(
                        db, state["restaurant_id"], query, limit=5
                    )
                    if not items:
                        output = "No matching items found on the menu."
                    else:
                        output = "Found the following matching items:\n" + "\n".join(
                            f"- {item['name']} (${item['price']:.2f}): {item['description'] or ''}"
                            for item in items
                        )

                elif name == "get_order_summary":
                    order = await OrderService.get_order_with_items(db, state["order_id"])
                    if not order or not order.items:
                        output = "Your order is currently empty."
                    else:
                        output = OrderService.format_receipt(order)

                elif name == "confirm_and_place_order":
                    await OrderService.confirm_order(db, state["order_id"])
                    output = "Order confirmed and sent to the kitchen!"

                else:
                    output = f"Unknown tool: {name}"
                    is_error = True

            except Exception as e:
                output = f"Error executing tool {name}: {str(e)}"
                is_error = True

            tool_messages.append(ToolMessage(content=output, tool_call_id=tool_call_id, name=name))

            # Emit manual tool execution event to telemetry bus
            duration_ms = (time.perf_counter() - t0) * 1000
            from monitoring.events import bus, Event, EK

            bus.emit(
                Event(
                    kind=EK.TOOL,
                    title=f"{name}({', '.join(f'{k}={v}' for k, v in args.items())})",
                    duration_ms=duration_ms,
                    session_id=state["session_id"],
                    is_error=is_error,
                    detail={
                        "tool": name,
                        "input": args,
                        "output": output,
                    },
                )
            )

        await db.commit()

        # Reload cart to update state
        order = await OrderService.get_order_with_items(db, state["order_id"])
        cart = []
        if order:
            for item in order.items:
                cart.append(
                    {
                        "item_id": item.menu_item_id,
                        "name": item.name_snapshot,
                        "price": float(item.price_snapshot),
                        "quantity": item.quantity,
                        "modifiers": item.modifiers_chosen,
                    }
                )

    from monitoring.hooks import emit_agent_state

    new_state = {**state, "cart": cart}
    emit_agent_state(new_state, state["session_id"], node_name="tools")

    return {"messages": tool_messages, "cart": cart}


def should_use_tools(state: OrderState) -> str:
    """
    Conditional edge: did the LLM decide to call a tool?
    Returns "tools" or "end" — LangGraph routes accordingly.
    """
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return "end"


def update_stage(state: OrderState) -> dict:
    """
    Examine conversation history to determine which stage we're in.
    This drives UI changes and system prompt tone.
    """
    messages = state["messages"]
    cart = state["cart"]
    stage = state.get("stage", "greeting")

    # Simple heuristic — in production this could use an LLM classifier
    if stage == "greeting" and len(messages) > 2:
        stage = "ordering"
    if cart and stage == "ordering":
        # Check if last AI message mentions confirmation
        last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        if last_ai and any(
            word in last_ai.content.lower() for word in ["confirm", "place your order", "shall i"]
        ):
            stage = "confirming"

    from monitoring.hooks import emit_agent_state

    new_state = {**state, "stage": stage}
    emit_agent_state(new_state, state["session_id"], node_name="update_stage")

    return {"stage": stage}

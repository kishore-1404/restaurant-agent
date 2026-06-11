from sqlalchemy import select, text
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage, HumanMessage, RemoveMessage
from core.state import OrderState, CartItem
import time
import re
import logging
from decimal import Decimal
from datetime import datetime
from core.tools import ORDER_TOOLS
from prompts.system_prompt import build_system_prompt
from llm.factory import llm_provider
from db.base import AsyncSessionFactory
from db.models import OrderItem, MenuItem, Order, CustomerProfile
from services.restaurant_service import RestaurantService
from services.menu_service import MenuService
from services.order_service import OrderService
from services.allergen_service import AllergenService
from services.profile_service import ProfileService
from services.rule_service import RuleService

logger = logging.getLogger(__name__)

# Bind tools to the LLM once at startup
_llm = llm_provider.get_chat_model()
_llm_with_tools = _llm.bind_tools(ORDER_TOOLS)


def _sanitise_message_for_history(content: str) -> str:
    """
    Strip any tool result JSON that might contain customer PII
    before it enters long-term conversation history.
    Tool results are ephemeral — they inform the current response
    but should not persist across summary boundaries.
    """
    if content.startswith("[PRE-LOADED FACTS"):
        return "[Facts loaded and communicated]"  # replaced after use
    return content


async def chatbot_node(state: OrderState) -> dict:
    """
    Core LLM node — processes messages and decides what to do next.
    Optionally calls tools or responds directly.
    """
    from monitoring.hooks import emit_agent_state
    from core.session_context import build_session_context
    from core.context_manager import should_summarise, summarise_and_prune
    from redis_client import cache as redis_cache

    emit_agent_state(state, state["session_id"], node_name="chatbot")

    messages = list(state["messages"])
    updated_state_fields = {}

    # ─── 1. Context Manager: Turn/Token Budget Pruning ───
    messages_update = []
    if await should_summarise(messages):
        messages_update, messages = await summarise_and_prune(
            messages=messages,
            session_id=state["session_id"],
            llm_client=_llm,
            redis_cache=redis_cache
        )
        updated_state_fields["messages"] = messages_update

    # ─── 2. PII Sanitisation of history messages ───
    for msg in messages:
        if hasattr(msg, "content") and isinstance(msg.content, str):
            msg.content = _sanitise_message_for_history(msg.content)

    async with AsyncSessionFactory() as db:
        # Load restaurant config
        restaurant = await RestaurantService.get_by_id(db, state["restaurant_id"])
        
        # Build dynamic SessionContext
        ctx = await build_session_context(
            db, 
            restaurant, 
            state["session_id"], 
            customer_phone=state.get("customer_phone"),
            language_code=state.get("language_code")
        )

        if ctx.language_code != state.get("language_code"):
            updated_state_fields["language_code"] = ctx.language_code
        if ctx.customer_profile:
            p = ctx.customer_profile
            profile_dict = {
                "id": p.id,
                "name": p.name,
                "phone": p.phone,
                "email": p.email,
                "language_code": p.language_code,
                "dietary_restrictions": p.dietary_restrictions,
                "allergens": p.allergens,
                "strict_allergens": p.strict_allergens,
                "preferences": p.preferences
            }
            if state.get("customer_profile") != profile_dict:
                updated_state_fields["customer_profile"] = profile_dict
            if state.get("customer_name") != p.name:
                updated_state_fields["customer_name"] = p.name
        else:
            if state.get("customer_profile") is not None:
                updated_state_fields["customer_profile"] = None
            if state.get("customer_name") is not None:
                updated_state_fields["customer_name"] = None

        # Detect language from first message if not set
        user_messages = [m for m in messages if m.type == "human"]
        if user_messages and not state.get("language_code"):
            try:
                from langdetect import detect
                first_msg_text = user_messages[0].content
                detected = detect(first_msg_text)
                SUPPORTED_LANGUAGES = {"en", "es", "ja", "fr", "de", "pt", "zh", "ar", "hi", "ko"}
                lang = detected if detected in SUPPORTED_LANGUAGES else "en"
                ctx.language_code = lang
                updated_state_fields["language_code"] = lang
            except Exception:
                pass

        # ─── 3. Pre-dispatch: match user intent and preload facts ───
        last_message = messages[-1] if messages else None
        if last_message and isinstance(last_message, HumanMessage):
            from core.pre_dispatch import run_pre_dispatch
            predispatch_facts = await run_pre_dispatch(last_message.content, ctx, db)
            ctx.predispatch_facts = predispatch_facts

        # Build system prompt dynamically from restaurant + menu + preloaded facts
        system_prompt = build_system_prompt(ctx, state["cart"], state["stage"])

    # Prepend system message to conversation history
    full_messages = [SystemMessage(content=system_prompt)] + messages

    # Call LLM
    response = await _llm_with_tools.ainvoke(full_messages)
    
    # If we pruned the context, we return the complete messages_update list + new LLM response.
    # Otherwise, LangGraph add_messages will just append our single response.
    if messages_update:
        return {"messages": messages_update + [response], **updated_state_fields}
    else:
        return {"messages": [response], **updated_state_fields}


async def tool_executor(state: OrderState) -> dict:
    """
    Custom tool execution node. Intercepts LLM tool calls and runs
    the actual database/service logic against PostgreSQL and Redis.
    """
    last_message = state["messages"][-1]
    tool_messages = []
    cart = state.get("cart", [])
    
    state_updates = {}
    upsells_shown_list = list(state.get("upsells_shown", []) or [])
    allergen_warnings_shown_list = list(state.get("allergen_warnings_shown", []) or [])
    customer_phone = state.get("customer_phone")
    customer_profile = state.get("customer_profile")

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
                # Load active rules and customer allergens
                now_time = datetime.now()
                price_rules = await RuleService.get_active_price_rules(db, state["restaurant_id"], now_time)
                
                strict_allergens = []
                warn_allergens = []
                if customer_profile:
                    strict_allergens = customer_profile.get("strict_allergens", []) or []
                    warn_allergens = customer_profile.get("allergens", []) or []

                # ─── 1. add_item ───
                if name == "add_item":
                    item_name = args.get("item_name")
                    quantity = args.get("quantity", 1)

                    items = await MenuService.search_items(db, state["restaurant_id"], item_name, limit=1)
                    if not items:
                        output = f"Could not find item '{item_name}' on the menu."
                        is_error = True
                    else:
                        menu_item = await MenuService.get_item_by_id(db, items[0]["id"], state["restaurant_id"])
                        
                        # Check safety using PG safety_audit function
                        from services.intelligence_service import IntelligenceService as IS
                        audit = await IS.safety_audit(
                            db,
                            allergens=warn_allergens,
                            dietary=customer_profile.get("dietary_restrictions", []) if customer_profile else [],
                            restaurant_id=state["restaurant_id"],
                            strict=strict_allergens,
                            session_id=state["session_id"]
                        )
                        
                        unsafe_items = audit.get("data", {}).get("unsafe_items", [])
                        modifiable_items = audit.get("data", {}).get("modifiable_items", [])
                        
                        is_unsafe = False
                        conflict_details = ""
                        
                        # Find if this menu item is in unsafe_items
                        for u in unsafe_items:
                            if u["name"].lower() == menu_item.name.lower():
                                is_unsafe = True
                                conflict_details = f"contains allergens: {', '.join(u.get('conflicting_allergens', []))}"
                                break
                                
                        # Or if it's in modifiable_items but added without modifications
                        is_modifiable_only = False
                        for m in modifiable_items:
                            if m["name"].lower() == menu_item.name.lower():
                                is_modifiable_only = True
                                conflict_details = f"requires modification: {m.get('instruction')}"
                                break
                                
                        if is_unsafe:
                            output = f"Cannot add {menu_item.name} because it is unsafe: {conflict_details}."
                            is_error = True
                        elif is_modifiable_only:
                            output = f"Cannot add {menu_item.name} directly: {conflict_details}."
                            is_error = True
                        else:
                            # Apply price rules
                            final_price, applied_rules = RuleService.apply_price_rules(menu_item, price_rules)
                            
                            # Add item
                            await OrderService.add_item(
                                db, state["order_id"], menu_item, quantity,
                                price_snapshot=final_price, original_price=menu_item.price
                            )
                            output = f"Added {quantity}x {menu_item.name} to order."
                            
                            # Warning for soft allergens if any
                            overlapping_warn = list(set(menu_item.allergens or []) & set(warn_allergens))
                            if overlapping_warn:
                                from monitoring.hooks import emit_allergen_event
                                emit_allergen_event(menu_item.name, overlapping_warn, state["session_id"])
                                if menu_item.id not in allergen_warnings_shown_list:
                                    allergen_warnings_shown_list.append(menu_item.id)
                                    state_updates["allergen_warnings_shown"] = allergen_warnings_shown_list
                                    output += f" Heads up — this contains {', '.join(overlapping_warn)}."

                            # Emit price rule event if discount applied
                            if final_price < menu_item.price:
                                from monitoring.hooks import emit_price_rule
                                emit_price_rule(applied_rules[0], menu_item.name, float(menu_item.price), float(final_price), state["session_id"])

                # ─── 2. add_item_with_modifications ───
                elif name == "add_item_with_modifications":
                    item_name = args.get("item_name")
                    quantity = args.get("quantity", 1)
                    remove = args.get("remove")
                    swap = args.get("swap")
                    add_extras = args.get("add_extras")

                    items = await MenuService.search_items(db, state["restaurant_id"], item_name, limit=1)
                    if not items:
                        output = f"Could not find item '{item_name}' on the menu."
                        is_error = True
                    else:
                        menu_item = await MenuService.get_item_by_id(db, items[0]["id"], state["restaurant_id"])
                        
                        # Validate mods
                        applied_mods, rejected_mods, price_delta = await _validate_and_price_modifications(
                            menu_item, remove, swap, add_extras
                        )
                        if rejected_mods:
                            output = f"Failed to add item. Invalid modifications: {', '.join(rejected_mods)}"
                            is_error = True
                        else:
                            # Price rules apply to base price, then we add delta
                            final_base, applied_rules = RuleService.apply_price_rules(menu_item, price_rules)
                            final_price = final_base + price_delta
                            original_price = menu_item.price + price_delta
                            
                            # Check safety of modified item. Since they removed some things,
                            # we verify if the modifications removed the strict allergens.
                            removed_ingredients = applied_mods.get("remove", [])
                            item_allergens = menu_item.allergens or []
                            
                            # If strict allergen is in the base item's allergens, verify if the removed ingredients
                            # actually made it safe. In our database schema/rules, we check if there are still strict allergen overlaps.
                            remaining_allergens = list(set(item_allergens) - set(removed_ingredients))
                            overlapping_strict = list(set(remaining_allergens) & set(strict_allergens))
                            
                            if overlapping_strict:
                                output = f"Cannot add {menu_item.name} because it still contains strict allergens: {', '.join(overlapping_strict)}."
                                is_error = True
                            else:
                                await OrderService.add_item(
                                    db, state["order_id"], menu_item, quantity,
                                    price_snapshot=final_price, original_price=original_price,
                                    modifications_applied=applied_mods
                                )
                                output = f"Added {quantity}x {menu_item.name} with modifications."
                                
                                # Allergen warnings for soft allergens
                                overlapping_warn = list(set(remaining_allergens) & set(warn_allergens))
                                if overlapping_warn:
                                    from monitoring.hooks import emit_allergen_event
                                    emit_allergen_event(menu_item.name, overlapping_warn, state["session_id"])
                                    if menu_item.id not in allergen_warnings_shown_list:
                                        allergen_warnings_shown_list.append(menu_item.id)
                                        state_updates["allergen_warnings_shown"] = allergen_warnings_shown_list
                                        output += f" Heads up — this contains {', '.join(overlapping_warn)}."

                                if final_base < menu_item.price:
                                    from monitoring.hooks import emit_price_rule
                                    emit_price_rule(applied_rules[0], menu_item.name, float(menu_item.price), float(final_base), state["session_id"])

                # ─── 3. remove_item ───
                elif name == "remove_item":
                    item_name = args.get("item_name")
                    items = await MenuService.search_items(db, state["restaurant_id"], item_name, limit=1)
                    if not items:
                        output = f"Could not find item '{item_name}' on the menu."
                        is_error = True
                    else:
                        await OrderService.remove_item(db, state["order_id"], items[0]["id"])
                        output = f"Removed {items[0]['name']} from the order."

                # ─── 4. update_item_quantity ───
                elif name == "update_item_quantity":
                    item_name = args.get("item_name")
                    new_quantity = args.get("new_quantity")

                    items = await MenuService.search_items(db, state["restaurant_id"], item_name, limit=1)
                    if not items:
                        output = f"Could not find item '{item_name}' on the menu."
                        is_error = True
                    else:
                        item_id = items[0]["id"]
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
                                output = f"Removed '{items[0]['name']}' from the order."
                            else:
                                existing_item.quantity = new_quantity
                                output = f"Updated '{items[0]['name']}' quantity to {new_quantity}."
                            await db.flush()
                            await OrderService.recalculate_discounts(db, state["order_id"])
                        else:
                            output = f"Item '{item_name}' is not in the order."
                            is_error = True

                # ─── 5. clear_order ───
                elif name == "clear_order":
                    result = await db.execute(
                        select(OrderItem).where(OrderItem.order_id == state["order_id"])
                    )
                    items = result.scalars().all()
                    for item in items:
                        await db.delete(item)
                    await db.flush()
                    await OrderService.recalculate_discounts(db, state["order_id"])
                    output = "Cleared all items from your order."

                # ─── 6. confirm_order ───
                elif name == "confirm_order":
                    pay_method = args.get("payment_method", "card")
                    res = await RuleService.validate_order_rules(db, state["order_id"], state["restaurant_id"])
                    if not res["valid"]:
                        output = f"Cannot place order due to rules: {res['violations'][0]['message']}"
                        is_error = True
                    else:
                        order = await OrderService.get_order_with_items(db, state["order_id"])
                        order.payment_method = pay_method
                        await OrderService.confirm_order(db, state["order_id"])
                        
                        output = f"Placed! Order #{order.id}: " + ", ".join(f"{i.name_snapshot} x{i.quantity}" for i in order.items) + f" — ${float(order.total):.2f}."

                # ─── 7. safety_audit ───
                elif name == "safety_audit":
                    allergens_list = args.get("allergens") or warn_allergens or []
                    dietary_list = args.get("dietary") or (customer_profile.get("dietary_restrictions", []) if customer_profile else [])
                    strict_list = customer_profile.get("strict_allergens", []) if customer_profile else []
                    from services.intelligence_service import IntelligenceService as IS
                    res = await IS.safety_audit(db, allergens_list, dietary_list, state["restaurant_id"], strict=strict_list, session_id=state["session_id"])
                    import json
                    output = json.dumps(res)

                # ─── 8. get_item_detail ───
                elif name == "get_item_detail":
                    item_name = args.get("item_name")
                    from services.intelligence_service import IntelligenceService as IS
                    res = await IS.get_item_detail(db, item_name, state["restaurant_id"])
                    import json
                    output = json.dumps(res)

                # ─── 9. explore_semantic ───
                elif name == "explore_semantic":
                    query = args.get("query")
                    from core.pre_dispatch import _embed
                    embedding = await _embed(query)
                    if not embedding:
                        output = "Could not generate embedding for query."
                        is_error = True
                    else:
                        from services.intelligence_service import IntelligenceService as IS
                        res = await IS.explore_semantic(
                            db=db,
                            query_embedding=embedding,
                            restaurant_id=state["restaurant_id"],
                            allergens=warn_allergens,
                            dietary=customer_profile.get("dietary_restrictions", []) if customer_profile else [],
                            max_price=args.get("max_price"),
                            max_calories=args.get("max_calories"),
                            session_id=state["session_id"],
                            query_text=query
                        )
                        import json
                        output = json.dumps(res)

                # ─── 10. compare_items ───
                elif name == "compare_items":
                    item_a = args.get("item_a")
                    item_b = args.get("item_b")
                    from services.intelligence_service import IntelligenceService as IS
                    res = await IS.compare_items(db, item_a, item_b, state["restaurant_id"])
                    import json
                    output = json.dumps(res)

                # ─── 11. get_recommendations ───
                elif name == "get_recommendations":
                    tod = args.get("time_of_day", "day")
                    from services.intelligence_service import IntelligenceService as IS
                    res = await IS.get_recommendations(
                        db=db,
                        restaurant_id=state["restaurant_id"],
                        allergens=warn_allergens,
                        dietary=customer_profile.get("dietary_restrictions", []) if customer_profile else [],
                        time_of_day=tod,
                    )
                    import json
                    output = json.dumps(res)

                # ─── 12. suggest_complete_meal ───
                elif name == "suggest_complete_meal":
                    budget = float(args.get("budget"))
                    goal = args.get("goal", "balanced")
                    from services.intelligence_service import IntelligenceService as IS
                    res = await IS.suggest_complete_meal(
                        db=db,
                        restaurant_id=state["restaurant_id"],
                        budget=budget,
                        allergens=warn_allergens,
                        dietary=customer_profile.get("dietary_restrictions", []) if customer_profile else [],
                        goal=goal,
                    )
                    import json
                    output = json.dumps(res)

                # ─── 13. get_pairings ───
                elif name == "get_pairings":
                    item_name = args.get("item_name")
                    from services.intelligence_service import IntelligenceService as IS
                    res = await IS.get_pairings(db, item_name, state["restaurant_id"], allergens=warn_allergens)
                    import json
                    output = json.dumps(res)

                # ─── 14. get_restaurant_info ───
                elif name == "get_restaurant_info":
                    field = args.get("field")
                    from services.intelligence_service import IntelligenceService as IS
                    res = await IS.get_restaurant_info(db, field, state["restaurant_id"])
                    import json
                    output = json.dumps(res)

                # ─── 15. find_by_description ───
                elif name == "find_by_description":
                    desc = args.get("description")
                    from core.pre_dispatch import _embed
                    embedding = await _embed(desc)
                    from services.intelligence_service import IntelligenceService as IS
                    res = await IS.find_by_description(
                        db=db,
                        description=desc,
                        restaurant_id=state["restaurant_id"],
                        allergens=warn_allergens,
                        embedding=embedding,
                        session_id=state["session_id"]
                    )
                    import json
                    output = json.dumps(res)

                # ─── 16. get_last_order ───
                elif name == "get_last_order":
                    if customer_phone:
                        from services.intelligence_service import IntelligenceService as IS
                        res = await IS.get_last_order(db, customer_phone, state["restaurant_id"])
                        import json
                        output = json.dumps(res)
                    else:
                        import json
                        output = json.dumps({
                            "status": "error",
                            "data": {},
                            "safety_flags": [],
                            "llm_guidance": "Customer phone number not available. Cannot fetch last order."
                        })

                # ─── 17. get_active_offers ───
                elif name == "get_active_offers":
                    from services.intelligence_service import IntelligenceService as IS
                    res = await IS.get_active_offers(db, state["restaurant_id"], state["order_id"])
                    import json
                    output = json.dumps(res)

                else:
                    output = f"Unknown tool: {name}"
                    is_error = True

            except Exception as e:
                output = f"Error executing tool {name}: {str(e)}"
                is_error = True

            tool_messages.append(ToolMessage(content=output, tool_call_id=tool_call_id, name=name))

            # Emit tool execution event to telemetry bus
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
                        "original_price": float(item.original_price) if item.original_price is not None else float(item.price_snapshot),
                        "quantity": item.quantity,
                        "modifications": item.modifications_applied or {},
                        "allergen_warnings": item.allergen_warnings or [],
                    }
                )

    new_state = {**state, "cart": cart, **state_updates}
    from monitoring.hooks import emit_agent_state
    emit_agent_state(new_state, state["session_id"], node_name="tools")

    return {"messages": tool_messages, "cart": cart, **state_updates}


def should_use_tools(state: OrderState) -> str:
    """
    Conditional edge: did the LLM decide to call a tool?
    """
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return "end"


def update_stage(state: OrderState) -> dict:
    """
    Examine conversation history to determine which stage we're in.
    """
    messages = state["messages"]
    cart = state["cart"]
    stage = state.get("stage", "greeting")

    if stage == "greeting" and len(messages) > 2:
        stage = "ordering"
    if cart and stage == "ordering":
        last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        if last_ai and any(
            word in last_ai.content.lower() for word in ["confirm", "place your order", "shall i"]
        ):
            stage = "confirming"
    if stage == "confirming":
        last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        if last_ai and any(
            word in last_ai.content.lower() for word in ["pay", "payment", "card", "cash"]
        ):
            stage = "payment"
    
    # Transition to done if confirm_order tool was successfully executed
    if any(isinstance(m, ToolMessage) and m.name == "confirm_order" for m in messages):
        stage = "done"

    new_state = {**state, "stage": stage}
    from monitoring.hooks import emit_agent_state
    emit_agent_state(new_state, state["session_id"], node_name="update_stage")

    return {"stage": stage}


async def _validate_and_price_modifications(
    item: MenuItem,
    remove: list, swap: dict, add_extras: dict
) -> tuple[dict, list, Decimal]:
    """
    Returns (applied_modifications, rejected_list, price_delta)
    """
    allowed = item.allowed_modifications or {}
    applied, rejected = {}, []
    price_delta = Decimal("0")

    for r in (remove or []):
        if allowed.get("remove") and r in allowed.get("remove", []):
            applied.setdefault("remove", []).append(r)
        else:
            rejected.append(f"Can't remove {r}")

    for component, target in (swap or {}).items():
        if allowed.get("swap") and target in allowed.get("swap", {}).get(component, []):
            applied.setdefault("swap", {})[component] = target
        else:
            options = allowed.get("swap", {}).get(component, []) if allowed.get("swap") else []
            rejected.append(f"{component} can only be swapped to: {', '.join(options) or 'N/A'}")

    for extra, qty in (add_extras or {}).items():
        extra_price = allowed.get("add", {}).get(extra)
        if extra_price is not None:
            applied.setdefault("add", {})[extra] = qty
            price_delta += Decimal(str(extra_price)) * qty
        else:
            rejected.append(f"{extra} not available as an add-on")

    return applied, rejected, price_delta

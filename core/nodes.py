from sqlalchemy import select, text
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage
from core.state import OrderState, CartItem
import time
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

# Bind tools to the LLM once at startup
_llm = llm_provider.get_chat_model()
_llm_with_tools = _llm.bind_tools(ORDER_TOOLS)


async def chatbot_node(state: OrderState) -> dict:
    """
    Core LLM node — processes messages and decides what to do next.
    Optionally calls tools or responds directly.
    """
    from monitoring.hooks import emit_agent_state
    from core.session_context import build_session_context

    emit_agent_state(state, state["session_id"], node_name="chatbot")

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

        updated_state_fields = {}
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
        user_messages = [m for m in state["messages"] if m.type == "human"]
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

        # Build system prompt dynamically from restaurant + menu
        system_prompt = build_system_prompt(ctx, state["cart"], state["stage"])

    # Prepend system message to conversation history
    messages = [SystemMessage(content=system_prompt)] + state["messages"]

    # Call LLM
    response = await _llm_with_tools.ainvoke(messages)
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
                        
                        # Check allergen block
                        item_allergens = menu_item.allergens or []
                        overlapping_strict = list(set(item_allergens) & set(strict_allergens))
                        
                        if overlapping_strict:
                            output = f"Cannot add {menu_item.name} because it contains allergens you must strictly avoid: {', '.join(overlapping_strict)}."
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
                            
                            # Telemetry & Warning for soft allergens
                            overlapping_warn = list(set(item_allergens) & set(warn_allergens))
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
                        
                        # Allergen Block
                        item_allergens = menu_item.allergens or []
                        overlapping_strict = list(set(item_allergens) & set(strict_allergens))
                        
                        if overlapping_strict:
                            output = f"Cannot add {menu_item.name} because it contains allergens you must strictly avoid: {', '.join(overlapping_strict)}."
                            is_error = True
                        else:
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
                                
                                await OrderService.add_item(
                                    db, state["order_id"], menu_item, quantity,
                                    price_snapshot=final_price, original_price=original_price,
                                    modifications_applied=applied_mods
                                )
                                output = f"Added {quantity}x {menu_item.name} with modifications."
                                
                                # Allergen warnings
                                overlapping_warn = list(set(item_allergens) & set(warn_allergens))
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

                # ─── 6. search_menu ───
                elif name == "search_menu":
                    query = args.get("query")
                    safe_only = args.get("safe_only", False)
                    items = await MenuService.search_items(
                        db, state["restaurant_id"], query, limit=5,
                        safe_only=safe_only, customer_allergens=warn_allergens
                    )
                    if not items:
                        output = "No matching items found on the menu."
                    else:
                        output = "Found the following matching items:\n" + "\n".join(
                            f"- {item['name']} (${item['price']:.2f}): {item['description'] or ''}"
                            for item in items
                        )

                # ─── 7. get_menu_category ───
                elif name == "get_menu_category":
                    cat_name = args.get("category_name")
                    menu = await MenuService.get_contextual_menu(db, state["restaurant_id"], now_time)
                    matching_cat = None
                    for cat in menu.keys():
                        if cat.lower() == cat_name.lower():
                            matching_cat = cat
                            break
                    
                    if not matching_cat:
                        output = f"Could not find category '{cat_name}'."
                    else:
                        output = f"Items in {matching_cat}:\n" + "\n".join(
                            f"- {item['name']} (${item['price']:.2f}): {item['description'] or ''}"
                            for item in menu[matching_cat]
                        )

                # ─── 8. check_item_availability ───
                elif name == "check_item_availability":
                    item_name = args.get("item_name")
                    items = await MenuService.search_items(db, state["restaurant_id"], item_name, limit=1)
                    if not items:
                        output = f"Could not find item '{item_name}'."
                    else:
                        menu_item = await MenuService.get_item_by_id(db, items[0]["id"], state["restaurant_id"])
                        if menu_item.available_quantity is not None and menu_item.available_quantity <= 0:
                            output = f"Sorry, {menu_item.name} is currently sold out."
                        else:
                            output = f"{menu_item.name} is available."

                # ─── 9. check_allergens_in_cart ───
                elif name == "check_allergens_in_cart":
                    if not customer_profile:
                        output = "No allergen profile on file. Please provide your phone number to check allergies."
                    else:
                        unsafe_items = []
                        order = await OrderService.get_order_with_items(db, state["order_id"])
                        for item in order.items:
                            menu_item = await MenuService.get_item_by_id(db, item.menu_item_id, state["restaurant_id"])
                            matched = list(set(menu_item.allergens or []) & set(warn_allergens))
                            if matched:
                                unsafe_items.append(f"{menu_item.name} contains: {', '.join(matched)}")
                        
                        if not unsafe_items:
                            output = "Great news! No allergen conflicts detected for items in your cart."
                        else:
                            output = "Allergen warnings for your current cart:\n" + "\n".join(f"- {x}" for x in unsafe_items)

                # ─── 10. get_item_allergens ───
                elif name == "get_item_allergens":
                    item_name = args.get("item_name")
                    items = await MenuService.search_items(db, state["restaurant_id"], item_name, limit=1)
                    if not items:
                        output = f"Could not find item '{item_name}'."
                    else:
                        menu_item = await MenuService.get_item_by_id(db, items[0]["id"], state["restaurant_id"])
                        ingredients = ", ".join(menu_item.ingredients or []) or "None listed"
                        allergens = ", ".join(menu_item.allergens or []) or "None"
                        output = f"{menu_item.name} ingredients: {ingredients}. Allergens: {allergens}."

                # ─── 11. get_nutrition_summary ───
                elif name == "get_nutrition_summary":
                    order = await OrderService.get_order_with_items(db, state["order_id"])
                    if not order or not order.items:
                        output = "Your order is empty."
                    else:
                        calories, protein, carbs, fat = 0, 0, 0, 0
                        for item in order.items:
                            m = await MenuService.get_item_by_id(db, item.menu_item_id, state["restaurant_id"])
                            nut = m.nutrition_info or {}
                            calories += int(nut.get("calories", 0)) * item.quantity
                            protein += float(nut.get("protein_g", 0)) * item.quantity
                            carbs += float(nut.get("carbs_g", 0)) * item.quantity
                            fat += float(nut.get("fat_g", 0)) * item.quantity
                        
                        output = f"Nutrition summary for your cart:\n- Calories: {calories} kcal\n- Protein: {protein:.1f}g\n- Carbs: {carbs:.1f}g\n- Fat: {fat:.1f}g"

                # ─── 12. get_last_order ───
                elif name == "get_last_order":
                    phone = args.get("customer_phone")
                    customer_phone = phone
                    state_updates["customer_phone"] = phone
                    
                    last_order_items = await ProfileService.get_order_history_summary(db, phone, state["restaurant_id"])
                    if not last_order_items:
                        # Try to load profile to check if returning
                        profile = await ProfileService.get_by_phone(db, phone)
                        if profile:
                            state_updates["customer_profile"] = {
                                "id": profile.id,
                                "name": profile.name,
                                "phone": profile.phone,
                                "email": profile.email,
                                "language_code": profile.language_code,
                                "dietary_restrictions": profile.dietary_restrictions,
                                "allergens": profile.allergens,
                                "strict_allergens": profile.strict_allergens,
                                "preferences": profile.preferences
                            }
                        output = "Could not find any past completed orders for this phone number."
                    else:
                        output = f"Your last order: {last_order_items.replace('Frequent orders at this restaurant: ', '')}. Would you like to repeat it?"

                # ─── 13. get_popular_pairings ───
                elif name == "get_popular_pairings":
                    item_name = args.get("item_name")
                    items = await MenuService.search_items(db, state["restaurant_id"], item_name, limit=1)
                    if not items:
                        output = "Could not find item."
                    else:
                        item_id = items[0]["id"]
                        
                        # Query materialized view for pairing
                        res = await db.execute(
                            text("SELECT item_b_id, paired_item_name, paired_item_price, lift_score FROM top_pairings WHERE item_a_id = :id AND lift_score > 1.5"),
                            {"id": item_id}
                        )
                        row = res.fetchone()
                        if row and row.item_b_id not in upsells_shown_list:
                            upsells_shown_list.append(row.item_b_id)
                            state_updates["upsells_shown"] = upsells_shown_list
                            
                            from monitoring.hooks import emit_upsell
                            emit_upsell(row.paired_item_name, items[0]["name"], float(row.lift_score), state["session_id"])
                            
                            output = f"Most people who order {items[0]['name']} also get {row.paired_item_name} (${float(row.paired_item_price):.2f}) — want one?"
                        else:
                            output = "No pairing recommendation available."

                # ─── 14. save_customer_preference ───
                elif name == "save_customer_preference":
                    phone = args.get("customer_phone")
                    pref_type = args.get("preference_type")
                    val = args.get("value")
                    
                    profile = await ProfileService.get_by_phone(db, phone)
                    profile_data = {"phone": phone}
                    if profile:
                        profile_data = {
                            "phone": phone,
                            "name": profile.name,
                            "email": profile.email,
                            "language_code": profile.language_code,
                            "dietary_restrictions": list(profile.dietary_restrictions or []),
                            "allergens": list(profile.allergens or []),
                            "strict_allergens": list(profile.strict_allergens or []),
                            "preferences": dict(profile.preferences or {})
                        }
                    
                    if pref_type == "allergen":
                        allergens = profile_data.setdefault("allergens", [])
                        if val not in allergens:
                            allergens.append(val)
                    elif pref_type == "dietary":
                        dietary = profile_data.setdefault("dietary_restrictions", [])
                        if val not in dietary:
                            dietary.append(val)
                    elif pref_type == "language":
                        profile_data["language_code"] = val
                    elif pref_type == "name":
                        profile_data["name"] = val

                    updated_profile = await ProfileService.upsert_profile(db, profile_data)
                    state_updates["customer_phone"] = phone
                    state_updates["customer_profile"] = {
                        "id": updated_profile.id,
                        "name": updated_profile.name,
                        "phone": updated_profile.phone,
                        "email": updated_profile.email,
                        "language_code": updated_profile.language_code,
                        "dietary_restrictions": updated_profile.dietary_restrictions,
                        "allergens": updated_profile.allergens,
                        "strict_allergens": updated_profile.strict_allergens,
                        "preferences": updated_profile.preferences
                    }
                    output = f"Saved your {pref_type} preference: '{val}'."

                # ─── 15. get_active_promotions ───
                elif name == "get_active_promotions":
                    promos = []
                    for r in price_rules:
                        promos.append(f"- {r.label}: {r.description}")
                    if not promos:
                        output = "No promotions are currently active today."
                    else:
                        output = "Active promotions today:\n" + "\n".join(promos)

                # ─── 16. validate_order_rules ───
                elif name == "validate_order_rules":
                    res = await RuleService.validate_order_rules(db, state["order_id"], state["restaurant_id"])
                    
                    # Telemetry
                    if not res["valid"]:
                        for violation in res["violations"]:
                            from monitoring.hooks import emit_rule_violation
                            # Wait, does emit_rule_violation exist? Let's check monitoring/hooks.py
                            # If not, we can run general event or create it. Let's make sure we check
                            # or just emit to EventBus
                            from monitoring.events import bus, Event, EK
                            bus.emit(Event(
                                kind=EK.RULE,
                                title=f"Rule hit: {violation['rule']}",
                                session_id=state["session_id"],
                                detail=violation
                            ))
                    
                    import json
                    output = json.dumps(res)

                # ─── 17. get_order_summary ───
                elif name == "get_order_summary":
                    order = await OrderService.get_order_with_items(db, state["order_id"])
                    if not order or not order.items:
                        output = "Your order is currently empty."
                    else:
                        output = OrderService.format_receipt(order)

                # ─── 18. confirm_order ───
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

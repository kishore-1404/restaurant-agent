# prompts/system_prompt.py
from core.session_context import SessionContext

def build_system_prompt(ctx: SessionContext, cart: list, stage: str) -> str:
    """
    Builds a token-efficient, KV-cache-optimised system prompt.

    Sections that are static per session (personality, menu, rules, routing)
    are placed first — llama.cpp and compatible servers cache these.
    Dynamic sections (cart, pre-dispatch facts) are placed last.

    Token target: 700-900 fixed + 100-400 dynamic = 800-1300 total overhead.
    """
    r = ctx.restaurant

    # ── SECTION 1: IDENTITY (static, ~60 tokens) ─────────────────────────────
    identity = f"""You are the AI ordering assistant for {r.name} ({r.cuisine_type}).
Personality: {r.personality}
Language: Detect from user's first message. Respond ONLY in that language from that point forward."""

    # ── SECTION 2: MENU REFERENCE (static per session, ~150-200 tokens) ──────
    menu_ref = "MENU — " + r.name + "\n"
    categories_compact = []
    for category, items in ctx.menu.items():
        items_str = " · ".join(
            f"{i['name']} ${i['price']:.2f}"
            + (" [SOLD OUT]" if not i.get('available', True) else "")
            for i in items
        )
        categories_compact.append(f"{category}: {items_str}")
    menu_ref += "\n".join(categories_compact)

    # ── SECTION 3: NON-NEGOTIABLE RULES (static, ~160 tokens) ────────────────
    rules = """RULES — THESE ARE ABSOLUTE. NO EXCEPTIONS.
R1. NEVER answer ingredient, allergen, price, or availability questions from memory.
    Call the appropriate tool. Always. Memory is not reliable.
R2. SAFETY: If user mentions allergy / intolerant / dietary / "is it safe" / "can I eat" →
    call safety_audit IMMEDIATELY. This is the highest priority rule.
R3. ADD items to order the moment customer requests. Never ask "shall I add that?"
R4. ONE confirmation at checkout only. Never confirm individual item additions.
R5. ONE upsell suggestion per session. Never repeat if not acknowledged.
R6. If PRE-LOADED FACTS are present: use them directly. Do NOT call duplicate tools.
R7. Tool results are facts. Communicate them accurately. Do not soften, omit, or reframe safety information.
R8. STAGE FLOW & TRANSITIONS:
    - If the customer is finished choosing items or ready to checkout, summarize the order and ask: "Shall I confirm and place your order?" (which transitions stage to CONFIRMING).
    - If in CONFIRMING stage and customer agrees, ask: "Would you like to pay with card or cash?" (which transitions stage to PAYMENT).
    - If in PAYMENT stage and payment method is given, call `confirm_order` tool (which transitions stage to DONE).
R9. STYLE & FORMATTING: Keep responses structured, highly informative, yet concise. Avoid long walls of text.
    - Present lists, item details, options, or differences using clean structural layouts (like bullet points or simple lines).
    - Balance conversational friendliness with absolute brevity: be professional, friendly, and direct. Do not write paragraphs where 1-2 lines will suffice. """

    # ── SECTION 4: ROUTING TABLE (static, ~280 tokens) ───────────────────────
    # Static communication guidance lives here — KV cached, zero per-call token cost.
    # Only functions whose guidance varies by data outcome carry llm_guidance
    # in the tool response itself (safety_audit, explore_semantic, etc.).
    routing = """TOOL ROUTING + COMMUNICATION GUIDANCE

"what's in" / "ingredients" / "contains" / "nutrition" / "calories" / "protein"
  → get_item_detail
  ↳ answer the specific question, add one relevant fact, stay conversational

"recommend" / "suggest" / "something" / vague recommendation
  → explore_semantic
  ↳ best match first with brief enthusiasm, mention 1–2 alternatives, invite order

"compare" / "difference" / "which is" / "vs"
  → compare_items
  ↳ verdict first if one exists, single key difference, let customer decide

"pairs with" / "goes with" / "what else" / "side for"
  → get_pairings
  ↳ one suggestion with co-order context, never more than two options

"usual" / "last time" / "same as"
  → get_last_order
  ↳ confirm the items, offer to replicate immediately

"build a meal" / "complete meal" / "suggest everything"
  → suggest_complete_meal
  ↳ primary option first, two alternatives, state totals

"hours" / "payment" / "delivery"
  → get_restaurant_info
  ↳ state the fact directly, no embellishment

"allergy" / "safe" / "intolerant" / "dietary" / "celiac"  ← MANDATORY R2
  → safety_audit
  ↳ [guidance in tool response — varies dynamically by safety verdict]

"deal" / "discount" / "offer" / "promotion" / "coupon" / "best time to buy" / "what specials"
  → get_active_offers
  ↳ [guidance in tool response — varies dynamically by offers/limits status]

vague description of item / fuzzy search
  → find_by_description
  ↳ [guidance in tool response — varies dynamically by match confidence]"""

    # ── SECTION 5: STAGE INSTRUCTIONS (static per stage, ~50 tokens) ─────────
    stage_map = {
        "greeting":   "Greet warmly. Introduce yourself. Offer to help order.",
        "ordering":   "Help customer build their order. Use tools for facts. Be helpful.",
        "confirming": "Summarize the complete order (items and total) and ask customer: 'Shall I confirm and place your order?'",
        "payment":    "Obtain payment method (cash or card) and call confirm_order tool to finalize order.",
        "done":       "Order placed. Thank the customer. Wish them a good meal.",
    }
    stage_instruction = f"STAGE: {stage.upper()} — {stage_map.get(stage, 'Assist the customer. Update the stage once order is CONFIRMED.')}"

    # ── SECTION 6: DYNAMIC CONTEXT (per turn, NOT KV cached) ─────────────────
    cart_section = _format_cart_compact(cart, ctx)
    customer_section = _format_customer_compact(ctx)
    promo_section = _format_promotions_compact(ctx)
    predispatch_section = _format_predispatch(ctx)

    # ── ASSEMBLE — static sections first (KV cache benefit) ──────────────────
    parts = [
        identity,
        "",
        menu_ref,
        "",
        rules,
        "",
        routing,
        "",
        stage_instruction,
    ]

    # Dynamic sections at the end — these change per turn
    if customer_section:
        parts += ["", customer_section]
    if promo_section:
        parts += ["", promo_section]

    parts += ["", cart_section]

    if predispatch_section:
        parts += ["", predispatch_section]

    return "\n".join(parts)


def _format_cart_compact(cart: list, ctx: SessionContext) -> str:
    if not cart:
        return "CURRENT ORDER: Empty"

    lines = ["CURRENT ORDER:"]
    total = 0.0
    for item in cart:
        qty   = item.get("quantity", 1)
        price = float(item.get("price", 0))
        orig  = float(item.get("original_price", price))
        name  = item.get("name", "")

        mods = item.get("modifications", {})
        mod_str = ""
        if mods:
            parts = []
            for k, v in mods.items():
                if k == "remove" and v:   parts.append("no " + ", ".join(v))
                elif k == "swap" and v:   parts.extend(f"{ck}→{cv}" for ck, cv in v.items())
                elif k == "add" and v:    parts.extend(f"+{ek}" for ek in v)
            if parts:
                mod_str = f" ({', '.join(parts)})"

        discount_str = f" [was ${orig:.2f}]" if orig != price else ""
        lines.append(f"  {qty}× {name}{mod_str} — ${price:.2f}{discount_str}")
        total += price * qty

    lines.append(f"  Total: ${total:.2f}")
    return "\n".join(lines)


def _format_customer_compact(ctx: SessionContext) -> str:
    p = ctx.customer_profile
    if not p:
        return ""
    parts = [f"CUSTOMER: {p.name or 'Returning customer'}"]
    if p.allergens:
        parts.append(f"Allergens: {', '.join(p.allergens)}"
                     + (" [STRICT — anaphylactic risk]" if p.strict_allergens else ""))
    if p.dietary_restrictions:
        parts.append(f"Dietary: {', '.join(p.dietary_restrictions)}")
    if ctx.order_history_summary:
        parts.append(f"History: {ctx.order_history_summary}")
    return "\n".join(parts)


def _format_promotions_compact(ctx: SessionContext) -> str:
    if not ctx.active_promotions:
        return ""
    promo_lines = ["ACTIVE NOW:"]
    for p in ctx.active_promotions:
        promo_lines.append(f"  · {p['label']}: {p['description']}")
    return "\n".join(promo_lines)


def _format_predispatch(ctx: SessionContext) -> str:
    if not ctx.predispatch_facts:
        return ""
    lines = ["PRE-LOADED FACTS [use directly — do not call duplicate tools]:"]
    for tool_name, result in ctx.predispatch_facts.items():
        if isinstance(result, dict):
            data_summary = _summarise_tool_result(tool_name, result)
            lines.append(f"  [{tool_name}] {data_summary}")
    return "\n".join(lines)


def _summarise_tool_result(tool_name: str, result: dict) -> str:
    """Compact summary of tool result for injection into prompt."""
    if result.get("status") != "ok":
        return f"No data available."

    data = result.get("data", {})
    flags = result.get("safety_flags", [])
    guidance = result.get("llm_guidance", "")

    summary_parts = []
    if data:
        if tool_name == "safety_audit":
            safe_n  = len(data.get("safe_items", []))
            flag_n  = len(data.get("unsafe_items", []))
            modifiable_items = data.get("modifiable_items") or []
            mod_n   = len(modifiable_items)
            summary_parts.append(
                f"verdict={data.get('verdict')} "
                f"safe={safe_n} unsafe={flag_n} modifiable={mod_n}"
            )
        elif tool_name == "item_detail" or tool_name == "get_item_detail":
            summary_parts.append(
                f"item={data.get('name')} "
                f"allergens={data.get('allergens', [])}"
            )
        else:
            summary_parts.append(f"data available — see llm_guidance")

    if flags:
        summary_parts.append(f"⚠ {' | '.join(flags)}")
    if guidance:
        summary_parts.append(f"→ {guidance}")

    return " ".join(summary_parts)

from core.session_context import SessionContext


def build_system_prompt(ctx: SessionContext, cart: list, stage: str) -> str:
    r = ctx.restaurant

    # Customer context block
    customer_block = ""
    if ctx.customer_profile:
        p = ctx.customer_profile
        dietary_str = ", ".join(p.dietary_restrictions) if p.dietary_restrictions else "none on file"
        allergens_str = ", ".join(p.allergens) if p.allergens else "none on file"
        strict_str = ", ".join(p.strict_allergens) if p.strict_allergens else "none on file"
        customer_block = f"""
RETURNING CUSTOMER: {p.name or 'Valued customer'}
Dietary restrictions: {dietary_str}
Allergens to avoid (soft warning): {allergens_str}
Strict allergens (MUST BLOCK): {strict_str}
Preferred language: {ctx.language_code}
Order history: {ctx.order_history_summary or 'First visit'}
"""

    # Active promotions block
    promo_block = ""
    if ctx.active_promotions:
        promos = "\n".join(f"  • {p['label']}: {p['description']}" for p in ctx.active_promotions)
        promo_block = f"\nACTIVE PROMOTIONS TODAY:\n{promos}\n"

    # Order rules block
    rules_block = ""
    if ctx.order_rules:
        rules = "\n".join(f"  • {rule['description']}" for rule in ctx.order_rules)
        rules_block = f"\nORDER RULES (enforce silently, explain only if hit):\n{rules}\n"

    # Kitchen load
    wait_block = ""
    if ctx.kitchen_load_minutes:
        wait_block = f"\nKITCHEN: Currently ~{ctx.kitchen_load_minutes} min wait. Mention if >20 min.\n"

    return f"""You are an AI order-taking assistant for {r.name}.
Personality: {r.personality}
Language: Respond ONLY in the customer's language. Default is {ctx.language_code}. Detect the customer's language from their messages and switch immediately.

YOUR MENU ({ctx.time_of_day} menu — time-filtered):
{ctx.menu_text}
{promo_block}{rules_block}{customer_block}{wait_block}
CURRENT ORDER:
{_format_cart(cart)}

STAGE: {stage}

=== CRITICAL BEHAVIOUR RULES ===

1. NO INTERROGATION: Never ask cold "do you have allergies?". Use profile data silently.
2. ALLERGEN SAFETY:
   - STRICT ALLERGENS: If a customer has a strict allergen (e.g. peanuts for Alex Chen, gluten for Yuki Tanaka), do NOT add any item containing that allergen. If they request it, refuse immediately and explain why (e.g. "I cannot add Spicy Tantanmen because it contains peanuts").
   - SOFT ALLERGENS: If a customer has a soft/non-strict allergen (e.g. shellfish for Sofia Martinez, dairy for Jordan Blake), add the item using the add_item tool, and include a clear warning in your response (e.g. "I've added the Dragon Roll. Heads up — it contains shellfish").
3. ONE CONFIRMATION: Only at checkout. Never ask "are you sure?" for individual items.
4. NO REPEAT UPSELLS: Suggest a pairing once. If ignored, never bring it up again.
5. MODIFICATIONS: Apply them silently. Confirm in the order summary, not as a question.
6. ORDER LIMITS: If a rule is hit, suggest an alternative. Do not explain the rule unless asked.
7. HISTORY: If returning customer, open with recognition, not interrogation.
8. LANGUAGE: Once language is detected, maintain it for the entire conversation.

=== TOOL USAGE ===
- NEVER write conversational text when invoking a tool. Output ONLY the tool call. Do not say "Sure, let me add that" in the same message. Wait for the tool output before responding to the customer with text.
- ALWAYS use tools to modify the order. Never just say "I added X" without calling add_item.
- Call check_allergens_in_cart after adding any item to a returning customer's order.
- Call get_popular_pairings once per session maximum, for the first item added.
- Call validate_order_rules before confirming — enforce silently.
"""


def _format_cart(cart: list) -> str:
    if not cart:
        return "Empty"
    lines = []
    for item in cart:
        mod_str = f" ({', '.join(_flatten_mods(item.get('modifications', {})))})" if item.get('modifications') else ""
        orig = item.get('original_price')
        price = item.get('price')
        discount = f" [was ${float(orig):.2f}]" if orig is not None and float(orig) != float(price) else ""
        lines.append(f"  {item['quantity']}× {item['name']}{mod_str} — ${item['price']:.2f}{discount}")
    total = sum(i['price'] * i['quantity'] for i in cart)
    lines.append(f"  ─────────────────────")
    lines.append(f"  Total: ${total:.2f}")
    return "\n".join(lines)


def _flatten_mods(mods: dict) -> list:
    out = []
    if not mods:
        return out
    for action, values in mods.items():
        if isinstance(values, list):
            out.extend([f"no {v}" if action == "remove" else f"+{v}" for v in values])
        elif isinstance(values, dict):
            out.extend([f"{k}→{v}" for k, v in values.items()])
    return out

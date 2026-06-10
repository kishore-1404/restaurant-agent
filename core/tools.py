# core/tools.py  — complete replacement
from langchain_core.tools import tool


# ─── ORDER MODIFICATION TOOLS ─────────────────────────────────────────────────

@tool
def add_item(item_name: str, quantity: int = 1) -> str:
    """
    Add a menu item to the order. Use exact item name from the menu.
    For items with modifications, use add_item_with_modifications instead.
    """
    return f"Added {quantity}x {item_name}"


@tool
def add_item_with_modifications(
    item_name: str,
    quantity: int = 1,
    remove: list[str] = None,
    swap: dict = None,
    add_extras: dict = None,
) -> str:
    """
    Add a menu item with specific modifications (remove ingredients,
    swap components, add extras). Validates against item's allowed_modifications.
    """
    return f"Added {quantity}x {item_name} with modifications"


@tool
def remove_item(item_name: str) -> str:
    """Remove a menu item from the current order."""
    return f"Removed {item_name}"


@tool
def update_item_quantity(item_name: str, new_quantity: int) -> str:
    """Change the quantity of an item already in the order."""
    return f"Updated {item_name} quantity to {new_quantity}"


@tool
def clear_order() -> str:
    """Remove all items from the order. Only call if customer explicitly asks to start over."""
    return "Cleared all items from order."


# ─── MENU INTELLIGENCE TOOLS ──────────────────────────────────────────────────

@tool
def search_menu(query: str, safe_only: bool = False) -> str:
    """
    Full-text search the menu. Returns matching items with prices.
    Set safe_only=True to filter out items conflicting with customer's dietary profile.
    """
    return f"Searching menu for: {query}"


@tool
def get_menu_category(category_name: str) -> str:
    """Get all available items in a specific category."""
    return f"Fetching items in category: {category_name}"


@tool
def check_item_availability(item_name: str) -> str:
    """Check if a specific item is currently available (stock, time restrictions)."""
    return f"Checking availability for: {item_name}"


# ─── ALLERGEN & NUTRITION TOOLS ───────────────────────────────────────────────

@tool
def check_allergens_in_cart() -> str:
    """
    Check all items in the current cart against the customer's allergen profile.
    Returns list of items with allergen conflicts.
    Only meaningful if customer has a known profile.
    """
    return "Checking allergens in cart..."


@tool
def get_item_allergens(item_name: str) -> str:
    """Get the full list of allergens and ingredients for a specific item."""
    return f"Fetching allergens for: {item_name}"


@tool
def get_nutrition_summary() -> str:
    """
    Get the total nutritional breakdown of the current cart.
    Returns calories, protein, carbs, fat. Use only when customer asks.
    """
    return "Fetching nutrition summary..."


# ─── PERSONALISATION TOOLS ────────────────────────────────────────────────────

@tool
def get_last_order(customer_phone: str) -> str:
    """
    Get the customer's most recent order at this restaurant.
    Use when customer says 'same as last time' or 'my usual'.
    """
    return f"Fetching last order for customer: {customer_phone}"


@tool
def get_popular_pairings(item_name: str) -> str:
    """
    Get the item most commonly ordered alongside this one.
    Call ONCE per session after the first item is added.
    Returns None if no strong pairing exists.
    """
    return f"Fetching popular pairings for: {item_name}"


@tool
def save_customer_preference(
    customer_phone: str,
    preference_type: str,   # "allergen" | "dietary" | "name" | "language"
    value: str,
) -> str:
    """
    Save a preference to the customer's profile for future visits.
    Only call AFTER customer explicitly said "yes, remember this" or similar.
    """
    return f"Saving preference {preference_type} for customer: {customer_phone}"


# ─── PROMOTIONS & RULES TOOLS ─────────────────────────────────────────────────

@tool
def get_active_promotions() -> str:
    """
    List all currently active promotions and deals.
    Use to answer questions about today's specials or discounts.
    """
    return "Fetching active promotions..."


@tool
def validate_order_rules() -> str:
    """
    Validate the current order against all active order rules (limits, minimums, etc.).
    ALWAYS call this before confirming an order.
    Returns {"valid": bool, "issues": [{"description": str, "suggestion": str}]}
    """
    return "Validating order rules..."


# ─── ORDER LIFECYCLE TOOLS ────────────────────────────────────────────────────

@tool
def get_order_summary() -> str:
    """
    Get a formatted summary of the current order with items, modifications,
    applied discounts, and total. Call when customer asks what's in their order.
    """
    return "Fetching order summary..."


@tool
def confirm_order(payment_method: str = "card") -> str:
    """
    Finalize and place the order. Call ONLY after:
    1. validate_order_rules() returned valid=True
    2. Customer explicitly confirmed (said "yes", "confirm", "place it", etc.)
    Do NOT call this proactively.
    """
    return f"Confirming order with payment: {payment_method}"


# Export all
ORDER_TOOLS = [
    add_item, add_item_with_modifications, remove_item,
    update_item_quantity, clear_order,
    search_menu, get_menu_category, check_item_availability,
    check_allergens_in_cart, get_item_allergens, get_nutrition_summary,
    get_last_order, get_popular_pairings, save_customer_preference,
    get_active_promotions, validate_order_rules,
    get_order_summary, confirm_order,
]

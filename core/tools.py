# core/tools.py
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


# ─── SQL-BACKED INTELLIGENCE TOOLS ────────────────────────────────────────────

@tool
def safety_audit(allergens: list[str], dietary: list[str]) -> str:
    """
    Audit the menu or order safety based on allergens and dietary restrictions.
    Returns safe items, unsafe items, and items that can be modified to be safe.
    """
    return "Running safety audit..."


@tool
def get_item_detail(item_name: str) -> str:
    """
    Get detailed information about a menu item, including description, price, ingredients, and allergens.
    """
    return f"Fetching details for {item_name}..."


@tool
def explore_semantic(query: str, max_price: float = None, max_calories: int = None) -> str:
    """
    Search menu items using semantic search. Useful when the customer describes what they want vaguely.
    """
    return f"Exploring items matching: {query}..."


@tool
def compare_items(item_a: str, item_b: str) -> str:
    """
    Compare two menu items in detail (ingredients, allergens, price, nutrition).
    """
    return f"Comparing {item_a} and {item_b}..."


@tool
def get_recommendations(time_of_day: str = "day") -> str:
    """
    Get item recommendations based on popularity, personalization, and time of day.
    """
    return f"Fetching recommendations for {time_of_day}..."


@tool
def suggest_complete_meal(budget: float, goal: str = "balanced") -> str:
    """
    Suggest a complete meal (starter + main + drink/dessert) fitting within a target budget.
    """
    return f"Suggesting meal under ${budget} (goal: {goal})..."


@tool
def get_pairings(item_name: str) -> str:
    """
    Get common pairings and side recommendations for a specific menu item.
    """
    return f"Getting pairings for {item_name}..."


@tool
def get_restaurant_info(field: str) -> str:
    """
    Get general restaurant information. Allowed field values:
    'hours', 'payment', 'delivery', 'address', 'phone', 'wifi', 'parking', 'general'.
    """
    return f"Getting restaurant {field} information..."


@tool
def find_by_description(description: str) -> str:
    """
    Find a specific menu item based on customer's fuzzy description of it.
    """
    return f"Finding item by description: {description}..."


@tool
def get_last_order() -> str:
    """
    Fetch the customer's previous completed order details.
    """
    return "Fetching last order details..."


@tool
def get_active_offers() -> str:
    """
    Retrieve active offers, promotions, discounts, and order rules (e.g. minimum order limits).
    Use this when the customer asks about deals, discounts, promotions, or coupons, or when checking order conditions.
    """
    return "Fetching active offers and promotions..."


# ─── ORDER LIFECYCLE TOOLS ────────────────────────────────────────────────────

@tool
def confirm_order(payment_method: str = "card") -> str:
    """
    Finalize and place the order. Call ONLY after:
    1. Customer explicitly confirmed (said "yes", "confirm", "place it", etc.)
    Do NOT call this proactively.
    """
    return f"Confirming order with payment: {payment_method}"


# Export all tools
ORDER_TOOLS = [
    # Modifications
    add_item,
    add_item_with_modifications,
    remove_item,
    update_item_quantity,
    clear_order,
    confirm_order,

    # Intelligence
    safety_audit,
    get_item_detail,
    explore_semantic,
    compare_items,
    get_recommendations,
    suggest_complete_meal,
    get_pairings,
    get_restaurant_info,
    find_by_description,
    get_last_order,
    get_active_offers,
]

from langchain_core.tools import tool


@tool
def add_item_to_order(item_name: str, quantity: int = 1) -> str:
    """
    Add a menu item to the customer's order.
    Use the exact item name from the menu.
    Call this whenever the customer mentions wanting to order something.
    """
    # The actual DB logic is injected at runtime via a closure.
    # This signature is what the LLM sees and decides to call.
    return f"Added {quantity}x {item_name}"


@tool
def remove_item_from_order(item_name: str) -> str:
    """
    Remove a menu item from the customer's order.
    Call this when the customer says they don't want something anymore.
    """
    return f"Removed {item_name}"


@tool
def modify_item_quantity(item_name: str, new_quantity: int) -> str:
    """
    Change the quantity of an item already in the order.
    """
    return f"Updated {item_name} quantity to {new_quantity}"


@tool
def search_menu(query: str) -> str:
    """
    Search the menu when the customer asks for something vague or with a typo.
    Use for: 'something spicy', 'that pasta dish', 'burgr' (typo), 'cheapest drink'.
    """
    return f"Searching menu for: {query}"


@tool
def get_order_summary() -> str:
    """
    Get the current order summary with all items and total.
    Call this when the customer asks what's in their order.
    """
    return "Fetching order summary..."


@tool
def confirm_and_place_order() -> str:
    """
    Finalize and confirm the order after the customer approves.
    Only call this AFTER explicitly asking the customer to confirm.
    """
    return "Order confirmed!"


# Export all tools as a list
ORDER_TOOLS = [
    add_item_to_order,
    remove_item_from_order,
    modify_item_quantity,
    search_menu,
    get_order_summary,
    confirm_and_place_order,
]

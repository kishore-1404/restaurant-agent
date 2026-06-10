from typing import TypedDict, Annotated, Optional
from langgraph.graph.message import add_messages


class CartItem(TypedDict):
    item_id: int
    name: str
    price: float
    quantity: int
    modifiers: dict


class OrderState(TypedDict):
    # LangGraph managed — messages accumulate via add_messages reducer
    messages: Annotated[list, add_messages]

    # Session context
    restaurant_id: int
    session_id: str
    customer_name: Optional[str]

    # Live cart (mirrored from DB for agent visibility)
    cart: list[CartItem]
    order_id: Optional[int]

    # Conversation stage
    stage: str          # "greeting" | "ordering" | "confirming" | "payment" | "done"

    # Menu snapshot (loaded once per session from DB/cache)
    menu_text: str      # formatted menu string injected into system prompt

    # Metadata
    error_message: Optional[str]

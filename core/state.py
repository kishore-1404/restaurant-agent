from typing import TypedDict, Annotated, Optional
from langgraph.graph.message import add_messages


class CartItem(TypedDict):
    item_id:    int
    name:       str
    price:      float       # price_at_order_time (after applied rules)
    original_price: float   # before discount
    quantity:   int
    modifications: dict     # {"remove": ["pickles"], "swap": {"patty": "chicken"}}
    allergen_warnings: list # allergens flagged for this item


class OrderState(TypedDict):
    messages:           Annotated[list, add_messages]

    # Session
    restaurant_id:      int
    session_id:         str
    language_code:      str            # detected from first user message

    # Customer
    customer_phone:     Optional[str]
    customer_name:      Optional[str]
    customer_profile:   Optional[dict] # serialised CustomerProfile

    # Order
    cart:               list[CartItem]
    order_id:           Optional[int]
    stage:              str

    # Context (refreshed from SessionContext)
    menu_text:          str
    active_promotions:  list
    order_rules:        list

    # Session guards
    allergen_warnings_shown:  list     # item_ids already warned
    upsells_shown:            list     # item_ids already suggested

    # Metadata
    error_message:      Optional[str]

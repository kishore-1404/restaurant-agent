from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from db.models import Restaurant, CustomerProfile
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class SessionContext:
    """
    All dynamic, session-level context that shapes the agent's behaviour.
    Built once at session start, refreshed when key state changes.
    """
    # Restaurant
    restaurant:         Restaurant
    menu:               dict                    # time-filtered, price-adjusted, translated
    menu_text:          str                     # formatted string for system prompt

    # Customer
    session_id:         str
    customer_profile:   Optional[CustomerProfile] = None
    customer_name:      Optional[str] = None
    language_code:      str = "en"

    # Active rules
    active_price_rules: list = field(default_factory=list)
    active_promotions:  list = field(default_factory=list)
    order_rules:        list = field(default_factory=list)

    # Context signals
    kitchen_load_minutes: Optional[int] = None  # estimated wait
    time_of_day:         str = "day"            # "morning" | "day" | "evening" | "night"

    # Session guards (prevent repetition)
    allergen_warnings_shown:  set = field(default_factory=set)  # item ids already warned
    upsells_shown:            set = field(default_factory=set)  # item ids already suggested
    language_detected:        bool = False

    # History
    order_history_summary:   Optional[str] = None  # "You usually order X"


async def build_session_context(
    db: AsyncSession,
    restaurant: Restaurant,
    session_id: str,
    customer_phone: Optional[str] = None,
    language_code: Optional[str] = None,
) -> SessionContext:
    """
    Build a fully-enriched SessionContext at conversation start.
    This replaces the scattered service calls in main.py.
    """
    from services.menu_service import MenuService
    from services.rule_service import RuleService
    from services.profile_service import ProfileService

    now = datetime.now()

    # Load customer profile if phone is provided
    profile = None
    customer_name = None
    history_summary = None
    detected_lang = language_code or "en"

    if customer_phone:
        profile = await ProfileService.get_by_phone(db, customer_phone)
        if profile:
            customer_name = profile.name
            if not language_code:
                detected_lang = profile.language_code or "en"
            history_summary = await ProfileService.get_order_history_summary(db, customer_phone, restaurant.id)
            from monitoring.hooks import emit_profile_loaded
            emit_profile_loaded(
                profile.name or "Valued customer",
                session_id,
                has_restrictions=bool(profile.allergens or profile.dietary_restrictions)
            )

    # Time-filtered, price-adjusted menu
    menu = await MenuService.get_contextual_menu(db, restaurant.id, now)

    # Active pricing and order rules
    price_rules = await RuleService.get_active_price_rules(db, restaurant.id, now)
    order_rules  = await RuleService.get_order_rules(db, restaurant.id)
    
    # Structure active promotions from price rules
    promotions = []
    for r in price_rules:
        promotions.append({
            "name": r.name,
            "label": r.label,
            "description": r.description or f"{r.label} discount active"
        })

    # Apply price rules to menu items
    for category, items in menu.items():
        for item in items:
            final_price, applied_labels = RuleService.apply_price_rules(item, price_rules)
            item["price"] = float(final_price)
            if applied_labels:
                item["applied_promotions"] = applied_labels

    # Format menu for system prompt
    customer_allergens = profile.allergens if profile else None
    menu_text = MenuService.format_for_prompt(menu, detected_lang, customer_allergens)

    # Estimate kitchen wait time
    kitchen_wait = 12
    if now.hour in [12, 13, 18, 19, 20]:
        kitchen_wait = 25

    return SessionContext(
        restaurant=restaurant,
        menu=menu,
        menu_text=menu_text,
        session_id=session_id,
        customer_profile=profile,
        customer_name=customer_name,
        language_code=detected_lang,
        active_price_rules=price_rules,
        active_promotions=promotions,
        order_rules=[{"rule_type": r.rule_type, "value": float(r.value) if r.value else None, "description": r.description, "error_message": r.error_message} for r in order_rules],
        kitchen_load_minutes=kitchen_wait,
        time_of_day=_time_of_day(now),
        order_history_summary=history_summary,
    )


def _time_of_day(dt: datetime) -> str:
    h = dt.hour
    if h < 11:  return "morning"
    if h < 17:  return "day"
    if h < 21:  return "evening"
    return "night"

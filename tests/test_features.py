import pytest
from datetime import datetime, time
from decimal import Decimal
from sqlalchemy import select, text
from db.models import Restaurant, CustomerProfile, MenuItem, MenuCategory, PriceRule, OrderRule, Order, OrderItem
from services.allergen_service import AllergenService
from services.profile_service import ProfileService
from services.rule_service import RuleService
from services.menu_service import MenuService
from services.order_service import OrderService


@pytest.fixture
async def db():
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from config import settings

    # Create a fresh engine and sessionmaker bound to the current test event loop
    engine = create_async_engine(settings.database_url, echo=False)
    
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
            
    await engine.dispose()


@pytest.mark.asyncio
async def test_allergen_service_check_and_safe_menu(db):
    # Retrieve first restaurant
    res = await db.execute(select(Restaurant).where(Restaurant.is_active == True).limit(1))
    restaurant = res.scalar_one_or_none()
    assert restaurant is not None

    # Check allergens for an item
    # Peanut Allergy profile test: phone +1-555-0101
    profile = await ProfileService.get_by_phone(db, "+1-555-0101")
    assert profile is not None
    assert "peanuts" in profile.allergens

    # Find a menu item with peanuts
    res_items = await db.execute(
        select(MenuItem)
        .where(MenuItem.restaurant_id == restaurant.id)
    )
    items = res_items.scalars().all()
    assert len(items) > 0

    peanut_item = None
    for item in items:
        if "peanuts" in (item.allergens or []):
            peanut_item = item
            break

    if peanut_item:
        matched = await AllergenService.check_item_allergens(db, peanut_item.id, profile.allergens)
        assert "peanuts" in matched
        warning = AllergenService.format_allergen_warning(peanut_item.name, matched)
        assert "peanuts" in warning

    # Get safe items for the peanut allergy customer
    safe_ids = await AllergenService.get_safe_items(
        db, restaurant.id, profile.allergens, profile.dietary_restrictions
    )
    assert len(safe_ids) > 0
    if peanut_item:
        assert peanut_item.id not in safe_ids


@pytest.mark.asyncio
async def test_profile_service_recognize_and_history(db):
    # Check profile get
    profile = await ProfileService.get_by_phone(db, "+1-555-0102")  # Vegetarian profile in seeds
    assert profile is not None
    assert "vegetarian" in profile.dietary_restrictions

    # Test history summary on seeded orders
    summary = await ProfileService.get_order_history_summary(db, "+1-555-0102", 1)
    assert isinstance(summary, str)


@pytest.mark.asyncio
async def test_rule_service_pricing_rules(db):
    # Fetch first active restaurant
    res = await db.execute(select(Restaurant).where(Restaurant.is_active == True).limit(1))
    restaurant = res.scalar_one_or_none()
    assert restaurant is not None

    # Fetch active price rules
    rules = await RuleService.get_active_price_rules(db, restaurant.id, datetime.now())
    assert isinstance(rules, list)

    # Test rule application
    test_item = MenuItem(
        id=9999,
        name="Promo Burger",
        price=Decimal("10.00"),
        category_id=1,
        restaurant_id=restaurant.id
    )
    # Test percentage off rule
    pct_rule = PriceRule(
        restaurant_id=restaurant.id,
        name="Test 20% Off",
        label="20% OFF",
        rule_type="percentage_off",
        value=Decimal("20.00"),
        applies_to="all",
        is_active=True
    )

    final_price, applied = RuleService.apply_price_rules(test_item, [pct_rule])
    assert final_price == Decimal("8.00")
    assert "20% OFF" in applied

    # Test fixed off rule
    fixed_rule = PriceRule(
        restaurant_id=restaurant.id,
        name="Test $2 Off",
        label="SAVE $2",
        rule_type="fixed_off",
        value=Decimal("2.00"),
        applies_to="all",
        is_active=True
    )
    final_price, applied = RuleService.apply_price_rules(test_item, [fixed_rule])
    assert final_price == Decimal("8.00")
    assert "SAVE $2" in applied


@pytest.mark.asyncio
async def test_rule_service_order_rules(db):
    res = await db.execute(select(Restaurant).where(Restaurant.is_active == True).limit(1))
    restaurant = res.scalar_one_or_none()
    assert restaurant is not None

    # Retrieve an actual menu item from this restaurant to avoid foreign key violations
    res_item = await db.execute(
        select(MenuItem).where(MenuItem.restaurant_id == restaurant.id).limit(1)
    )
    menu_item = res_item.scalar_one_or_none()
    assert menu_item is not None

    # Create dummy order below min_total rule (seeded min_total is usually $15 or $20)
    order = Order(
        restaurant_id=restaurant.id,
        session_id="test-order-rules-session",
        status="pending",
        total=Decimal("5.00")
    )
    db.add(order)
    await db.flush()

    # Add item
    item = OrderItem(
        order_id=order.id,
        menu_item_id=menu_item.id,
        name_snapshot=menu_item.name,
        price_snapshot=Decimal("5.00"),
        quantity=1,
    )
    db.add(item)
    await db.flush()

    # Validate rules
    res_val = await RuleService.validate_order_rules(db, order.id, restaurant.id)
    assert "valid" in res_val
    if not res_val["valid"]:
        assert len(res_val["violations"]) > 0
        assert res_val["violations"][0]["rule"] in ("min_total", "min_for_delivery")

    # Cleanup test order
    await db.delete(item)
    await db.delete(order)


@pytest.mark.asyncio
async def test_menu_service_contextual_menu(db):
    res = await db.execute(select(Restaurant).where(Restaurant.is_active == True).limit(1))
    restaurant = res.scalar_one_or_none()
    assert restaurant is not None

    # Retrieve menu available now
    now = datetime.now()
    menu = await MenuService.get_contextual_menu(db, restaurant.id, now)
    assert isinstance(menu, dict)

    # Format for prompt test
    prompt_text = MenuService.format_for_prompt(menu)
    assert isinstance(prompt_text, str)


@pytest.mark.asyncio
async def test_v2_intelligence_telemetry(db):
    # Test that pre_dispatch, safety_audit, explore_semantic, and context manager emit telemetry events correctly
    from monitoring.events import bus, EK
    
    # 1. Clear bus events
    bus._buffer.clear()
    
    # Let's get restaurant and profile to use
    res = await db.execute(select(Restaurant).where(Restaurant.is_active == True).limit(1))
    restaurant = res.scalar_one_or_none()
    assert restaurant is not None
    
    profile = await ProfileService.get_by_phone(db, "+1-555-0101")
    assert profile is not None
    
    # 2. Test safety_audit telemetry event emission
    from services.intelligence_service import IntelligenceService as IS
    audit_res = await IS.safety_audit(
        db,
        allergens=profile.allergens,
        dietary=profile.dietary_restrictions,
        restaurant_id=restaurant.id,
        strict=profile.strict_allergens,
        session_id="test-session-safety"
    )
    
    safety_events = [e for e in bus.all_events() if e.kind == EK.SAFETY]
    assert len(safety_events) == 1
    assert safety_events[0].session_id == "test-session-safety"
    assert "verdict" in safety_events[0].detail
    
    # 3. Test explore_semantic telemetry event emission
    bus._buffer.clear()
    query_emb = [0.0] * 768
    semantic_res = await IS.explore_semantic(
        db,
        query_embedding=query_emb,
        restaurant_id=restaurant.id,
        allergens=profile.allergens,
        dietary=profile.dietary_restrictions,
        session_id="test-session-semantic",
        query_text="something healthy"
    )
    
    semantic_events = [e for e in bus.all_events() if e.kind == EK.SEMANTIC]
    assert len(semantic_events) == 1
    assert semantic_events[0].session_id == "test-session-semantic"
    assert semantic_events[0].detail["query"] == "something healthy"

    # 4. Test context manager telemetry event emission
    bus._buffer.clear()
    from core.context_manager import estimate_tokens, should_summarise, summarise_and_prune
    from langchain_core.messages import HumanMessage, AIMessage
    
    messages = [
        HumanMessage(content=f"message {i}") if i % 2 == 0 else AIMessage(content=f"reply {i}")
        for i in range(75) # exceeds turn limit of 30
    ]
    
    # Mock LLM and Cache
    class MockLLM:
        async def ainvoke(self, messages):
            class MockResponse:
                content = "Mocked conversation summary."
            return MockResponse()
            
    class MockCache:
        async def set_json(self, key, value, ttl=None):
            pass
            
    assert await should_summarise(messages) is True
    
    msg_update, pruned = await summarise_and_prune(
        messages=messages,
        session_id="test-session-context",
        llm_client=MockLLM(),
        redis_cache=MockCache()
    )
    
    context_events = [e for e in bus.all_events() if e.kind == EK.CONTEXT]
    assert len(context_events) == 1
    assert context_events[0].session_id == "test-session-context"
    assert context_events[0].detail["initial_turns"] == 75
    assert "Mocked conversation summary." in context_events[0].detail["summary_generated"]


@pytest.mark.asyncio
async def test_stage_transitions():
    from core.nodes import update_stage
    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
    
    # 1. Test greeting to ordering
    state = {
        "messages": [
            HumanMessage(content="hello"),
            AIMessage(content="hi"),
            HumanMessage(content="i want food")
        ],
        "cart": [],
        "stage": "greeting",
        "session_id": "test-session"
    }
    res = update_stage(state)
    assert res["stage"] == "ordering"

    # 2. Test ordering to confirming
    state = {
        "messages": [
            HumanMessage(content="place the order"),
            AIMessage(content="Perfect. Shall I confirm and place your order?")
        ],
        "cart": [{"item_id": 1, "name": "Pizza", "price": 10.0, "quantity": 1}],
        "stage": "ordering",
        "session_id": "test-session"
    }
    res = update_stage(state)
    assert res["stage"] == "confirming"

    # 3. Test confirming to payment
    state = {
        "messages": [
            HumanMessage(content="yes"),
            AIMessage(content="How would you like to pay, cash or card?")
        ],
        "cart": [{"item_id": 1, "name": "Pizza", "price": 10.0, "quantity": 1}],
        "stage": "confirming",
        "session_id": "test-session"
    }
    res = update_stage(state)
    assert res["stage"] == "payment"

    # 4. Test transition to done on confirm_order tool call
    state = {
        "messages": [
            HumanMessage(content="by card"),
            AIMessage(content="processing"),
            ToolMessage(content="ok", name="confirm_order", tool_call_id="call_confirm"),
            AIMessage(content="done")
        ],
        "cart": [{"item_id": 1, "name": "Pizza", "price": 10.0, "quantity": 1}],
        "stage": "payment",
        "session_id": "test-session"
    }
    res = update_stage(state)
    assert res["stage"] == "done"


@pytest.mark.asyncio
async def test_get_active_offers(db):
    from services.intelligence_service import IntelligenceService as IS
    
    # 1. Fetch first restaurant
    res = await db.execute(select(Restaurant).where(Restaurant.is_active == True).limit(1))
    restaurant = res.scalar_one_or_none()
    assert restaurant is not None
    
    # Retrieve an actual menu item from this restaurant to avoid foreign key violations
    res_item = await db.execute(
        select(MenuItem).where(MenuItem.restaurant_id == restaurant.id).limit(1)
    )
    menu_item = res_item.scalar_one_or_none()
    assert menu_item is not None

    # 2. Create a test order
    order = Order(
        restaurant_id=restaurant.id,
        session_id="test-offers-session",
        status="pending",
        total=Decimal("12.00")
    )
    db.add(order)
    await db.flush()

    # Add an order item that has a discount (original price > price snapshot)
    item = OrderItem(
        order_id=order.id,
        menu_item_id=menu_item.id,
        name_snapshot=menu_item.name,
        original_price=Decimal("15.00"),
        price_snapshot=Decimal("12.00"),
        quantity=1,
    )
    db.add(item)
    await db.flush()

    # 3. Call get_active_offers
    res_offers = await IS.get_active_offers(db, restaurant.id, order.id)
    assert res_offers is not None
    assert res_offers.get("status") == "ok"
    data = res_offers.get("data", {})
    assert "applied_discounts" in data
    assert "available_offers" in data
    assert "all_offers_schedule" in data
    assert "order_rules_status" in data
    assert "llm_guidance" in res_offers
    assert isinstance(res_offers["llm_guidance"], str)
    
    # Verify applied discounts has our item
    applied = data["applied_discounts"]
    assert len(applied) > 0
    assert applied[0]["item_name"] == menu_item.name
    assert float(applied[0]["savings"]) == 3.0
    
    # Cleanup
    await db.delete(item)
    await db.delete(order)



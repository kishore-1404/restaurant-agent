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

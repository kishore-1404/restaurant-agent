from fastapi import APIRouter, Depends, HTTPException
from api.dependencies import get_db_and_restaurant
from services.order_service import OrderService
from services.menu_service import MenuService
from pydantic import BaseModel
from decimal import Decimal
from typing import Optional, List

router = APIRouter()


class OrderCreate(BaseModel):
    session_id: str
    customer_name: Optional[str] = None


class OrderItemAdd(BaseModel):
    menu_item_id: int
    quantity: int = 1
    modifiers_chosen: Optional[dict] = None


class OrderItemOut(BaseModel):
    id: int
    menu_item_id: int
    name_snapshot: str
    price_snapshot: Decimal
    quantity: int
    modifiers_chosen: dict
    subtotal: Decimal

    class Config:
        from_attributes = True


class OrderOut(BaseModel):
    id: int
    restaurant_id: int
    session_id: str
    customer_name: Optional[str]
    status: str
    total: Decimal
    payment_method: Optional[str]
    notes: Optional[str]
    items: List[OrderItemOut]

    class Config:
        from_attributes = True


@router.post("", response_model=OrderOut)
async def create_order(
    req: OrderCreate,
    context=Depends(get_db_and_restaurant)
):
    db, restaurant = context
    order = await OrderService.create_order(db, restaurant.id, req.session_id, req.customer_name)
    await db.commit()
    # Reload with empty items list
    return await OrderService.get_order_with_items(db, order.id)


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(
    order_id: int,
    context=Depends(get_db_and_restaurant)
):
    db, restaurant = context
    order = await OrderService.get_order_with_items(db, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.post("/{order_id}/items", response_model=OrderOut)
async def add_item_to_order(
    order_id: int,
    req: OrderItemAdd,
    context=Depends(get_db_and_restaurant)
):
    db, restaurant = context
    # Get menu item (scoping automatically checked by get_item_by_id under restaurant_id)
    menu_item = await MenuService.get_item_by_id(db, req.menu_item_id, restaurant.id)
    if not menu_item:
        raise HTTPException(status_code=404, detail="Menu item not found or unavailable")

    await OrderService.add_item(db, order_id, menu_item, req.quantity, req.modifiers_chosen)
    await db.commit()
    return await OrderService.get_order_with_items(db, order_id)


@router.delete("/{order_id}/items/{menu_item_id}", response_model=OrderOut)
async def remove_item_from_order(
    order_id: int,
    menu_item_id: int,
    context=Depends(get_db_and_restaurant)
):
    db, restaurant = context
    await OrderService.remove_item(db, order_id, menu_item_id)
    await db.commit()
    return await OrderService.get_order_with_items(db, order_id)


@router.post("/{order_id}/confirm", response_model=OrderOut)
async def confirm_order(
    order_id: int,
    context=Depends(get_db_and_restaurant)
):
    db, restaurant = context
    try:
        order = await OrderService.confirm_order(db, order_id)
        await db.commit()
        return await OrderService.get_order_with_items(db, order.id)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))


class OrderConfirmRequest(BaseModel):
    session_id: str


@router.post("/confirm", response_model=OrderOut)
async def confirm_order_by_session(
    req: OrderConfirmRequest,
    context=Depends(get_db_and_restaurant)
):
    db, restaurant = context
    from sqlalchemy import select
    from db.models import Order
    res = await db.execute(select(Order).where(Order.session_id == req.session_id))
    order = res.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    try:
        order = await OrderService.confirm_order(db, order.id)
        await db.commit()
        return await OrderService.get_order_with_items(db, order.id)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))

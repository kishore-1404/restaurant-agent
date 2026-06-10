from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from db.base import get_db_session
from services.restaurant_service import RestaurantService
from pydantic import BaseModel
from datetime import datetime


router = APIRouter()


class RestaurantOut(BaseModel):
    id: int
    name: str
    cuisine_type: str
    personality: str
    special_instructions: str | None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("", response_model=list[RestaurantOut])
async def list_restaurants(db: AsyncSession = Depends(get_db_session)):
    return await RestaurantService.list_active(db)


@router.get("/{restaurant_id}", response_model=RestaurantOut)
async def get_restaurant(restaurant_id: int, db: AsyncSession = Depends(get_db_session)):
    restaurant = await RestaurantService.get_by_id(db, restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")
    return restaurant

from fastapi import APIRouter, Depends, Query
from api.dependencies import get_db_and_restaurant
from services.menu_service import MenuService

router = APIRouter()


@router.get("")
async def get_menu(
    context=Depends(get_db_and_restaurant),
    use_cache: bool = True
):
    db, restaurant = context
    return await MenuService.get_menu(db, restaurant.id, use_cache=use_cache)


@router.get("/search")
async def search_menu(
    q: str = Query(..., min_length=1),
    limit: int = Query(5, ge=1, le=20),
    context=Depends(get_db_and_restaurant)
):
    db, restaurant = context
    return await MenuService.search_items(db, restaurant.id, q, limit=limit)

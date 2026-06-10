from fastapi import Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from db.base import get_db_session
from services.restaurant_service import RestaurantService
from config import settings


async def get_db_and_restaurant(
    request: Request,
    db: AsyncSession = Depends(get_db_session)
):
    # Retrieve restaurant_id from request.state set by TenantMiddleware
    restaurant_id = getattr(request.state, "restaurant_id", None)

    # Fallback to DEFAULT_RESTAURANT_ID from settings if not provided in header
    if not restaurant_id:
        restaurant_id = settings.default_restaurant_id

    # Retrieve restaurant metadata
    restaurant = await RestaurantService.get_by_id(db, restaurant_id)
    if not restaurant:
        # Fallback to the first active restaurant if the default ID is not found in the DB
        active_restaurants = await RestaurantService.list_active(db)
        if active_restaurants:
            restaurant = active_restaurants[0]
            restaurant_id = restaurant.id
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Restaurant with ID {restaurant_id} not found or inactive, and no other active restaurants are available."
            )

    # Set the PostgreSQL session variable for Row-Level Security
    await RestaurantService.set_tenant_context(db, restaurant.id)

    return db, restaurant

from api.routers.restaurants import router as restaurants
from api.routers.menu import router as menu
from api.routers.orders import router as orders
from api.routers.chat import router as chat
from api.routers.frontend import router as frontend

__all__ = ["restaurants", "menu", "orders", "chat", "frontend"]


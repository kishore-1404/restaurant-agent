from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class TenantMiddleware(BaseHTTPMiddleware):
    """
    Reads X-Restaurant-ID header and stores restaurant context on the request.
    The DB dependency then calls SET LOCAL app.restaurant_id = X
    so that Row-Level Security policies automatically scope all queries.
    """
    async def dispatch(self, request: Request, call_next):
        restaurant_id = request.headers.get("X-Restaurant-ID")
        request.state.restaurant_id = int(restaurant_id) if restaurant_id else None
        response = await call_next(request)
        return response

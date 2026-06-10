import os
from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(include_in_schema=False)

_HTML = os.path.join(os.path.dirname(__file__), "../../static/index.html")


@router.get("/")
@router.get("/chat/{restaurant_id}")
async def spa(_restaurant_id: int = 0) -> FileResponse:
    """
    Return index.html for every frontend route.
    The SPA handles its own client-side routing.
    """
    return FileResponse(_HTML, media_type="text/html")

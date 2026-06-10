from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routers import restaurants, menu, orders, chat, frontend
from api.middleware import TenantMiddleware
from db.base import engine, Base
import logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables if they don't exist (migrations should cover this, but safe fallback)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ready")
    yield
    # Shutdown
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Restaurant AI Ordering System",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(TenantMiddleware)

    app.include_router(restaurants, prefix="/api/v1/restaurants", tags=["restaurants"])
    app.include_router(menu,        prefix="/api/v1/menu",        tags=["menu"])
    app.include_router(orders,      prefix="/api/v1/orders",      tags=["orders"])
    app.include_router(chat,        prefix="/api/v1/chat",        tags=["chat"])

    import os
    if os.environ.get("SERVE_WEB_UI") == "true":
        from fastapi.staticfiles import StaticFiles
        static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
        app.mount("/static", StaticFiles(directory=static_dir), name="static")
        app.include_router(frontend)

    # In both cases, mount the developer dashboard under "/monitor" using NiceGUI mount_dashboard
    from monitoring.dashboard import mount_dashboard
    mount_dashboard(app)

    return app


app = create_app()

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.admin import router as admin_router
from app.api.routes.files import router as files_router
from app.api.routes.folders import router as folders_router
from app.api.routes.health import router as health_router
from app.api.routes.retrieve import router as retrieve_router
from app.api.routes.upload import router as upload_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.scheduler.index_job import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(_: FastAPI):
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(folders_router)
    app.include_router(upload_router)
    app.include_router(files_router)
    app.include_router(retrieve_router)
    app.include_router(admin_router)
    return app


app = create_app()

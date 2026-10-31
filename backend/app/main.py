"""TechNova FastAPI application entry point.

This file builds the FastAPI app, applies middleware and mounts feature routers.
Business logic and endpoint handlers live in app.core and app.routes.*.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from .config import settings
from .core import lifespan, limiter
from .routes.system import router as system_router
from .routes.auth import router as auth_router
from .routes.members import router as members_router
from .routes.tasks import router as tasks_router
from .routes.teams import router as teams_router
from .routes.cards import router as cards_router
from .routes.hub import router as hub_router

# Keep the API title/version stable for deployment health checks and clients.
app = FastAPI(title="TechNova Club Portal API", version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Allow local development and the deployed Render frontend; custom domains come from FRONTEND_ORIGINS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys([
        "http://localhost:5173",
        "http://localhost:8080",
        "https://technova-1-qx44.onrender.com",
        *settings.origins(),
    ])),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount feature routers without changing their public /api endpoint paths.
app.include_router(system_router)
app.include_router(auth_router)
app.include_router(members_router)
app.include_router(tasks_router)
app.include_router(teams_router)
app.include_router(cards_router)
app.include_router(hub_router)

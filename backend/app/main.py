"""TechNova FastAPI application entry point.

The inner FastAPI app owns routes, lifespan and exception handling.
The outer CORS wrapper also decorates unhandled 500 responses, not only normal
route responses and preflight requests.
"""
import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
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
from .routes.push import router as push_router

logger = logging.getLogger("technova.api")

# The inner FastAPI application owns the API routes and startup/shutdown lifecycle.
api_app = FastAPI(
    title="TechNova Club Portal API",
    version="1.1.0",
    lifespan=lifespan,
)
api_app.state.limiter = limiter
api_app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@api_app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception):
    """Log unexpected exceptions and return a safe, consistent JSON error."""
    request_id = uuid4().hex[:12]
    logger.exception(
        "Unhandled API error %s for %s %s",
        request_id,
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An unexpected server error occurred. Please try again.",
            "request_id": request_id,
        },
        headers={"X-Request-ID": request_id},
    )


# Mount feature routers without changing their existing /api endpoint paths.
api_app.include_router(system_router)
api_app.include_router(auth_router)
api_app.include_router(members_router)
api_app.include_router(tasks_router)
api_app.include_router(teams_router)
api_app.include_router(cards_router)
api_app.include_router(hub_router)
api_app.include_router(push_router)

# Keep local development and the deployed Render frontend explicitly allowed.
# Add custom frontend domains through FRONTEND_ORIGINS; never use a wildcard with credentials.
ALLOWED_ORIGINS = list(dict.fromkeys([
    "http://localhost:5173",
    "http://localhost:8080",
    "https://technova-1-qx44.onrender.com",
    *settings.origins(),
]))

# IMPORTANT: CORS is the outermost ASGI layer. Starlette's built-in ServerErrorMiddleware
# can otherwise generate an unhandled 500 outside a normally-added CORS middleware.
app = CORSMiddleware(
    app=api_app,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
    max_age=600,
)

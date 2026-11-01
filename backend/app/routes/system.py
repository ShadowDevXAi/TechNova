"""System and administration endpoints.

Health checks, database statistics and owner-managed daily-task generation settings.

All protected operations reuse authentication and role checks from app.core.
"""

import logging

from fastapi import APIRouter, HTTPException
from ..core import *  # Shared database, schemas, authorization and business helpers.

router = APIRouter()
logger = logging.getLogger("technova.health")

# Purpose: root handles the system feature flow and returns its API result.
@router.get("/")
async def root():
    return {"status": "ok", "service": "technova-api", "health": "/api/health"}


# Purpose: health handles the system feature flow and returns its API result.
@router.get("/api/health")
async def health():
    """Report application and database readiness without exposing credentials."""
    try:
        await client.admin.command("ping")
    except Exception:
        logger.exception("MongoDB readiness check failed")
        raise HTTPException(
            status_code=503,
            detail="TechNova API is running, but its database is unavailable.",
        )
    return {"status": "ok", "service": "technova-api", "database": "connected"}


# Purpose: database stats handles the system feature flow and returns its API result.
@router.get("/api/admin/database-stats")
async def database_stats(actor: dict = Depends(allow("Founder", "Core Management"))):
    """Live MongoDB database/collection counts and storage statistics."""
    stats = await db.command("dbStats")
    collection_names = await db.list_collection_names()
    collection_names = sorted(collection_names)
    counts = await asyncio.gather(*(db[name].count_documents({}) for name in collection_names))
    collections = [{"name": name, "documents": count} for name, count in zip(collection_names, counts)]
    total_documents = sum(counts)

    storage_bytes = int(stats.get("storageSize", 0)) + int(stats.get("indexSize", 0))
    data_bytes = int(stats.get("dataSize", 0))
    index_bytes = int(stats.get("indexSize", 0))
    try:
        limit_gb = float(os.getenv("MONGODB_STORAGE_LIMIT_GB", "0") or 0)
    except ValueError:
        limit_gb = 0
    limit_bytes = int(limit_gb * 1024 ** 3) if limit_gb > 0 else None
    return {
        "database": db.name,
        "collections_count": len(collection_names),
        "documents_count": total_documents,
        "storage_bytes": storage_bytes,
        "data_bytes": data_bytes,
        "index_bytes": index_bytes,
        "storage_limit_bytes": limit_bytes,
        "remaining_bytes": max(0, limit_bytes - storage_bytes) if limit_bytes else None,
        "storage_limit_configured": bool(limit_bytes),
        "collections": collections,
        "measured_at": utcnow().isoformat(),
    }


# Purpose: run maintenance now handles the system feature flow and returns its API result.
@router.post("/api/maintenance/run")
async def run_maintenance_now(actor: dict = Depends(allow("Founder"))):
    return {"message": "Maintenance cycle completed", **(await run_daily_maintenance())}

# Purpose: get auto task settings handles the system feature flow and returns its API result.
@router.get("/api/auto-tasks/settings")
async def get_auto_task_settings(actor: dict = Depends(allow("Founder", "Core Management"))):
    return await auto_task_generation_status()


# Purpose: update auto task settings handles the system feature flow and returns its API result.
@router.put("/api/auto-tasks/settings")
async def update_auto_task_settings(body: dict, request: Request, actor: dict = Depends(allow("Founder"))):
    mode = body.get("mode", "custom")
    if mode not in {"custom", "unlimited"}:
        raise HTTPException(422, "Mode must be custom or unlimited")
    try:
        daily_target = int(body.get("daily_target", 5))
    except (TypeError, ValueError):
        raise HTTPException(422, "Daily target must be a whole number")
    if daily_target < 1 or daily_target > 50:
        raise HTTPException(422, "Custom daily target must be between 1 and 50")
    await db.app_settings.update_one(
        {"_id": "auto_daily_task_config"},
        {"$set": {"mode": mode, "daily_target": daily_target, "updated_at": utcnow(), "updated_by": actor["_id"]}},
        upsert=True,
    )
    await audit(actor, "auto_daily_task_settings_updated", "auto_daily_task_config", {
        "mode": mode, "daily_target": daily_target, "unlimited_daily_cap": 20,
    }, request)
    return await auto_task_generation_status()


# Purpose: generate auto tasks now handles the system feature flow and returns its API result.
@router.post("/api/auto-tasks/generate")
async def generate_auto_tasks_now(request: Request, actor: dict = Depends(allow("Founder"))):
    result = await generate_automatic_daily_tasks()
    await audit(actor, "auto_daily_tasks_generate_requested", result.get("date", ""), {
        "generated": result.get("generated", 0), "mode": result.get("mode"),
    }, request)
    return {"message": "Daily mission generation run completed", **result}


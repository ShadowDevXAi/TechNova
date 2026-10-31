"""Authenticated browser push-device registration endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from ..core import db, get_current_user
from ..firebase_push import firebase_push_configured
from ..security import utcnow

router = APIRouter()

@router.get("/api/push/status")
async def push_status(user: dict = Depends(get_current_user)):
    """Return Firebase configuration state and this account's registered-device count."""
    count = await db.push_tokens.count_documents({"user_id": user["_id"]})
    return {"configured": firebase_push_configured(), "registered_devices": count, "provider": "Firebase Cloud Messaging"}

@router.post("/api/push/register", status_code=201)
async def register_push_device(body: dict, user: dict = Depends(get_current_user)):
    """Bind the browser's FCM token to the signed-in account."""
    if not firebase_push_configured():
        raise HTTPException(503, "Firebase push is not configured on the backend. Add the Firebase Admin JSON as a Render Secret File first.")
    token = body.get("token")
    if not isinstance(token, str):
        raise HTTPException(422, "A valid Firebase device token is required")
    token = token.strip()
    if len(token) < 40 or len(token) > 8192 or any(character.isspace() for character in token):
        raise HTTPException(422, "The Firebase device token is invalid")
    label = body.get("device_label", "Web browser")
    if not isinstance(label, str):
        label = "Web browser"
    now = utcnow()
    await db.push_tokens.update_one(
        {"token": token},
        {"$set": {"token": token, "user_id": user["_id"], "device_label": label[:80], "updated_at": now},
         "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    count = await db.push_tokens.count_documents({"user_id": user["_id"]})
    return {"message": "Push notifications enabled for this device.", "registered_devices": count}

@router.post("/api/push/unregister")
async def unregister_push_device(body: dict, user: dict = Depends(get_current_user)):
    """Remove only the supplied device token owned by the current account."""
    token = body.get("token")
    if not isinstance(token, str) or not token.strip():
        raise HTTPException(422, "A device token is required to disable push notifications")
    result = await db.push_tokens.delete_one({"user_id": user["_id"], "token": token.strip()})
    return {"message": "Push notifications disabled for this device.", "removed": bool(result.deleted_count)}

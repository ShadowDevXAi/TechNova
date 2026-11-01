"""Firebase Cloud Messaging delivery for registered TechNova browser devices."""
import asyncio
import logging
from pathlib import Path
import firebase_admin
from firebase_admin import credentials, messaging
from .config import settings
from .db import db

logger = logging.getLogger("technova.push")

def _get_firebase_app():
    """Initialize Firebase Admin once from a mounted Render Secret File."""
    secret_path = (settings.firebase_service_account_file or "").strip()
    if not secret_path or not Path(secret_path).is_file():
        raise RuntimeError("Firebase Admin service-account secret file is not configured")
    try:
        return firebase_admin.get_app()
    except ValueError:
        credential = credentials.Certificate(secret_path)
        return firebase_admin.initialize_app(credential, options={"projectId": settings.firebase_project_id})

def firebase_push_configured() -> bool:
    """Check the mounted service-account file without exposing its contents."""
    try:
        _get_firebase_app()
        return True
    except Exception:
        logger.info("Firebase push is not configured or its service-account file is invalid.")
        return False

def _send_to_tokens(tokens: list[str], title: str, body: str, data: dict[str, str]) -> list[str]:
    """Send FCM messages in batches and return tokens Firebase confirms are expired."""
    app = _get_firebase_app()
    expired_tokens: list[str] = []
    target_url = (settings.public_app_url or "https://technova-1-qx44.onrender.com").rstrip("/") + "/"
    for start in range(0, len(tokens), 500):
        batch_tokens = tokens[start:start + 500]
        messages = [
            messaging.Message(
                token=token,
                notification=messaging.Notification(title=title[:120], body=body[:1000]),
                data={**data, "url": target_url},
                webpush=messaging.WebpushConfig(fcm_options=messaging.WebpushFCMOptions(link=target_url)),
            )
            for token in batch_tokens
        ]
        response = messaging.send_each(messages, app=app)
        for token, result in zip(batch_tokens, response.responses):
            if result.success:
                continue
            error_text = str(result.exception or "").lower()
            if "registration-token-not-registered" in error_text or "requested entity was not found" in error_text or "unregistered" in error_text:
                expired_tokens.append(token)
            else:
                logger.warning("Firebase push delivery failed for a device: %s", result.exception)
    return expired_tokens

async def send_push_notification(user_id, title: str, body: str, notification_type: str = "general", task_id: str | None = None, common_task_id: str | None = None) -> None:
    """Send to all registered devices without blocking portal request handling."""
    if not settings.firebase_service_account_file:
        return
    try:
        devices = await db.push_tokens.find(
            {"user_id": user_id}, {"_id": 0, "token": 1}
        ).to_list(500)
        tokens = [item.get("token") for item in devices if item.get("token")]
        if not tokens:
            return
        data = {"type": str(notification_type or "general"), "title": title[:120], "body": body[:1000]}
        if task_id:
            data["taskId"] = str(task_id)
        if common_task_id:
            data["commonTaskId"] = str(common_task_id)
        expired = await asyncio.to_thread(_send_to_tokens, tokens, title, body, data)
        if expired:
            await db.push_tokens.delete_many({"token": {"$in": expired}})
    except Exception:
        # Optional delivery (including token lookup/cleanup) must never break the main action.
        logger.exception("Firebase push delivery failed; the in-app notification was retained.")

"""Owner-only Telegram notifications and on-demand sanitized database backups.

Telegram is an external third-party service: never send authentication secrets,
password hashes, reset tokens, OTPs, push tokens or service credentials.
"""
from __future__ import annotations

import asyncio
import gzip
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from bson import ObjectId
from .config import settings
from .db import db
from .storage import read_attachment

logger = logging.getLogger("technova.telegram")
POLL_SECONDS = 2
MAX_BACKUP_CHUNK = 7 * 1024 * 1024
REDACT_KEYS = re.compile(
    r"(password|passwd|secret|token|otp|credential|authorization|private.?key|"
    r"service.?account|reset.?code|verification.?code|recovery.?code|"
    r"firebase.?key|api.?key|jwt)", re.I
)
EXCLUDED_COLLECTIONS = {
    "password_resets", "email_verifications", "auth_challenges",
    "trusted_devices", "push_tokens",
}


def telegram_status() -> dict:
    configured = bool(
        settings.telegram_bot_token.strip()
        and settings.telegram_owner_id.strip()
        and settings.telegram_backup_chat_id.strip()
    )
    return {
        "enabled": bool(settings.telegram_enabled and configured),
        "configured": configured,
        "owner_allowlist_configured": bool(settings.telegram_owner_id.strip()),
        "channel_configured": bool(settings.telegram_backup_chat_id.strip()),
    }


def _api(method: str, payload: dict | None = None, multipart: tuple[str, bytes, str] | None = None):
    token = settings.telegram_bot_token.strip()
    if not token:
        raise RuntimeError("Telegram bot is not configured")
    url = f"https://api.telegram.org/bot{token}/{method}"
    if multipart:
        field, content, filename = multipart
        boundary = "----TechNovaTelegramBoundary"
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n"
            f"{settings.telegram_backup_chat_id.strip()}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
        request = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
    else:
        request = urllib.request.Request(
            url, data=json.dumps(payload or {}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
    try:
        with urllib.request.urlopen(request, timeout=35) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not result.get("ok"):
            raise RuntimeError("Telegram API rejected the request")
        return result.get("result")
    except urllib.error.HTTPError as exc:
        # Do not log response bodies; they may contain chat or provider details.
        raise RuntimeError(f"Telegram API HTTP {exc.code}") from exc


async def _send_message(text: str, chat_id: str | None = None):
    payload = {
        "chat_id": chat_id or settings.telegram_backup_chat_id.strip(),
        "text": text[:4000],
        "disable_web_page_preview": True,
    }
    await asyncio.to_thread(_api, "sendMessage", payload)


async def _send_document(content: bytes, filename: str, caption: str = ""):
    if len(content) > 49 * 1024 * 1024:
        raise ValueError("Telegram document exceeds the supported upload limit")
    # sendDocument accepts caption as an optional multipart field; keep it short.
    token = settings.telegram_bot_token.strip()
    boundary = "----TechNovaTelegramBoundary"
    fields = [("chat_id", settings.telegram_backup_chat_id.strip()), ("caption", caption[:900])]
    chunks = []
    for key, value in fields:
        chunks.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode()
        )
    chunks.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{filename}\"\r\n"
        "Content-Type: application/gzip\r\n\r\n".encode()
    )
    chunks.extend([content, f"\r\n--{boundary}--\r\n".encode()])
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendDocument",
        data=b"".join(chunks),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    def send():
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not result.get("ok"):
            raise RuntimeError("Telegram document delivery failed")
        return result.get("result")
    await asyncio.to_thread(send)


def _safe_value(value):
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat() if value.tzinfo else value.isoformat() + "Z"
    if isinstance(value, bytes):
        return "[binary data omitted]"
    if isinstance(value, dict):
        return {
            str(key): _safe_value(item)
            for key, item in value.items()
            if not REDACT_KEYS.search(str(key))
        }
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    return value


async def create_database_backup():
    """Export app collections in bounded gzip chunks, omitting authentication secrets."""
    names = sorted(name for name in await db.list_collection_names() if name not in EXCLUDED_COLLECTIONS and not name.startswith("system."))
    exported = 0
    chunk = []
    chunk_number = 1
    async def flush(rows):
        nonlocal chunk_number, exported
        if not rows:
            return
        raw = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()
        compressed = gzip.compress(raw, compresslevel=5)
        await _send_document(
            compressed, f"technova-backup-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{chunk_number:03d}.json.gz",
            f"TechNova database backup chunk {chunk_number}. Authentication secrets excluded.",
        )
        exported += len(rows)
        chunk_number += 1

    for name in names:
        cursor = db[name].find({})
        async for doc in cursor:
            chunk.append({"collection": name, "document": _safe_value(doc)})
            if len(chunk) >= 100:
                await flush(chunk)
                chunk = []
    await flush(chunk)
    # Uploaded binary attachments are backed up separately, without loading all files into RAM.
    attachments = db.attachments.find({})
    file_count = 0
    async for item in attachments:
        try:
            data = await asyncio.to_thread(read_attachment, item)
            compressed = gzip.compress(data, compresslevel=1)
            if len(compressed) <= 49 * 1024 * 1024:
                name = re.sub(r"[^a-zA-Z0-9._-]", "_", item.get("filename", "attachment"))[:100]
                await _send_document(
                    compressed, f"attachment-{str(item['_id'])}-{name}.gz",
                    f"Original attachment: {name}; gzip-compressed. Record ID: {item['_id']}",
                )
                file_count += 1
            else:
                await _send_message(f"Backup skipped oversized attachment record {item['_id']}.")
        except Exception:
            logger.exception("Telegram backup could not export attachment id=%s", str(item.get("_id")))
    await _send_message(
        f"TechNova backup completed. Exported {exported} database records and {file_count} attachment files. "
        "Authentication and service secrets were excluded."
    )


async def _process_attachment(job: dict):
    from bson import ObjectId
    item = await db.attachments.find_one({"_id": ObjectId(job["attachment_id"])})
    if not item:
        return
    data = await asyncio.to_thread(read_attachment, item)
    if len(data) > 49 * 1024 * 1024:
        raise ValueError("Attachment exceeds Telegram's bot upload limit")
    filename = re.sub(r"[^a-zA-Z0-9._-]", "_", item.get("filename", "attachment"))[:100]
    caption = (
        f"TechNova upload: {filename}\n"
        f"Size: {len(data)} bytes\n"
        f"Attachment record: {job['attachment_id']}\n"
        "Delivered to the private owner backup channel."
    )
    await asyncio.to_thread(
        _api, "sendDocument", None,
        ("document", data, filename),
    )
    await db.telegram_jobs.update_one({"_id": job["_id"]}, {"$set": {"status": "sent", "sent_at": datetime.now(timezone.utc)}})
    await _send_message(caption)


async def enqueue_attachment(attachment_id: str):
    """Persist a tiny queue item; never wait for Telegram in the upload request."""
    if not telegram_status()["enabled"]:
        return
    await db.telegram_jobs.update_one(
        {"_id": f"attachment:{attachment_id}"},
        {"$setOnInsert": {
            "kind": "attachment", "attachment_id": attachment_id,
            "status": "pending", "attempts": 0, "created_at": datetime.now(timezone.utc),
        }},
        upsert=True,
    )


async def delivery_worker():
    while True:
        try:
            job = await db.telegram_jobs.find_one_and_update(
                {"status": "pending", "attempts": {"$lt": 5}},
                {"$set": {"status": "processing", "locked_at": datetime.now(timezone.utc)},
                 "$inc": {"attempts": 1}},
                sort=[("created_at", 1)],
            )
            if job:
                try:
                    if job.get("kind") == "attachment":
                        await _process_attachment(job)
                    else:
                        await db.telegram_jobs.update_one({"_id": job["_id"]}, {"$set": {"status": "failed"}})
                except Exception:
                    logger.exception("Telegram delivery job failed id=%s", str(job.get("_id")))
                    await db.telegram_jobs.update_one(
                        {"_id": job["_id"]},
                        {"$set": {"status": "pending", "last_error": "Delivery failed"}}
                    )
            else:
                await asyncio.sleep(3)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telegram delivery worker iteration failed")
            await asyncio.sleep(5)


async def _handle_owner_command(update: dict):
    message = update.get("message") or update.get("channel_post") or {}
    sender = message.get("from") or {}
    chat = message.get("chat") or {}
    owner_id = settings.telegram_owner_id.strip()
    if not owner_id or str(sender.get("id", "")) != owner_id:
        return
    # Accept commands only in the owner's private chat, never groups or channels.
    if chat.get("type") != "private" or str(chat.get("id", "")) != owner_id:
        return
    command = (message.get("text") or "").split()[0].split("@")[0].lower()
    if command == "/start" or command == "/help":
        await _send_message(
            "TechNova owner bot\n/status — integration status\n/backup — export permitted database records and uploaded files\n/help — show commands",
            chat_id=owner_id,
        )
    elif command == "/status":
        jobs = await db.telegram_jobs.count_documents({"status": "pending"})
        await _send_message(
            f"Telegram integration: {'enabled' if telegram_status()['enabled'] else 'not configured'}\nPending delivery jobs: {jobs}",
            chat_id=owner_id,
        )
    elif command == "/backup":
        await _send_message("Owner backup started. Files will be delivered to the configured private channel.", chat_id=owner_id)
        try:
            await create_database_backup()
        except Exception:
            logger.exception("Owner-requested Telegram backup failed")
            await _send_message("Backup failed. Check backend logs for the request ID and configuration.", chat_id=owner_id)


async def polling_worker():
    """Long-poll commands from Telegram; only the configured owner can invoke actions."""
    if not telegram_status()["enabled"]:
        logger.info("Telegram bot disabled or missing configuration; worker not started")
        return
    offset = 0
    while True:
        try:
            updates = await asyncio.to_thread(
                _api, "getUpdates",
                {"offset": offset, "timeout": 20, "allowed_updates": ["message"]},
            )
            for update in updates or []:
                offset = max(offset, int(update["update_id"]) + 1)
                try:
                    await _handle_owner_command(update)
                except Exception:
                    logger.exception("Telegram owner command failed")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telegram polling failed; retrying")
            await asyncio.sleep(5)


async def start_telegram_workers():
    if not telegram_status()["enabled"]:
        logger.info("Telegram integration disabled; configure backend secrets to enable it")
        return []
    await db.telegram_jobs.create_index([("status", 1), ("created_at", 1)])
    return [
        asyncio.create_task(delivery_worker(), name="telegram-delivery-worker"),
        asyncio.create_task(polling_worker(), name="telegram-owner-polling-worker"),
    ]

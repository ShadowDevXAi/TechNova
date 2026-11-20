"""Member-owned encrypted profile image storage backed by a private Telegram channel.

Only ciphertext is sent to this API or Telegram. The member's passphrase stays
in the browser and is never stored or transmitted to the backend.
"""
import asyncio
import base64
import re
import urllib.request

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from ..config import settings
from ..core import audit, db, get_current_user, limiter, utcnow
from ..telegram_backup import _api, telegram_status

router = APIRouter()
MAX_ENCRYPTED_IMAGE_BYTES = 6 * 1024 * 1024
ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp"}
HEX_SALT = re.compile(r"^[0-9a-f]{32}$")
HEX_IV = re.compile(r"^[0-9a-f]{24}$")


def _require_member(user: dict) -> None:
    """Restrict this feature to ordinary Member accounts, never management."""
    if user.get("role") != "Member":
        raise HTTPException(403, "Encrypted profile images are available to Member accounts only.")


def _telegram_download(file_path: str) -> bytes:
    """Download Telegram's stored ciphertext using the server-only bot token."""
    safe_path = str(file_path or "")
    if not safe_path or safe_path.startswith("/") or ".." in safe_path.split("/"):
        raise RuntimeError("Telegram returned an invalid file path")
    url = f"https://api.telegram.org/file/bot{settings.telegram_bot_token.strip()}/{safe_path}"
    with urllib.request.urlopen(url, timeout=45) as response:
        content = response.read(MAX_ENCRYPTED_IMAGE_BYTES + 1)
    if len(content) > MAX_ENCRYPTED_IMAGE_BYTES:
        raise RuntimeError("Stored encrypted profile image exceeds the supported size")
    return content


@router.post("/api/profile-image")
@limiter.limit("5/hour")
async def upload_profile_image(
    request: Request,
    encrypted_file: UploadFile = File(...),
    salt: str = Form(...),
    iv: str = Form(...),
    media_type: str = Form(...),
    user: dict = Depends(get_current_user),
):
    """Send browser-encrypted bytes to Telegram and store only file metadata in MongoDB."""
    _require_member(user)
    if not telegram_status()["enabled"]:
        raise HTTPException(503, "Private Telegram image storage is not configured. Ask the TechNova Founder to configure it.")
    if not HEX_SALT.fullmatch(salt) or not HEX_IV.fullmatch(iv):
        raise HTTPException(422, "Invalid encryption parameters.")
    if media_type not in ALLOWED_MEDIA_TYPES:
        raise HTTPException(415, "Only JPEG, PNG and WEBP profile images are supported.")

    ciphertext = await encrypted_file.read(MAX_ENCRYPTED_IMAGE_BYTES + 1)
    if not ciphertext or len(ciphertext) > MAX_ENCRYPTED_IMAGE_BYTES:
        raise HTTPException(413, "Encrypted profile image must be smaller than 6 MB.")
    # AES-GCM ciphertext must include its 128-bit authentication tag.
    if len(ciphertext) < 17:
        raise HTTPException(422, "Encrypted image payload is incomplete.")

    try:
        telegram_message = await asyncio.to_thread(
            _api,
            "sendDocument",
            None,
            ("document", ciphertext, "technova-profile-image.enc"),
        )
        document = telegram_message.get("document") or {}
        file_id = document.get("file_id")
        file_unique_id = document.get("file_unique_id")
        if not file_id or not file_unique_id:
            raise RuntimeError("Telegram did not return a document reference")
    except Exception as exc:
        raise HTTPException(502, "Telegram could not store the encrypted profile image. Please retry later.") from exc

    now = utcnow()
    await db.profile_images.update_one(
        {"owner_id": user["_id"]},
        {"$set": {
            "owner_id": user["_id"],
            "telegram_file_id": file_id,
            "telegram_file_unique_id": file_unique_id,
            "telegram_message_id": telegram_message.get("message_id"),
            "salt": salt,
            "iv": iv,
            "media_type": media_type,
            "ciphertext_size": len(ciphertext),
            "updated_at": now,
        }, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    await audit(user, "profile_image_encrypted_upload", str(user["_id"]), {
        "storage": "telegram_private_channel",
        "encrypted_bytes": len(ciphertext),
        "media_type": media_type,
    }, request)
    return {
        "message": "Encrypted profile image saved to the private Telegram channel.",
        "media_type": media_type,
        "updated_at": now,
    }


@router.get("/api/profile-image")
@limiter.limit("30/minute")
async def get_profile_image(request: Request, user: dict = Depends(get_current_user)):
    """Return only the signed-in Member's encrypted image; never expose another owner's image."""
    _require_member(user)
    record = await db.profile_images.find_one({"owner_id": user["_id"]})
    if not record:
        raise HTTPException(404, "No encrypted profile image has been uploaded.")
    try:
        telegram_file = await asyncio.to_thread(
            _api, "getFile", {"file_id": record["telegram_file_id"]}
        )
        ciphertext = await asyncio.to_thread(_telegram_download, telegram_file.get("file_path", ""))
    except Exception as exc:
        raise HTTPException(502, "Could not retrieve the encrypted profile image from Telegram.") from exc

    return {
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        "salt": record["salt"],
        "iv": record["iv"],
        "media_type": record["media_type"],
        "ciphertext_size": len(ciphertext),
        "updated_at": record.get("updated_at"),
    }

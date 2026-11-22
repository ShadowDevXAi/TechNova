"""Consent-gated ID-card photos stored in private S3-compatible object storage.

Uploads are decoded and re-encoded as JPEG, then scanned by ClamAV before storage.
Photos are never served from a public object URL.
"""
import asyncio
import io
import secrets
import warnings

from bson import ObjectId
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.responses import Response

from ..core import audit, allow, db, get_current_user, limiter, utcnow
from ..id_card_photo_storage import delete_id_card_photo, read_id_card_photo, store_id_card_photo
from ..image_scan import MalwareDetected, ScannerUnavailable, scan_image_bytes
from .cards import active_card_from_token

router = APIRouter()
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 12_000_000
MAX_OUTPUT_BYTES = 1_500_000
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


def _require_member(user: dict, *, active: bool = True) -> None:
    if user.get("role") != "Member":
        raise HTTPException(403, "ID-card photos are available to Member accounts only.")
    if active and user.get("status") != "Active":
        raise HTTPException(403, "Only active members can manage an ID-card photo.")


def _require_durable_private_storage() -> None:
    """ID-card photo bytes are stored in the configured MongoDB database via GridFS."""
    if db is None:
        raise HTTPException(503, "MongoDB photo storage is unavailable.")


async def _normalized_jpeg(upload: UploadFile) -> bytes:
    raw = await upload.read(MAX_UPLOAD_BYTES + 1)
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Choose an image no larger than 5 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            probe = Image.open(io.BytesIO(raw))
            if probe.format not in ALLOWED_FORMATS:
                raise HTTPException(415, "Only JPEG, PNG and WEBP images are supported.")
            if getattr(probe, "is_animated", False):
                raise HTTPException(415, "Animated images are not supported.")
            if probe.width < 64 or probe.height < 64 or probe.width * probe.height > MAX_PIXELS:
                raise HTTPException(422, "Image dimensions must be at least 64×64 and no more than 12 megapixels.")
            probe.verify()
            image = Image.open(io.BytesIO(raw))
            image = ImageOps.exif_transpose(image)
            image.load()
            if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
            image.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=86, optimize=True, progressive=True)
            result = output.getvalue()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(422, "The uploaded file is not a safe, valid image.")
    if len(result) > MAX_OUTPUT_BYTES:
        raise HTTPException(413, "The processed ID-card photo is too large. Choose a smaller image.")
    return result


async def _remove_photo_for_owner(owner_id) -> None:
    old = await db.card_photos.find_one({"owner_id": owner_id})
    if not old:
        return
    # Remove metadata first: a storage failure must never leave the photo retrievable.
    await db.card_photos.delete_one({"_id": old["_id"]})
    try:
        await delete_id_card_photo(old)
    except Exception:
        # Orphaned private object is inaccessible and can be cleaned up by storage lifecycle.
        pass


@router.post("/api/cards/me/photo")
@limiter.limit("5/hour")
async def upload_own_id_card_photo(
    request: Request,
    photo: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    _require_member(user)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError:
            raise HTTPException(400, "Invalid upload content length.")
        if declared_length > MAX_UPLOAD_BYTES + 128 * 1024:
            raise HTTPException(413, "Choose an image no larger than 5 MB.")
    _require_durable_private_storage()
    current = await db.users.find_one({"_id": user["_id"]}, {"id_card_photo_consent": 1, "status": 1})
    if not current or current.get("status") != "Active":
        raise HTTPException(403, "Only active members can upload an ID-card photo.")
    if current.get("id_card_photo_consent") is not True:
        raise HTTPException(403, "Grant ID-card photo consent before uploading.")
    content = await _normalized_jpeg(photo)
    try:
        await asyncio.to_thread(scan_image_bytes, content)
    except MalwareDetected as exc:
        raise HTTPException(422, "The uploaded image failed the malware scan.") from exc
    except ScannerUnavailable as exc:
        raise HTTPException(503, "ID-card photo scanning is unavailable. Uploads are disabled until ClamAV is healthy.") from exc
        try:
        stored = await store_id_card_photo(user["_id"], content)
    except Exception as exc:
        raise HTTPException(502, "Private ID-card photo storage failed. No photo was published.") from exc

    # Re-check consent after the storage operation to close the upload/revocation race.
    latest = await db.users.find_one({"_id": user["_id"]}, {"id_card_photo_consent": 1, "status": 1})
    if not latest or latest.get("status") != "Active" or latest.get("id_card_photo_consent") is not True:
        try:
            await delete_id_card_photo(stored)
        except Exception:
            pass
        raise HTTPException(409, "Photo consent changed during upload. The new photo was not activated.")

    now = utcnow()
    record = {
        "owner_id": user["_id"],
        **stored,
        "content_type": "image/jpeg",
        "size": len(content),
        "updated_at": now,
    }
    previous = await db.card_photos.find_one({"owner_id": user["_id"]})
    await db.card_photos.update_one(
        {"owner_id": user["_id"]},
        {"$set": record, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )

    # Close the remaining revoke/upload race: consent may be withdrawn after the
    # pre-write check but before the photo metadata becomes visible. Re-check
    # after activation and remove the record/object if consent is no longer active.
    final_consent = await db.users.find_one(
        {"_id": user["_id"]},
        {"id_card_photo_consent": 1, "status": 1},
    )
    if not final_consent or final_consent.get("status") != "Active" or final_consent.get("id_card_photo_consent") is not True:
        await db.card_photos.delete_one({"owner_id": user["_id"], "gridfs_id": stored.get("gridfs_id")})
        try:
            await asyncio.to_thread(delete_attachment, stored)
        except Exception:
            pass
        raise HTTPException(409, "Photo consent changed during upload. The photo was not activated.")

    if previous:
        try:
            await delete_id_card_photo(previous)
        except Exception:
            pass
    await audit(user, "id_card_photo_uploaded", str(user["_id"]), {"content_type": "image/jpeg", "bytes": len(content)}, request)
    return {"uploaded": True, "content_type": "image/jpeg", "size": len(content), "updated_at": now}


@router.get("/api/cards/me/photo")
@limiter.limit("30/minute")
async def get_own_id_card_photo(request: Request, user: dict = Depends(get_current_user)):
    _require_member(user, active=False)
    current = await db.users.find_one({"_id": user["_id"]}, {"id_card_photo_consent": 1})
    if not current or current.get("id_card_photo_consent") is not True:
        raise HTTPException(403, "ID-card photo consent is not active.")
    record = await db.card_photos.find_one({"owner_id": user["_id"]})
    if not record:
        raise HTTPException(404, "No ID-card photo has been uploaded.")
    _require_durable_private_storage()
    try:
        content = await read_id_card_photo(record)
    except Exception as exc:
        raise HTTPException(502, "Could not retrieve your private ID-card photo.") from exc
    return Response(content=content, media_type="image/jpeg", headers={
        "Cache-Control": "private, no-store, max-age=0",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
        "Vary": "Authorization",
    })


@router.delete("/api/cards/me/photo")
@limiter.limit("10/hour")
async def delete_own_id_card_photo(request: Request, user: dict = Depends(get_current_user)):
    _require_member(user, active=False)
    await _remove_photo_for_owner(user["_id"])
    await audit(user, "id_card_photo_deleted", str(user["_id"]), {}, request)
    return {"deleted": True}


@router.get("/api/verify/{token}/photo")
@limiter.limit("20/minute")
async def get_verified_card_photo(
    token: str,
    request: Request,
    actor: dict = Depends(allow("Founder", "Core Management")),
):
    if len(token) < 30 or len(token) > 200:
        raise HTTPException(404, "Card not found")
    card = await active_card_from_token(token)
    if not card:
        raise HTTPException(404, "Card is invalid or revoked.")
    member = await db.users.find_one({"_id": ObjectId(card["member_id"])})
    if not member or member.get("status") != "Active":
        raise HTTPException(404, "Member is not active.")
    if actor.get("role") == "Core Management" and member.get("role") != "Member":
        raise HTTPException(403, "Core Management can view Member ID photos only.")
    if member.get("id_card_photo_consent") is not True:
        raise HTTPException(404, "No consented ID-card photo is available.")
    record = await db.card_photos.find_one({"owner_id": member["_id"]})
    if not record:
        raise HTTPException(404, "No ID-card photo has been uploaded.")
    _require_durable_private_storage()
    try:
        content = await __import__("asyncio").to_thread(read_attachment, record)
    except Exception as exc:
        raise HTTPException(502, "Could not retrieve the private ID-card photo.") from exc
    await audit(actor, "id_card_photo_viewed", str(member["_id"]), {"member_id": member.get("member_id")}, request)
    return Response(content=content, media_type="image/jpeg", headers={
        "Cache-Control": "private, no-store, max-age=0",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
        "Vary": "Authorization",
    })

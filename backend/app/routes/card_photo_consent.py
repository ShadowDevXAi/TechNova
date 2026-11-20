"""Explicit member consent for a future separately stored ID-card photo.

This endpoint records consent only. It never publishes or reuses the private,
browser-encrypted profile image. A separately reviewed photo-storage workflow
must exist before any image is returned by card verification.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from ..storage import delete_attachment

from ..core import audit, db, get_current_user, limiter, utcnow

router = APIRouter()


class CardPhotoConsentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consent: bool


def _require_member(user: dict) -> None:
    if user.get("role") != "Member":
        raise HTTPException(403, "ID-card photo consent is available to Member accounts only.")


def _require_active_member(user: dict) -> None:
    _require_member(user)
    if user.get("status") != "Active":
        raise HTTPException(403, "Only active members can grant ID-card photo consent.")


@router.get("/api/cards/me/photo-consent")
@limiter.limit("30/minute")
async def get_own_card_photo_consent(request: Request, user: dict = Depends(get_current_user)):
    """Return only the signed-in member's own ID-card photo consent state."""
    _require_member(user)
    record = await db.users.find_one(
        {"_id": user["_id"]},
        {"id_card_photo_consent": 1, "id_card_photo_consent_at": 1, "id_card_photo_consent_revoked_at": 1},
    ) or {}
    consent_granted = record.get("id_card_photo_consent") is True
    photo_record = await db.card_photos.find_one({"owner_id": user["_id"]}, {"_id": 1}) if consent_granted else None
    photo_available = photo_record is not None
    return {
        "consent": consent_granted,
        "consent_at": record.get("id_card_photo_consent_at"),
        "revoked_at": record.get("id_card_photo_consent_revoked_at"),
        "photo_uploaded": photo_available,
        "photo_sharing_enabled": consent_granted and photo_available,
        "message": "Your separate ID-card photo is available only to authorized staff during an active ID verification." if photo_available else "Upload a separate ID-card photo after granting consent.",
    }


@router.put("/api/cards/me/photo-consent")
@limiter.limit("10/hour")
async def update_own_card_photo_consent(
    payload: CardPhotoConsentIn,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Record explicit opt-in or immediate withdrawal for future ID-card photo use."""
    if payload.consent:
        _require_active_member(user)
    else:
        # Consent withdrawal remains available even if the account is suspended.
        _require_member(user)
    now = utcnow()
    update = {
        "$set": {
            "id_card_photo_consent": payload.consent,
            "id_card_photo_consent_updated_at": now,
        }
    }
    if payload.consent:
        update["$set"]["id_card_photo_consent_at"] = now
        update["$set"]["id_card_photo_consent_revoked_at"] = None
    else:
        update["$set"]["id_card_photo_consent_revoked_at"] = now

    await db.users.update_one({"_id": user["_id"]}, update)
    if not payload.consent:
        # Withdrawal is effective before storage cleanup; the verification endpoint
        # checks this flag before every read, so a cleanup failure cannot expose it.
        photo = await db.card_photos.find_one({"owner_id": user["_id"]})
        if photo:
            await db.card_photos.delete_one({"_id": photo["_id"]})
            try:
                import asyncio
                await asyncio.to_thread(delete_attachment, photo)
            except Exception:
                # The object remains private and inaccessible; lifecycle cleanup can remove it.
                pass
    await audit(
        user,
        "id_card_photo_consent_granted" if payload.consent else "id_card_photo_consent_revoked",
        str(user["_id"]),
        {"consent": payload.consent},
        request,
    )
    return {
        "consent": payload.consent,
        "consent_at": now if payload.consent else None,
        "revoked_at": None if payload.consent else now,
        "photo_sharing_enabled": False,
        "message": "Your preference was saved. No photo is published or shared by this setting.",
    }

"""Explicit member consent for a future separately stored ID-card photo.

This endpoint records consent only. It never publishes or reuses the private,
browser-encrypted profile image. A separately reviewed photo-storage workflow
must exist before any image is returned by card verification.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

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
    return {
        "consent": record.get("id_card_photo_consent") is True,
        "consent_at": record.get("id_card_photo_consent_at"),
        "revoked_at": record.get("id_card_photo_consent_revoked_at"),
        "photo_sharing_enabled": False,
        "message": "This setting records your preference only. A separate secure card-photo upload and review is required before any photo can be displayed.",
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

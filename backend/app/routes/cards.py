"""Digital ID, QR verification and audit endpoints.

Issues/revokes signed member cards, verifies scans, confirms task completion and
exposes the founder-only audit log.

All protected operations reuse authentication and role checks from app.core.
"""

from fastapi import APIRouter
from ..core import *  # Shared database, schemas, authorization and business helpers.

router = APIRouter()

# Purpose: signed card token handles the cards feature flow and returns its API result.
def signed_card_token(member_key: str, card_id: ObjectId) -> str:
    """Create a reproducible signed QR token without storing the raw token."""
    card_key = str(card_id)
    payload = f"technova-card-v2:{member_key}:{card_key}".encode("utf-8")
    signature = hmac.new(settings.jwt_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"{card_key}.{signature}"


# Purpose: active card from token handles the cards feature flow and returns its API result.
async def active_card_from_token(raw: str) -> dict | None:
    """Validate persistent signed QR tokens and continue to accept legacy random tokens."""
    card_key, separator, signature = raw.partition(".")
    if separator and ObjectId.is_valid(card_key) and len(signature) == 64:
        card = await db.cards.find_one({
            "_id": ObjectId(card_key), "status": "Active", "token_version": 2,
        })
        if not card:
            return None
        expected = signed_card_token(card["member_id"], card["_id"]).partition(".")[2]
        if not hmac.compare_digest(signature, expected):
            return None
        if not hmac.compare_digest(str(card.get("token_hash", "")), token_hash(raw)):
            return None
        return card
    return await db.cards.find_one({"token_hash": token_hash(raw), "status": "Active"})


# Purpose: mint card handles the cards feature flow and returns its API result.
async def mint_card(target: dict, actor: dict, request: Request, *, reuse_active: bool, action: str) -> dict:
    if target.get("status") != "Active":
        raise HTTPException(400, "Only active members can receive cards")
    member_key = str(target["_id"])
    if reuse_active:
        current = await db.cards.find_one({
            "member_id": member_key, "status": "Active", "token_version": 2,
        })
        if current:
            raw = signed_card_token(member_key, current["_id"])
            return {
                "member_id": target["member_id"],
                "verification_url": f"{settings.public_app_url.rstrip('/')}/verify/{raw}",
                "status": "Active", "issued_at": current["issued_at"],
            }
    await db.cards.update_many(
        {"member_id": member_key, "status": "Active"},
        {"$set": {"status": "Revoked", "revoked_at": utcnow()}},
    )
    card_id = ObjectId()
    raw = signed_card_token(member_key, card_id)
    issued_at = utcnow()
    await db.cards.insert_one({
        "_id": card_id, "member_id": member_key, "token_hash": token_hash(raw),
        "token_version": 2, "status": "Active", "issued_by": str(actor["_id"]),
        "issued_at": issued_at, "revoked_at": None,
    })
    await audit(actor, action, member_key, {"member_id": target["member_id"]}, request)
    return {
        "member_id": target["member_id"],
        "verification_url": f"{settings.public_app_url.rstrip('/')}/verify/{raw}",
        "status": "Active", "issued_at": issued_at,
    }


# Purpose: issue own card handles the cards feature flow and returns its API result.
@router.post("/api/cards/me/issue")
async def issue_own_card(request: Request, actor: dict = Depends(get_current_user)):
    """Return the signed-in user's stable QR card, creating it only if necessary."""
    if actor.get("status") != "Active":
        raise HTTPException(403, "Only active members can issue a digital ID")
    return await mint_card(actor, actor, request, reuse_active=True, action="card_self_issued")


# Purpose: issue card handles the cards feature flow and returns its API result.
@router.post("/api/cards/{member_id}/issue")
async def issue_card(member_id: str, request: Request, actor: dict = Depends(allow("Founder"))):
    target = await db.users.find_one({"_id": oid(member_id)})
    if not target:
        raise HTTPException(404, "Member not found")
    return await mint_card(target, actor, request, reuse_active=False, action="card_issued")


# Purpose: revoke card handles the cards feature flow and returns its API result.
@router.post("/api/cards/{member_id}/revoke")
async def revoke_card(member_id: str, request: Request, actor: dict = Depends(allow("Founder"))):
    target=await db.users.find_one({"_id":oid(member_id)})
    if not target: raise HTTPException(404,"Member not found")
    await db.cards.update_many({"member_id":str(target["_id"]),"status":"Active"},{"$set":{"status":"Revoked","revoked_at":utcnow()}})
    await audit(actor,"card_revoked",member_id,{},request)
    return {"message":"Active cards revoked"}

# Purpose: verify card handles the cards feature flow and returns its API result.
@router.get("/api/verify/{token}")
async def verify_card(token: str, request: Request, actor: dict = Depends(allow("Founder", "Core Management"))):
    if len(token)<30 or len(token)>200:
        raise HTTPException(404, "Card not found")
    card = await active_card_from_token(token)
    if not card:
        return {"valid": False, "status": "Invalid or revoked"}
    member = await db.users.find_one({"_id": oid(card["member_id"])})
    if not member or member["status"] != "Active":
        return {"valid": False, "status": "Member inactive"}
    if actor.get("role") == "Core Management" and member.get("role") != "Member":
        raise HTTPException(403, "Core Management can verify Member IDs only")
    await audit(actor, "card_verified", str(member["_id"]), {"member_id": member["member_id"]}, request)
    progress = await member_progress_summary(member["_id"])
    return {
        "valid": True,
        "status": "Active",
        "name": member["name"],
        "member_id": member["member_id"],
        "role": member["role"],
        "team": member.get("team", "Unassigned"),
        "club": "TechNova",
        "progression_type": progress.get("progression_type", "xp"),
        "xp": progress["xp"],
        "level": progress["level"],
        "level_title": progress["level_title"],
        "credits": progress["credits"],
        "credit_rank": progress["credit_rank"],
    }

# Purpose: confirm card verification handles the cards feature flow and returns its API result.
@router.post("/api/verify/{token}/confirm")
async def confirm_card_verification(token: str, request: Request, actor: dict = Depends(allow("Founder", "Core Management"))):
    """Record an authenticated staff confirmation after a QR has been scanned and checked."""
    if len(token) < 30 or len(token) > 200:
        raise HTTPException(404, "Card not found")
    card = await active_card_from_token(token)
    if not card:
        raise HTTPException(404, "Card is invalid or revoked")
    member = await db.users.find_one({"_id": oid(card["member_id"])})
    if not member or member.get("status") != "Active":
        raise HTTPException(400, "Member is not active")
    if actor.get("role") == "Core Management" and member.get("role") != "Member":
        raise HTTPException(403, "Core Management can confirm Member IDs only")
    await audit(actor, "card_verification_confirmed", str(member["_id"]), {"member_id": member["member_id"]}, request)
    return {"confirmed": True, "message": "Identity verification confirmation recorded", "member_id": member["member_id"], "name": member["name"]}

# Purpose: confirm task completion handles the cards feature flow and returns its API result.
@router.post("/api/tasks/{task_id}/confirm-completion")
async def confirm_task_completion(task_id: str, data: TaskCompletionConfirm, request: Request, actor: dict = Depends(allow("Founder", "Core Management"))):
    """Confirm a Review task only when the assigned person's active QR is scanned."""
    task = await db.tasks.find_one({"_id": oid(task_id)})
    if not task:
        raise HTTPException(404, "Task not found")
    if task.get("status") != "Review":
        raise HTTPException(409, "This task is not awaiting completion confirmation")
    if not task.get("submission_evidence_url") or not task.get("submission_attested"):
        raise HTTPException(409, "This submission has no screenshot evidence or member attestation")

    member = await db.users.find_one({"_id": task["assignee_id"]})
    if not member or member.get("status") != "Active":
        raise HTTPException(400, "The assigned member is not active")
    if actor.get("role") == "Core Management" and member.get("role") != "Member":
        raise HTTPException(403, "Core Management can confirm Member task submissions only")

    card = await active_card_from_token(data.card_token)
    if not card or card.get("member_id") != str(member["_id"]):
        raise HTTPException(403, "Scan the active QR code belonging to this task's assignee")

    now = utcnow()
    result = await db.tasks.update_one(
        {"_id": task["_id"], "status": "Review"},
        {"$set": {
            "status": "Done",
            "completion_confirmed_at": now,
            "completion_confirmed_by": actor["_id"],
            "completion_confirmed_by_name": actor["name"],
            "completion_confirmed_by_role": actor["role"],
            "credits_awarded": task_credit_value(task),
            "credits_awarded_at": now,
            "updated_at": now,
        }},
    )
    if result.modified_count != 1:
        raise HTTPException(409, "Task was already confirmed or changed; refresh the task board")
    await create_notification(
        member,
        "Task completion approved",
        f'{actor["name"]} approved your submission for "{task["title"]}".',
        "task_approved",
        task_id=task_id,
    )
    await audit(
        actor,
        "task_completion_confirmed",
        task_id,
        {"assignee_id": str(member["_id"]), "member_id": member["member_id"]},
        request,
    )
    return clean_task(await db.tasks.find_one({"_id": task["_id"]}))


# Purpose: list audit handles the cards feature flow and returns its API result.
@router.get("/api/audit")
async def list_audit(limit: int = 50, user: dict = Depends(allow("Founder"))):
    limit = max(1, min(limit, 200))
    docs = await db.audit.find().sort("created_at", -1).limit(limit).to_list(limit)

    # Resolve audit targets that refer to members so the Founder sees names,
    # not internal Mongo IDs or club member IDs, in the Target column.
    target_values = list({str(x.get("target")) for x in docs if x.get("target")})
    target_object_ids = [
        ObjectId(value) for value in target_values if ObjectId.is_valid(value)
    ]
    member_query = []
    if target_object_ids:
        member_query.append({"_id": {"$in": target_object_ids}})
    if target_values:
        member_query.append({"member_id": {"$in": target_values}})
    target_names = {}
    if member_query:
        members_by_target = await db.users.find({"$or": member_query}).to_list(length=500)
        for member in members_by_target:
            name = member.get("name") or member.get("member_id") or "Member"
            target_names[str(member["_id"])] = name
            if member.get("member_id"):
                target_names[member["member_id"]] = name

    return [{
        "id": str(x["_id"]),
        "actor_role": x.get("actor_role"),
        "action": x["action"],
        "target": target_names.get(str(x.get("target")), x.get("target")),
        "created_at": x.get("created_at"),
        "details": x.get("details", {}),
    } for x in docs]


# TechNova Hub: authenticated collaboration modules
HUB_COLLECTIONS = {
    "projects": db.hub_projects, "challenges": db.hub_challenges,
    "events": db.hub_events, "resources": db.hub_resources,
    "discussions": db.hub_discussions, "rewards": db.hub_rewards, "attendance": db.hub_attendance,
    "polls": db.hub_polls, "mentorship": db.hub_mentorship,
    "messages": db.hub_messages, "certificates": db.hub_certificates,
}
HUB_STAFF = {"Founder", "Core Management", "Faculty"}


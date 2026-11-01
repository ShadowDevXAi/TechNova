"""Member directory and leaderboard endpoints.

Provides member listings, member administration and ranked club standings.

All protected operations reuse authentication and role checks from app.core.
"""

from fastapi import APIRouter
from ..core import *  # Shared database, schemas, authorization and business helpers.

router = APIRouter()

# Purpose: leaderboard handles the members feature flow and returns its API result.
@router.get("/api/leaderboard")
async def leaderboard(user: dict = Depends(get_current_user)):
    """Top 10 active Members by approved task credits, plus the signed-in Member's position."""
    active_members = await db.users.find({
        "role": "Member", "status": "Active",
    }).sort("name", 1).limit(5000).to_list(5000)
    credit_rows = await db.tasks.aggregate([
        {"$match": {"status": "Done", "credits_awarded": {"$gt": 0}}},
        {"$group": {
            "_id": "$assignee_id",
            "credits": {"$sum": "$credits_awarded"},
            "completed_tasks": {"$sum": 1},
        }},
    ]).to_list(length=5000)
    totals = {row["_id"]: {
        "credits": int(row.get("credits", 0)),
        "completed_tasks": int(row.get("completed_tasks", 0)),
    } for row in credit_rows}
    penalty_rows = await db.credit_penalties.aggregate([
        {"$group": {"_id": "$user_id", "penalties": {"$sum": "$points"}}},
    ]).to_list(length=5000)
    penalties = {row["_id"]: int(row.get("penalties", 0)) for row in penalty_rows}

    entries = []
    for member in active_members:
        score = totals.get(member["_id"], {"credits": 0, "completed_tasks": 0})
        entries.append({
            "id": str(member["_id"]),
            "member_id": member.get("member_id", ""),
            "name": member.get("name", "Member"),
            "team": member.get("team", "Unassigned"),
            "credits": score["credits"] - penalties.get(member["_id"], 0),
            "credits_earned": score["credits"],
            "credits_penalized": penalties.get(member["_id"], 0),
            "completed_tasks": score["completed_tasks"],
        })
    entries.sort(key=lambda row: (-row["credits"], -row["completed_tasks"], row["name"].casefold()))
    for position, entry in enumerate(entries, start=1):
        entry["position"] = position
        entry["rank"] = member_rank(entry["credits"])
        entry["top_three_eligible"] = position <= 3 and entry["credits"] > 0

    mine = next((entry for entry in entries if entry["id"] == str(user["_id"])), None)
    public_entries = [{key: value for key, value in entry.items() if key != "id"} for entry in entries]
    return {
        "top_10": public_entries[:10],
        "top_three": public_entries[:3],
        "my_entry": ({key: value for key, value in mine.items() if key != "id"} if mine else None),
        "active_member_count": len(entries),
        "credits_rule": "Credits are granted once after staff approval. Deadline and disciplinary penalties are deducted transparently.",
    }


# Purpose: member progress returns the XP level and credit rank used on digital ID cards.
@router.get("/api/members/{member_id}/progress")
async def member_progress(member_id: str, user: dict = Depends(get_current_user)):
    """Return progression for the signed-in member or a member visible to management."""
    target_id = oid(member_id)
    is_self = str(target_id) == str(user["_id"])
    if not is_self and user.get("role") not in PRIVILEGED:
        raise HTTPException(403, "You can only view your own progression")
    member = await db.users.find_one({"_id": target_id})
    if not member:
        raise HTTPException(404, "Member not found")
    progress = await member_progress_summary(target_id)
    return {
        "id": str(member["_id"]),
        "member_id": member.get("member_id", ""),
        "name": member.get("name", "Member"),
        "role": member.get("role", "Member"),
        "team": member.get("team", "Unassigned"),
        **progress,
    }


# Purpose: list members handles the members feature flow and returns its API result.
@router.get("/api/members")
async def list_members(q: str = "", user: dict = Depends(get_current_user)):
    if user["role"] not in PRIVILEGED:
        return [clean_user(user)]
    query = {}
    if q:
        query={"$or":[{"name":{"$regex":q,"$options":"i"}},{"email":{"$regex":q,"$options":"i"}},{"member_id":{"$regex":q,"$options":"i"}},{"team":{"$regex":q,"$options":"i"}}]}
    docs = await db.users.find(query).sort("created_at",-1).limit(500).to_list(500)
    return [clean_user(x) for x in docs]

# Purpose: create member handles the members feature flow and returns its API result.
@router.post("/api/members", status_code=201)
async def create_member(data: MemberCreate, request: Request, actor: dict = Depends(allow("Founder"))):
    email=str(data.email).lower()
    if await db.users.find_one({"email":email}):
        raise HTTPException(409,"Email already exists")
    if data.role=="Founder":
        raise HTTPException(403,"Founder role cannot be assigned from this endpoint")
    member_id=await next_member_id(data.role)
    doc={"member_id":member_id,"name":data.name.strip(),"email":email,"password_hash":hash_password(data.password),"role":data.role,"team":data.team,"status":data.status,"created_at":utcnow(),"approved_at":utcnow() if data.status=="Active" else None}
    try: res=await db.users.insert_one(doc)
    except DuplicateKeyError: raise HTTPException(409,"Member ID collision; retry")
    created_member = {**doc, "_id": res.inserted_id}
    if doc["status"] == "Active":
        await create_notification(
            created_member,
            "Your TechNova account is ready",
            f'Your TechNova account has been created by {actor["name"]}. You can now sign in at {settings.public_app_url}. For security, your password is not included in this email.',
            "account_created",
        )
    else:
        await create_notification(
            created_member,
            "TechNova account created · approval pending",
            "A TechNova account has been created for you and is waiting for administrator approval. You will receive an email when it is activated.",
            "account_created",
        )
    await audit(actor,"member_created",str(res.inserted_id),{"role":data.role},request)
    return clean_user(created_member)

# Purpose: update member handles the members feature flow and returns its API result.
@router.patch("/api/members/{member_id}")
async def update_member(member_id: str, data: MemberPatch, request: Request, actor: dict = Depends(allow("Founder","Core Management"))):
    target=await db.users.find_one({"_id":oid(member_id)})
    if not target: raise HTTPException(404,"Member not found")
    if target["role"]=="Founder": raise HTTPException(403,"Founder account cannot be changed here")
    changes=data.model_dump(exclude_unset=True,exclude_none=True)
    if "role" in changes and changes["role"]=="Founder": raise HTTPException(403,"Founder role cannot be assigned")
    if actor["role"]!="Founder" and "role" in changes: raise HTTPException(403,"Only Founder can change roles")
    if "team" in changes:
        if actor["role"] != "Founder":
            raise HTTPException(403, "Only the Founder can assign teams")
        team_name = changes["team"].strip()
        if not team_name:
            raise HTTPException(422, "Team name cannot be empty")
        if team_name != "Unassigned" and not await db.teams.find_one({"name": team_name}):
            raise HTTPException(400, "Choose an existing team")
        changes["team"] = team_name
    if actor["role"]!="Founder" and changes.get("status")=="Suspended": raise HTTPException(403,"Only Founder can suspend members")
    if changes.get("status")=="Active": changes["approved_at"]=utcnow()
    if changes:
        await db.users.update_one({"_id":target["_id"]},{"$set":changes})
    notification_fields = [field for field in ("role", "team", "status") if field in changes]
    if notification_fields:
        if changes.get("status") == "Suspended":
            notification_title = "TechNova account suspended"
            notification_message = "Your TechNova account has been suspended by club management. Contact the Founder if you need clarification."
            notification_type = "account_suspended"
        elif changes.get("status") == "Active":
            notification_title = "TechNova account activated"
            notification_message = f'Your TechNova account has been activated. You can now sign in at {settings.public_app_url}.'
            notification_type = "account_activated"
        else:
            notification_title = "TechNova membership updated"
            parts = []
            if "role" in changes:
                parts.append(f'Your club role is now {changes["role"]}.')
            if "team" in changes:
                parts.append(f'Your assigned team is now {changes["team"]}.')
            notification_message = " ".join(parts) or "Your TechNova membership details were updated by club management."
            notification_type = "membership_updated"
        await create_notification(
            target,
            notification_title,
            notification_message,
            notification_type,
        )
    await audit(actor,"member_updated",member_id,{"fields":list(changes)},request)
    return clean_user(await db.users.find_one({"_id":target["_id"]}))

# Purpose: approve member handles the members feature flow and returns its API result.
@router.post("/api/members/{member_id}/approve")
async def approve_member(member_id: str, request: Request, actor: dict = Depends(allow("Founder","Core Management"))):
    target=await db.users.find_one({"_id":oid(member_id)})
    if not target: raise HTTPException(404,"Member not found")
    if target["role"]=="Founder": raise HTTPException(403,"Invalid target")
    was_active = target.get("status") == "Active"
    await db.users.update_one({"_id":target["_id"]},{"$set":{"status":"Active","approved_at":utcnow()}})
    if not was_active:
        await create_notification(
            target,
            "Your TechNova registration has been approved",
            f'Your membership has been approved by {actor["name"]}. You can now sign in at {settings.public_app_url}. Welcome to TechNova!',
            "account_approved",
        )
    await audit(actor,"member_approved",member_id,{},request)
    return clean_user(await db.users.find_one({"_id":target["_id"]}))

# Purpose: deactivate member handles the members feature flow and returns its API result.
@router.delete("/api/members/{member_id}")
async def deactivate_member(member_id: str, request: Request, actor: dict = Depends(allow("Founder"))):
    target=await db.users.find_one({"_id":oid(member_id)})
    if not target: raise HTTPException(404,"Member not found")
    if target["role"]=="Founder": raise HTTPException(403,"Founder account cannot be deleted")
    was_active = target.get("status") != "Suspended"
    await db.users.update_one({"_id":target["_id"]},{"$set":{"status":"Suspended","suspended_at":utcnow()}})
    await db.cards.update_many({"member_id":str(target["_id"]),"status":"Active"},{"$set":{"status":"Revoked","revoked_at":utcnow()}})
    if was_active:
        await create_notification(
            target,
            "TechNova account suspended",
            "Your TechNova account has been suspended by the Founder and your active digital ID cards have been revoked. Contact club management for more information.",
            "account_suspended",
        )
    await audit(actor,"member_suspended",member_id,{},request)
    return {"message":"Member suspended and active cards revoked"}


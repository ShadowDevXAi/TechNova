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
    await audit(actor,"member_created",str(res.inserted_id),{"role":data.role},request)
    return clean_user({**doc,"_id":res.inserted_id})

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
    if changes: await db.users.update_one({"_id":target["_id"]},{"$set":changes})
    await audit(actor,"member_updated",member_id,{"fields":list(changes)},request)
    return clean_user(await db.users.find_one({"_id":target["_id"]}))

# Purpose: approve member handles the members feature flow and returns its API result.
@router.post("/api/members/{member_id}/approve")
async def approve_member(member_id: str, request: Request, actor: dict = Depends(allow("Founder","Core Management"))):
    target=await db.users.find_one({"_id":oid(member_id)})
    if not target: raise HTTPException(404,"Member not found")
    if target["role"]=="Founder": raise HTTPException(403,"Invalid target")
    await db.users.update_one({"_id":target["_id"]},{"$set":{"status":"Active","approved_at":utcnow()}})
    await audit(actor,"member_approved",member_id,{},request)
    return clean_user(await db.users.find_one({"_id":target["_id"]}))

# Purpose: deactivate member handles the members feature flow and returns its API result.
@router.delete("/api/members/{member_id}")
async def deactivate_member(member_id: str, request: Request, actor: dict = Depends(allow("Founder"))):
    target=await db.users.find_one({"_id":oid(member_id)})
    if not target: raise HTTPException(404,"Member not found")
    if target["role"]=="Founder": raise HTTPException(403,"Founder account cannot be deleted")
    await db.users.update_one({"_id":target["_id"]},{"$set":{"status":"Suspended","suspended_at":utcnow()}})
    await db.cards.update_many({"member_id":str(target["_id"]),"status":"Active"},{"$set":{"status":"Revoked","revoked_at":utcnow()}})
    await audit(actor,"member_suspended",member_id,{},request)
    return {"message":"Member suspended and active cards revoked"}


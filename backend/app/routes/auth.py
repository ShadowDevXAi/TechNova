"""Authentication and member-profile endpoints.

Registration, login, password recovery, session identity, dashboard and credit ledger.

All protected operations reuse authentication and role checks from app.core.
"""

from fastapi import APIRouter
from ..core import *  # Shared database, schemas, authorization and business helpers.

router = APIRouter()

# Purpose: register handles the auth feature flow and returns its API result.
@router.post("/api/auth/register", status_code=201)
@limiter.limit("8/hour")
async def register(data: RegisterIn, request: Request):
    email = str(data.email).lower()
    if await db.users.find_one({"email":email}):
        raise HTTPException(409,"An account with this email already exists")
    # Public signups can only create pending Member accounts.
    member_id = await next_member_id("Member")
    doc = {"member_id":member_id,"name":data.name.strip(),"email":email,"password_hash":hash_password(data.password),"role":"Member","team":data.team.strip() or "Unassigned","status":"Pending","created_at":utcnow(),"approved_at":None}
    try:
        result = await db.users.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409,"Could not allocate member ID; please retry")
    await audit(None,"registration_submitted",str(result.inserted_id),{"email":email},request)
    return {"message":"Registration submitted. A club administrator must approve your account before you can sign in.","member_id":doc["member_id"]}

# Purpose: login handles the auth feature flow and returns its API result.
@router.post("/api/auth/login")
@limiter.limit("10/minute")
async def login(data: LoginIn, request: Request):
    user = await db.users.find_one({"email":str(data.email).lower()})
    if not user or not verify_password(data.password,user["password_hash"]):
        await audit(None,"login_failed","",{"email":str(data.email).lower()},request)
        raise HTTPException(401,"Incorrect email or password")
    if user["status"] == "Suspended" and user.get("suspension_temporary") and user.get("suspension_until") and user["suspension_until"] <= utcnow():
        await db.users.update_one({"_id": user["_id"]}, {"$set": {"status": "Active", "suspension_until": None, "suspension_temporary": False, "suspension_expired_at": utcnow()}})
        user = await db.users.find_one({"_id": user["_id"]})
        await resume_member_paused_tasks(user["_id"], utcnow())
    if user["status"] == "Suspended":
        if user.get("suspension_temporary") and user.get("suspension_until"):
            until_text = user["suspension_until"].astimezone(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y, %I:%M %p IST")
            reason_text = user.get("suspension_reason") or "Club rule review"
            raise HTTPException(403, f"Your account is temporarily suspended until {until_text}. Reason: {reason_text}")
        raise HTTPException(403, "Your account is suspended. Contact the Founder for reinstatement.")
    if user["status"] != "Active":
        raise HTTPException(403,"Your account is pending approval or unavailable")
    token = create_access_token(str(user["_id"]),user["role"])
    await audit(user,"login",str(user["_id"]),{},request)
    return {"access_token":token,"token_type":"bearer","user":clean_user(user)}

# Purpose: me handles the auth feature flow and returns its API result.
@router.get("/api/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return clean_user(user)

# Purpose: update profile handles the auth feature flow and returns its API result.
@router.patch("/api/auth/profile")
async def update_profile(body: dict, request: Request, user: dict = Depends(get_current_user)):
    if "team" in body and body.get("team") not in (None, "", user.get("team")):
        raise HTTPException(403, "Only the Founder can assign teams")
    allowed = {"name"}
    changes = {k: body[k].strip() for k in allowed if isinstance(body.get(k), str) and body[k].strip()}
    if "name" in changes and len(changes["name"]) > 100:
        raise HTTPException(422, "Name must be at most 100 characters")
    if "team" in changes and len(changes["team"]) > 80:
        raise HTTPException(422, "Team must be at most 80 characters")
    # Members may update their own display name/team, but not role, email, status or member ID.
    if changes:
        await db.users.update_one({"_id": user["_id"]}, {"$set": changes})
        await audit(user, "profile_updated", str(user["_id"]), {"fields": list(changes)}, request)
    return clean_user(await db.users.find_one({"_id": user["_id"]}))

# Purpose: change password handles the auth feature flow and returns its API result.
@router.post("/api/auth/change-password")
async def change_password(body: dict, user: dict = Depends(get_current_user)):
    old = body.get("current_password",""); new = body.get("new_password","")
    if not isinstance(new,str) or len(new)<12 or len(new)>128:
        raise HTTPException(422,"New password must be 12–128 characters")
    if not verify_password(old,user["password_hash"]):
        raise HTTPException(400,"Current password is incorrect")
    await db.users.update_one({"_id":user["_id"]},{"$set":{"password_hash":hash_password(new),"password_changed_at":utcnow()}})
    await audit(user,"password_changed",str(user["_id"]))
    return {"message":"Password changed"}

# Purpose: password reset request handles the auth feature flow and returns its API result.
@router.post("/api/auth/password-reset/request")
@limiter.limit("5/hour")
async def password_reset_request(body: dict, request: Request):
    email = str(body.get("email", "")).strip().lower()
    # Development reset tokens are opt-in only; fail closed on public deployments.
    response = {"message": "If the account exists, reset instructions will be sent."}
    delivery_mode = os.getenv("RESET_DELIVERY_MODE", "disabled").lower()
    if delivery_mode not in {"development", "email"}:
        return response
    if not email or len(email) > 320:
        return response
    user = await db.users.find_one({"email": email, "status": {"$ne": "Suspended"}})
    if user:
        raw = new_card_token()
        await db.password_resets.update_many({"user_id": user["_id"], "used": False}, {"$set": {"used": True}})
        await db.password_resets.insert_one({"user_id": user["_id"], "token_hash": token_hash(raw), "created_at": utcnow(), "expires_at": utcnow().replace(microsecond=0), "used": False})
        # Expiry is reset below using a timezone-aware timestamp to avoid naïve date handling.
        from datetime import timedelta
        await db.password_resets.update_one({"token_hash": token_hash(raw)}, {"$set": {"expires_at": utcnow() + timedelta(minutes=20)}})
        await audit(None, "password_reset_requested", str(user["_id"]), {}, request)
        if delivery_mode == "development":
            # Local-development convenience only; disable this outside local development.
            response["development_reset_token"] = raw
        elif delivery_mode == "email":
            if not (settings.smtp_host and settings.smtp_from_email):
                raise HTTPException(503, "Password reset email is not configured")
            message = EmailMessage()
            message["Subject"] = "Reset your TechNova portal password"
            message["From"] = settings.smtp_from_email
            message["To"] = email
            message.set_content(
                "A password reset was requested for your TechNova account. "
                "Use this one-time token within 20 minutes:\\n\\n"
                f"{raw}\\n\\nIf you did not request this, ignore this email."
            )
            try:
                context = ssl.create_default_context()
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
                    if settings.smtp_use_tls:
                        server.starttls(context=context)
                    if settings.smtp_username:
                        server.login(settings.smtp_username, settings.smtp_password)
                    server.send_message(message)
            except Exception:
                raise HTTPException(503, "Could not deliver password reset email; try again later")
    return response

# Purpose: password reset confirm handles the auth feature flow and returns its API result.
@router.post("/api/auth/password-reset/confirm")
@limiter.limit("10/hour")
async def password_reset_confirm(body: dict, request: Request):
    raw = body.get("token", "")
    new_password = body.get("new_password", "")
    if not isinstance(raw, str) or len(raw) < 30 or not isinstance(new_password, str) or len(new_password) < 12 or len(new_password) > 128:
        raise HTTPException(422, "Valid reset token and a 12–128 character password are required")
    reset = await db.password_resets.find_one({"token_hash": token_hash(raw), "used": False, "expires_at": {"$gt": utcnow()}})
    if not reset:
        raise HTTPException(400, "Reset token is invalid or expired")
    await db.users.update_one({"_id": reset["user_id"]}, {"$set": {"password_hash": hash_password(new_password), "password_changed_at": utcnow()}})
    await db.password_resets.update_one({"_id": reset["_id"]}, {"$set": {"used": True, "used_at": utcnow()}})
    await audit(None, "password_reset_completed", str(reset["user_id"]), {}, request)
    return {"message": "Password updated. Please sign in again."}

# Purpose: dashboard handles the auth feature flow and returns its API result.
@router.get("/api/dashboard")
async def dashboard(user: dict = Depends(get_current_user)):
    if user["role"] in PRIVILEGED:
        total = await db.users.count_documents({})
        active = await db.users.count_documents({"status":"Active"})
        pending = await db.users.count_documents({"status":"Pending"})
        active_task_filter = {"deleted_at": {"$exists": False}}
        tasks = await db.tasks.count_documents(active_task_filter)
        open_tasks = await db.tasks.count_documents({**active_task_filter, "status":{"$ne":"Done"}})
        done = await db.tasks.count_documents({**active_task_filter, "status":"Done"})
        recent = await db.tasks.find(active_task_filter).sort("created_at",-1).limit(6).to_list(6)
        return {"members_total":total,"members_active":active,"members_pending":pending,"tasks_total":tasks,"tasks_open":open_tasks,"tasks_done":done,"recent_tasks":[clean_task(x) for x in recent]}
    own_tasks = await db.tasks.find({"assignee_id":user["_id"], "deleted_at": {"$exists": False}}).sort("created_at",-1).limit(10).to_list(10)
    return {"members_total":1,"members_active":1,"members_pending":0,"tasks_total":len(own_tasks),"tasks_open":sum(x["status"]!="Done" for x in own_tasks),"tasks_done":sum(x["status"]=="Done" for x in own_tasks),"recent_tasks":[clean_task(x) for x in own_tasks]}

# Purpose: credit ledger handles the auth feature flow and returns its API result.
@router.get("/api/credits/ledger")
async def credit_ledger(user: dict = Depends(get_current_user)):
    """Return the signed-in user's own credit balance and a recent, auditable ledger."""
    earned_pipeline = await db.tasks.aggregate([
        {"$match": {"assignee_id": user["_id"], "status": "Done", "credits_awarded": {"$gt": 0}}},
        {"$group": {"_id": None, "total": {"$sum": "$credits_awarded"}}},
    ]).to_list(length=1)
    penalty_pipeline = await db.credit_penalties.aggregate([
        {"$match": {"user_id": user["_id"]}},
        {"$group": {"_id": None, "total": {"$sum": "$points"}}},
    ]).to_list(length=1)
    earned_total = int(earned_pipeline[0]["total"]) if earned_pipeline else 0
    penalized_total = int(penalty_pipeline[0]["total"]) if penalty_pipeline else 0

    earned_docs = await db.tasks.find({
        "assignee_id": user["_id"], "status": "Done", "credits_awarded": {"$gt": 0},
    }).sort("credits_awarded_at", -1).limit(50).to_list(50)
    penalty_docs = await db.credit_penalties.find({
        "user_id": user["_id"],
    }).sort("created_at", -1).limit(50).to_list(50)
    related_task_ids = [row.get("task_id") for row in penalty_docs if row.get("task_id")]
    related_tasks = await db.tasks.find({"_id": {"$in": related_task_ids}}).to_list(50) if related_task_ids else []
    task_titles = {row["_id"]: row.get("title", "Task") for row in related_tasks}

    entries = []
    for task in earned_docs:
        entries.append({
            "id": str(task["_id"]), "type": "earned", "title": task.get("title", "Completed task"),
            "points": int(task.get("credits_awarded", 0)), "reason": "Staff-approved task completion",
            "created_at": task.get("credits_awarded_at") or task.get("completion_confirmed_at") or task.get("updated_at"),
        })
    for penalty in penalty_docs:
        entries.append({
            "id": str(penalty["_id"]), "type": "penalty",
            "title": task_titles.get(penalty.get("task_id"), "Club rule penalty"),
            "points": -int(penalty.get("points", 0)), "reason": penalty.get("reason", "Credit adjustment"),
            "category": penalty.get("category", "disciplinary"), "created_at": penalty.get("created_at"),
        })
    entries.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    entries = [{
        **row,
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    } for row in entries[:50]]
    return {
        "balance": earned_total - penalized_total,
        "earned_total": earned_total,
        "penalized_total": penalized_total,
        "entries": entries,
    }



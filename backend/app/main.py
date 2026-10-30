from contextlib import asynccontextmanager
import asyncio
import os
import hmac
import hashlib
from datetime import datetime, timezone
from bson import ObjectId
from fastapi import FastAPI, Depends, HTTPException, status, Header, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from email.message import EmailMessage
import smtplib
import ssl
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
import re
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pymongo.errors import DuplicateKeyError
from pymongo import ReturnDocument
from motor.motor_asyncio import AsyncIOMotorDatabase
from .config import settings
from .db import client, db, ensure_indexes
from .security import hash_password, verify_password, create_access_token, decode_access_token, new_card_token, token_hash, utcnow
from .models import RegisterIn, LoginIn, MemberCreate, MemberPatch, TaskCreate, TaskPatch, TaskBulkConfirm, TaskCompletionConfirm, TeamCreate

bearer = HTTPBearer(auto_error=False)
PRIVILEGED = {"Founder", "Core Management"}
ALL_ROLES = {"Founder", "Core Management", "Member"}

def oid(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(400, "Invalid record ID")
    return ObjectId(value)

def clean_user(doc: dict) -> dict:
    return {"id": str(doc["_id"]), "member_id": doc["member_id"], "name": doc["name"], "email": doc["email"], "role": doc["role"], "team": doc.get("team","Unassigned"), "status": doc["status"], "created_at": doc.get("created_at")}

def clean_task(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "assignment_group_id": doc.get("assignment_group_id"),
        "title": doc["title"],
        "description": doc.get("description", ""),
        "project": doc.get("project", "Club projects"),
        "assignee_id": str(doc["assignee_id"]),
        "assignee_name": doc.get("assignee_name", ""),
        "priority": doc.get("priority", "Medium"),
        "status": doc.get("status", "Todo"),
        "due_date": doc.get("due_date"),
        "submission_note": doc.get("submission_note", ""),
        "submitted_at": doc.get("submitted_at"),
        "completion_confirmed_at": doc.get("completion_confirmed_at"),
        "completion_confirmed_by_name": doc.get("completion_confirmed_by_name"),
        "completion_confirmed_by_role": doc.get("completion_confirmed_by_role"),
        "created_by": str(doc["created_by"]),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }

async def next_member_id(role: str) -> str:
    # Atomic per-role sequence prevents concurrent registrations from reusing an ID.
    prefix = {"Founder": "TN", "Core Management": "TN-CM", "Member": "TN-M"}[role]
    counter = await db.counters.find_one_and_update(
        {"_id": f"member:{role}"},
        {"$inc": {"value": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    # ReturnDocument.AFTER is represented by True in PyMongo/Motor.
    return f"{prefix}-{counter['value']:04d}" if role != "Founder" else "TN001"

async def audit(actor: dict | None, action: str, target: str = "", details: dict | None = None, request: Request | None = None):
    await db.audit.insert_one({"actor_id": actor.get("_id") if actor else None, "actor_role": actor.get("role") if actor else None, "action": action, "target": target, "details": details or {}, "ip": request.client.host if request and request.client else None, "created_at": utcnow()})


def clean_notification(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "type": doc.get("type", "general"),
        "title": doc.get("title", "TechNova notification"),
        "message": doc.get("message", ""),
        "task_id": doc.get("task_id"),
        "common_task_id": doc.get("common_task_id"),
        "read": bool(doc.get("read_at")),
        "created_at": doc.get("created_at"),
    }


def clean_common_task(
    doc: dict,
    response_status: str | None = None,
    accepted_members: list[str] | None = None,
    completed_members: list[str] | None = None,
) -> dict:
    accepted_members = accepted_members or []
    completed_members = completed_members or []
    return {
        "id": str(doc["_id"]),
        "title": doc["title"],
        "description": doc.get("description", ""),
        "project": doc.get("project", "Club projects"),
        "priority": doc.get("priority", "Medium"),
        "due_date": doc.get("due_date"),
        "created_by_name": doc.get("created_by_name", "TechNova Management"),
        "created_at": doc.get("created_at"),
        "response_status": response_status,
        "accepted_count": len(accepted_members),
        "accepted_members": accepted_members,
        "completed_count": len(completed_members),
        "completed_members": completed_members,
    }


def _send_notification_email(recipient: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from_email
    message["To"] = recipient
    message.set_content(body)
    context = ssl.create_default_context()
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=8) as server:
        if settings.smtp_use_tls:
            server.starttls(context=context)
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)


async def create_notification(
    recipient: dict,
    title: str,
    message: str,
    notification_type: str = "general",
    task_id: str | None = None,
    common_task_id: str | None = None,
) -> None:
    await db.notifications.insert_one({
        "user_id": recipient["_id"],
        "type": notification_type,
        "title": title,
        "message": message,
        "task_id": task_id,
        "common_task_id": common_task_id,
        "read_at": None,
        "created_at": utcnow(),
    })
    # In-app delivery is always enabled. Email is an optional extra when SMTP is configured.
    if settings.smtp_host and settings.smtp_from_email and recipient.get("email"):
        try:
            await asyncio.to_thread(
                _send_notification_email,
                recipient["email"],
                title,
                message,
            )
        except Exception:
            # A mail-provider outage must never undo a saved task or in-app notification.
            pass

async def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required")
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = payload.get("sub")
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = await db.users.find_one({"_id": oid(user_id)})
    if not user or user.get("status") != "Active":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account is unavailable")
    return user

def allow(*roles: str):
    async def dependency(user: dict = Depends(get_current_user)):
        if user.get("role") not in roles:
            raise HTTPException(403, "You do not have permission to perform this action")
        return user
    return dependency

@asynccontextmanager
async def lifespan(app: FastAPI):
    await client.admin.command("ping")
    await ensure_indexes()
    # Initialize counters once from existing records so upgrades do not collide with old IDs.
    for role, key in [("Member", "member:Member"), ("Core Management", "member:Core Management")]:
        existing = await db.users.count_documents({"role": role})
        await db.counters.update_one({"_id": key}, {"$setOnInsert": {"value": existing}}, upsert=True)
    founder_email = settings.bootstrap_founder_email.lower()
    if not await db.users.find_one({"email": founder_email}):
        await db.counters.update_one({"_id":"member:Founder"},{"$set":{"value":1}},upsert=True)
        await db.users.insert_one({"member_id":"TN001","name":settings.bootstrap_founder_name,"email":founder_email,"password_hash":hash_password(settings.bootstrap_founder_password),"role":"Founder","team":"Leadership","status":"Active","created_at":utcnow(),"approved_at":utcnow()})
    # Seed initial teams idempotently.
    for name, description in [("Leadership","Club direction and planning"),("Web Development","Websites, interfaces, APIs"),("AI / ML","Applied AI and machine learning"),("Creative & Media","Design, animation, editing"),("Game Development","Game projects and prototyping")]:
        await db.teams.update_one({"name":name},{"$setOnInsert":{"name":name,"description":description,"created_at":utcnow()}},upsert=True)
    yield
    client.close()

limiter = Limiter(key_func=get_remote_address, default_limits=["300/hour"])
app = FastAPI(title="TechNova Club Portal API", version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
# Keep the deployed Render frontend explicitly allowed even if an environment
# variable is missing or contains stale origins. Add any custom domains via FRONTEND_ORIGINS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys([
        "http://localhost:5173",
        "http://localhost:8080",
        "https://technova-1-qx44.onrender.com",
        *settings.origins(),
    ])),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "ok", "service": "technova-api", "health": "/api/health"}


@app.get("/api/health")
async def health():
    return {"status":"ok","service":"technova-api"}

@app.post("/api/auth/register", status_code=201)
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

@app.post("/api/auth/login")
@limiter.limit("10/minute")
async def login(data: LoginIn, request: Request):
    user = await db.users.find_one({"email":str(data.email).lower()})
    if not user or not verify_password(data.password,user["password_hash"]):
        await audit(None,"login_failed","",{"email":str(data.email).lower()},request)
        raise HTTPException(401,"Incorrect email or password")
    if user["status"] != "Active":
        raise HTTPException(403,"Your account is pending approval or unavailable")
    token = create_access_token(str(user["_id"]),user["role"])
    await audit(user,"login",str(user["_id"]),{},request)
    return {"access_token":token,"token_type":"bearer","user":clean_user(user)}

@app.get("/api/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return clean_user(user)

@app.patch("/api/auth/profile")
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

@app.post("/api/auth/change-password")
async def change_password(body: dict, user: dict = Depends(get_current_user)):
    old = body.get("current_password",""); new = body.get("new_password","")
    if not isinstance(new,str) or len(new)<12 or len(new)>128:
        raise HTTPException(422,"New password must be 12–128 characters")
    if not verify_password(old,user["password_hash"]):
        raise HTTPException(400,"Current password is incorrect")
    await db.users.update_one({"_id":user["_id"]},{"$set":{"password_hash":hash_password(new),"password_changed_at":utcnow()}})
    await audit(user,"password_changed",str(user["_id"]))
    return {"message":"Password changed"}

@app.post("/api/auth/password-reset/request")
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

@app.post("/api/auth/password-reset/confirm")
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

@app.get("/api/dashboard")
async def dashboard(user: dict = Depends(get_current_user)):
    if user["role"] in PRIVILEGED:
        total = await db.users.count_documents({})
        active = await db.users.count_documents({"status":"Active"})
        pending = await db.users.count_documents({"status":"Pending"})
        tasks = await db.tasks.count_documents({})
        open_tasks = await db.tasks.count_documents({"status":{"$ne":"Done"}})
        done = await db.tasks.count_documents({"status":"Done"})
        recent = await db.tasks.find().sort("created_at",-1).limit(6).to_list(6)
        return {"members_total":total,"members_active":active,"members_pending":pending,"tasks_total":tasks,"tasks_open":open_tasks,"tasks_done":done,"recent_tasks":[clean_task(x) for x in recent]}
    own_tasks = await db.tasks.find({"assignee_id":user["_id"]}).sort("created_at",-1).limit(10).to_list(10)
    return {"members_total":1,"members_active":1,"members_pending":0,"tasks_total":len(own_tasks),"tasks_open":sum(x["status"]!="Done" for x in own_tasks),"tasks_done":sum(x["status"]=="Done" for x in own_tasks),"recent_tasks":[clean_task(x) for x in own_tasks]}

@app.get("/api/members")
async def list_members(q: str = "", user: dict = Depends(get_current_user)):
    if user["role"] not in PRIVILEGED:
        return [clean_user(user)]
    query = {}
    if q:
        query={"$or":[{"name":{"$regex":q,"$options":"i"}},{"email":{"$regex":q,"$options":"i"}},{"member_id":{"$regex":q,"$options":"i"}},{"team":{"$regex":q,"$options":"i"}}]}
    docs = await db.users.find(query).sort("created_at",-1).limit(500).to_list(500)
    return [clean_user(x) for x in docs]

@app.post("/api/members", status_code=201)
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

@app.patch("/api/members/{member_id}")
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

@app.post("/api/members/{member_id}/approve")
async def approve_member(member_id: str, request: Request, actor: dict = Depends(allow("Founder","Core Management"))):
    target=await db.users.find_one({"_id":oid(member_id)})
    if not target: raise HTTPException(404,"Member not found")
    if target["role"]=="Founder": raise HTTPException(403,"Invalid target")
    await db.users.update_one({"_id":target["_id"]},{"$set":{"status":"Active","approved_at":utcnow()}})
    await audit(actor,"member_approved",member_id,{},request)
    return clean_user(await db.users.find_one({"_id":target["_id"]}))

@app.delete("/api/members/{member_id}")
async def deactivate_member(member_id: str, request: Request, actor: dict = Depends(allow("Founder"))):
    target=await db.users.find_one({"_id":oid(member_id)})
    if not target: raise HTTPException(404,"Member not found")
    if target["role"]=="Founder": raise HTTPException(403,"Founder account cannot be deleted")
    await db.users.update_one({"_id":target["_id"]},{"$set":{"status":"Suspended","suspended_at":utcnow()}})
    await db.cards.update_many({"member_id":str(target["_id"]),"status":"Active"},{"$set":{"status":"Revoked","revoked_at":utcnow()}})
    await audit(actor,"member_suspended",member_id,{},request)
    return {"message":"Member suspended and active cards revoked"}

@app.get("/api/tasks")
async def list_tasks(user: dict = Depends(get_current_user)):
    query={} if user["role"] in PRIVILEGED else {"assignee_id":user["_id"]}
    docs=await db.tasks.find(query).sort("created_at",-1).limit(500).to_list(500)
    return [clean_task(x) for x in docs]


@app.get("/api/notifications")
async def list_notifications(user: dict = Depends(get_current_user)):
    docs = await db.notifications.find({"user_id": user["_id"]}).sort("created_at", -1).limit(60).to_list(60)
    return [clean_notification(x) for x in docs]


@app.post("/api/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: str, user: dict = Depends(get_current_user)):
    result = await db.notifications.update_one(
        {"_id": oid(notification_id), "user_id": user["_id"], "read_at": None},
        {"$set": {"read_at": utcnow()}},
    )
    if result.matched_count == 0:
        exists = await db.notifications.find_one({"_id": oid(notification_id), "user_id": user["_id"]})
        if not exists:
            raise HTTPException(404, "Notification not found")
    return {"message": "Notification marked as read"}


@app.get("/api/common-tasks")
async def list_common_tasks(user: dict = Depends(get_current_user)):
    docs = await db.common_tasks.find({"status": "Open"}).sort("created_at", -1).limit(200).to_list(200)
    result = []
    for doc in docs:
        response = await db.common_task_responses.find_one({
            "common_task_id": doc["_id"],
            "user_id": user["_id"],
        })
        accepted_rows = await db.common_task_responses.find({
            "common_task_id": doc["_id"],
            "response": "accepted",
        }).sort("created_at", 1).limit(500).to_list(500)
        completed_rows = await db.tasks.find({
            "common_task_id": doc["_id"],
            "status": "Done",
        }).sort("updated_at", 1).limit(500).to_list(500)
        accepted_names = [row.get("user_name", "Member") for row in accepted_rows]
        completed_names = [row.get("assignee_name", "Member") for row in completed_rows]
        result.append(clean_common_task(
            doc,
            response.get("response") if response else None,
            accepted_names,
            completed_names,
        ))
    return result


@app.get("/api/tasks/review-queue")
async def task_review_queue(actor: dict = Depends(allow("Founder", "Core Management"))):
    query = {"status": "Review"}
    if actor.get("role") == "Core Management":
        eligible = await db.users.find({
            "role": "Member",
            "status": "Active",
        }).to_list(1000)
        eligible_ids = [member["_id"] for member in eligible]
        if not eligible_ids:
            return []
        query["assignee_id"] = {"$in": eligible_ids}

    docs = await db.tasks.find(query).sort("submitted_at", 1).limit(500).to_list(500)
    if not docs:
        return []
    member_ids = list({doc["assignee_id"] for doc in docs})
    members = await db.users.find({"_id": {"$in": member_ids}}).to_list(500)
    member_by_id = {member["_id"]: member for member in members}
    result = []
    for doc in docs:
        member = member_by_id.get(doc["assignee_id"], {})
        task = clean_task(doc)
        task["assignee_member_id"] = member.get("member_id", "")
        task["assignee_team"] = member.get("team", "Unassigned")
        files = await db.attachments.find({"task_id": doc["_id"]}).sort("created_at", -1).limit(20).to_list(20)
        task["attachments"] = [
            {"id": str(item["_id"]), "filename": item["filename"], "size": item["size"]}
            for item in files
        ]
        task["attachments_count"] = await db.attachments.count_documents({"task_id": doc["_id"]})
        result.append(task)
    return result


@app.post("/api/tasks/bulk-confirm")
async def bulk_confirm_task_completion(
    data: TaskBulkConfirm,
    request: Request,
    actor: dict = Depends(allow("Founder", "Core Management")),
):
    unique_ids = list(dict.fromkeys(data.task_ids))
    if len(unique_ids) != len(data.task_ids):
        raise HTTPException(422, "Remove duplicate task selections before approval")
    try:
        object_ids = [oid(value) for value in unique_ids]
    except HTTPException:
        raise HTTPException(422, "One or more task IDs are invalid")

    tasks = await db.tasks.find({
        "_id": {"$in": object_ids},
        "status": "Review",
    }).to_list(100)
    if len(tasks) != len(object_ids):
        raise HTTPException(409, "Some selected tasks are no longer awaiting review. Refresh the queue and try again.")

    assignee_ids = list({task["assignee_id"] for task in tasks})
    members = await db.users.find({"_id": {"$in": assignee_ids}}).to_list(100)
    member_by_id = {member["_id"]: member for member in members}
    for task in tasks:
        member = member_by_id.get(task["assignee_id"])
        if not member:
            raise HTTPException(409, "A task assignee no longer exists")
        if actor.get("role") == "Core Management" and member.get("role") != "Member":
            raise HTTPException(403, "Core Management can approve Member submissions only")

    now = utcnow()
    approved = []
    for task in tasks:
        result = await db.tasks.update_one(
            {"_id": task["_id"], "status": "Review"},
            {"$set": {
                "status": "Done",
                "completion_confirmed_at": now,
                "completion_confirmed_by": actor["_id"],
                "completion_confirmed_by_name": actor["name"],
                "completion_confirmed_by_role": actor["role"],
                "updated_at": now,
            }},
        )
        if result.modified_count:
            member = member_by_id[task["assignee_id"]]
            approved.append(str(task["_id"]))
            await create_notification(
                member,
                "Task completion approved",
                f'{actor["name"]} approved your submission for "{task["title"]}".',
                "task_approved",
                task_id=str(task["_id"]),
            )

    await audit(actor, "tasks_bulk_completion_confirmed", ",".join(approved), {
        "requested_count": len(object_ids),
        "approved_count": len(approved),
        "task_ids": approved,
    }, request)
    return {
        "approved_count": len(approved),
        "message": f"{len(approved)} task submission(s) approved",
        "task_ids": approved,
    }


@app.get("/api/tasks/pending-confirmation")
async def pending_completion_tasks(member_id: str, actor: dict = Depends(allow("Founder", "Core Management"))):
    """List tasks submitted for QR-gated completion by the scanned member."""
    member = await db.users.find_one({"member_id": member_id, "status": "Active"})
    if not member:
        raise HTTPException(404, "Active member not found")
    if actor.get("role") == "Core Management" and member.get("role") != "Member":
        raise HTTPException(403, "Core Management can confirm Member task submissions only")
    docs = await db.tasks.find({
        "assignee_id": member["_id"],
        "status": "Review",
    }).sort("submitted_at", 1).limit(100).to_list(100)
    result = []
    for doc in docs:
        task = clean_task(doc)
        task["assignee_member_id"] = member["member_id"]
        task["assignee_team"] = member.get("team", "Unassigned")
        result.append(task)
    return result


def can_assign_task(actor: dict, target: dict) -> bool:
    # Founder can assign to Core Management and Members. Core Management can assign only to Members.
    if actor.get("role") == "Founder":
        return target.get("role") in {"Core Management", "Member"}
    if actor.get("role") == "Core Management":
        return target.get("role") == "Member"
    return False


@app.post("/api/tasks", status_code=201)
async def create_task(data: TaskCreate, request: Request, actor: dict = Depends(allow("Founder", "Core Management"))):
    now = utcnow()
    base = {
        "title": data.title.strip(),
        "description": data.description.strip(),
        "project": data.project.strip() or "Club projects",
        "priority": data.priority,
        "due_date": data.due_date,
        "created_by": actor["_id"],
        "created_by_name": actor["name"],
        "created_at": now,
        "updated_at": now,
    }

    if data.assignment_mode == "open_to_all":
        common_doc = {
            **base,
            "status": "Open",
        }
        result = await db.common_tasks.insert_one(common_doc)
        common_doc["_id"] = result.inserted_id
        active_members = await db.users.find({
            "role": "Member",
            "status": "Active",
        }).to_list(500)
        for member in active_members:
            await create_notification(
                member,
                "New common task available",
                f'{actor["name"]} posted "{common_doc["title"]}". Open Tasks & Projects to accept or decline it.',
                "common_task",
                common_task_id=str(result.inserted_id),
            )
        await audit(actor, "common_task_created", str(result.inserted_id), {
            "notified_members": len(active_members),
        }, request)
        return clean_common_task(common_doc, None, [], [])

    raw_ids = data.assignee_ids or ([data.assignee_id] if data.assignee_id else [])
    if data.assignment_mode == "individual" and data.assignee_id:
        raw_ids = [data.assignee_id]
    assignee_ids = list(dict.fromkeys(raw_ids))
    if not assignee_ids:
        raise HTTPException(422, "Choose at least one active assignee")
    if len(assignee_ids) > 100:
        raise HTTPException(422, "A task can be assigned to at most 100 members")

    try:
        requested_ids = [oid(value) for value in assignee_ids]
    except HTTPException:
        raise HTTPException(422, "One or more assignee IDs are invalid")
    targets = await db.users.find({
        "_id": {"$in": requested_ids},
        "status": "Active",
    }).to_list(100)
    if len(targets) != len(requested_ids):
        raise HTTPException(400, "Every selected assignee must be an active member")
    if any(not can_assign_task(actor, target) for target in targets):
        raise HTTPException(403, "Founder can assign to Core Management or Members; Core Management can assign only to Members")

    group_id = str(ObjectId()) if len(targets) > 1 else None
    created = []
    for target in targets:
        doc = {
            **base,
            "assignee_id": target["_id"],
            "assignee_name": target["name"],
            "status": "Todo",
            "submission_note": "",
            "assignment_group_id": group_id,
        }
        result = await db.tasks.insert_one(doc)
        doc["_id"] = result.inserted_id
        created.append(clean_task(doc))
        due_text = f' Due date: {data.due_date}.' if data.due_date else ""
        await create_notification(
            target,
            "New task assigned to you",
            f'{actor["name"]} assigned you "{data.title.strip()}". Project: {base["project"]}.{due_text}',
            "task_assigned",
            task_id=str(result.inserted_id),
        )
    await audit(actor, "task_created", group_id or created[0]["id"], {
        "assignee_ids": [str(target["_id"]) for target in targets],
        "task_count": len(created),
        "assignment_group_id": group_id,
    }, request)
    if len(created) == 1:
        return created[0]
    return {"count": len(created), "assignment_group_id": group_id, "tasks": created}


@app.post("/api/common-tasks/{common_task_id}/respond")
async def respond_to_common_task(common_task_id: str, body: dict, request: Request, user: dict = Depends(get_current_user)):
    if user.get("role") != "Member":
        raise HTTPException(403, "Only active Members can accept or decline common tasks")
    response = body.get("response")
    if response not in {"accepted", "declined"}:
        raise HTTPException(422, "Response must be accepted or declined")
    common = await db.common_tasks.find_one({
        "_id": oid(common_task_id),
        "status": "Open",
    })
    if not common:
        raise HTTPException(404, "Common task is no longer available")
    previous = await db.common_task_responses.find_one({
        "common_task_id": common["_id"],
        "user_id": user["_id"],
    })
    if previous:
        raise HTTPException(409, "You have already responded to this common task")

    personal_task = None
    if response == "accepted":
        task_doc = {
            "title": common["title"],
            "description": common.get("description", ""),
            "project": common.get("project", "Club projects"),
            "assignee_id": user["_id"],
            "assignee_name": user["name"],
            "priority": common.get("priority", "Medium"),
            "status": "Todo",
            "due_date": common.get("due_date"),
            "submission_note": "",
            "created_by": common["created_by"],
            "created_by_name": common.get("created_by_name", "TechNova Management"),
            "created_at": utcnow(),
            "updated_at": utcnow(),
            "common_task_id": common["_id"],
        }
        personal_task = await db.tasks.find_one_and_update(
            {"common_task_id": common["_id"], "assignee_id": user["_id"]},
            {"$setOnInsert": task_doc},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    try:
        await db.common_task_responses.insert_one({
            "common_task_id": common["_id"],
            "user_id": user["_id"],
            "user_name": user["name"],
            "response": response,
            "task_id": personal_task["_id"] if personal_task else None,
            "created_at": utcnow(),
        })
    except DuplicateKeyError:
        raise HTTPException(409, "You have already responded to this common task")

    creator = await db.users.find_one({"_id": common["created_by"], "status": "Active"})
    if creator:
        await create_notification(
            creator,
            f'Common task {response}',
            f'{user["name"]} {response} "{common["title"]}".',
            "common_task_response",
            task_id=str(personal_task["_id"]) if personal_task else None,
            common_task_id=common_task_id,
        )
    await audit(user, "common_task_responded", common_task_id, {"response": response}, request)
    return {
        "message": "You accepted the task. It is now in your task list." if response == "accepted" else "You declined this common task.",
        "response": response,
        "task_id": str(personal_task["_id"]) if personal_task else None,
    }

@app.patch("/api/tasks/{task_id}")
async def update_task(task_id: str, data: TaskPatch, request: Request, actor: dict = Depends(get_current_user)):
    target=await db.tasks.find_one({"_id":oid(task_id)})
    if not target: raise HTTPException(404,"Task not found")
    privileged=actor["role"] in PRIVILEGED
    if not privileged and target["assignee_id"]!=actor["_id"]: raise HTTPException(403,"You can only update tasks assigned to you")
    changes=data.model_dump(exclude_unset=True,exclude_none=True)
    if not privileged and set(changes)-{"status","submission_note"}: raise HTTPException(403,"Members may only update task status and submission note")
    if not privileged and changes.get("status") not in {None,"Todo","In progress","Review"}:
        raise HTTPException(403, "Members must submit tasks for review; completion requires a staff QR confirmation")
    if changes.get("status") == "Done":
        raise HTTPException(403, "Tasks can only be marked Done by confirming completion after scanning the assignee's QR")
    if changes.get("status") == "Review":
        changes["submitted_at"] = utcnow()
        changes["submitted_by"] = actor["_id"]
        changes["completion_confirmed_at"] = None
        changes["completion_confirmed_by"] = None
        changes["completion_confirmed_by_name"] = None
        changes["completion_confirmed_by_role"] = None
    elif changes.get("status") == "In progress":
        changes["submitted_at"] = None
        changes["submitted_by"] = None
    reassigned_to = None
    if privileged and "assignee_id" in changes:
        assignee=await db.users.find_one({"_id":oid(changes["assignee_id"])})
        if not assignee or assignee["status"]!="Active": raise HTTPException(400,"Assignee must be active")
        if not can_assign_task(actor, assignee):
            raise HTTPException(403, "You cannot assign tasks to this role")
        changes["assignee_id"]=assignee["_id"]; changes["assignee_name"]=assignee["name"]
        reassigned_to = assignee
    changes["updated_at"]=utcnow()
    await db.tasks.update_one({"_id":target["_id"]},{"$set":changes})
    if reassigned_to:
        await create_notification(
            reassigned_to,
            "Task assigned to you",
            f'{actor["name"]} assigned you "{target["title"]}".',
            "task_assigned",
            task_id=task_id,
        )
    if changes.get("status") == "Review":
        staff_roles = ["Founder"] if actor.get("role") == "Core Management" else ["Founder", "Core Management"]
        reviewers = await db.users.find({
            "role": {"$in": staff_roles},
            "status": "Active",
            "_id": {"$ne": actor["_id"]},
        }).to_list(200)
        for reviewer in reviewers:
            await create_notification(
                reviewer,
                "Task submission awaiting review",
                f'{actor["name"]} submitted "{target["title"]}" for completion approval.',
                "task_review",
                task_id=task_id,
            )
    await audit(actor,"task_updated",task_id,{"fields":list(changes)},request)
    return clean_task(await db.tasks.find_one({"_id":target["_id"]}))

@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str, request: Request, actor: dict = Depends(allow("Founder","Core Management"))):
    res=await db.tasks.delete_one({"_id":oid(task_id)})
    if not res.deleted_count: raise HTTPException(404,"Task not found")
    await audit(actor,"task_deleted",task_id,{},request)
    return {"message":"Task deleted"}

@app.post("/api/tasks/{task_id}/attachments", status_code=201)
async def upload_task_attachment(task_id: str, request: Request, file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    task = await db.tasks.find_one({"_id": oid(task_id)})
    if not task:
        raise HTTPException(404, "Task not found")
    if user["role"] not in PRIVILEGED and task["assignee_id"] != user["_id"]:
        raise HTTPException(403, "You cannot upload to this task")
    allowed = {"image/png", "image/jpeg", "image/webp", "application/pdf", "text/plain", "application/zip"}
    if file.content_type not in allowed:
        raise HTTPException(415, "Allowed files: PNG, JPEG, WEBP, PDF, TXT, ZIP")
    data = await file.read(10 * 1024 * 1024 + 1)
    if not data or len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "Attachment must be under 10 MB")
    import uuid
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", file.filename or "attachment")[:120]
    stored = f"{uuid.uuid4().hex}_{safe_name}"
    os.makedirs("/app/uploads", exist_ok=True)
    with open(os.path.join("/app/uploads", stored), "wb") as handle:
        handle.write(data)
    doc = {"task_id": task["_id"], "filename": safe_name, "stored_name": stored, "content_type": file.content_type, "size": len(data), "uploaded_by": user["_id"], "created_at": utcnow()}
    result = await db.attachments.insert_one(doc)
    await audit(user, "task_attachment_uploaded", str(result.inserted_id), {}, request)
    return {"id": str(result.inserted_id), "filename": safe_name, "content_type": file.content_type, "size": len(data)}

@app.get("/api/tasks/{task_id}/attachments")
async def list_task_attachments(task_id: str, user: dict = Depends(get_current_user)):
    task = await db.tasks.find_one({"_id": oid(task_id)})
    if not task:
        raise HTTPException(404, "Task not found")
    if user["role"] not in PRIVILEGED and task["assignee_id"] != user["_id"]:
        raise HTTPException(403, "You cannot view attachments for this task")
    rows = await db.attachments.find({"task_id": task["_id"]}).sort("created_at", -1).to_list(100)
    return [{"id":str(x["_id"]), "filename":x["filename"], "content_type":x["content_type"], "size":x["size"], "created_at":x["created_at"]} for x in rows]

@app.get("/api/attachments/{attachment_id}/download")
async def download_attachment(attachment_id: str, user: dict = Depends(get_current_user)):
    item = await db.attachments.find_one({"_id": oid(attachment_id)})
    if not item:
        raise HTTPException(404, "Attachment not found")
    task = await db.tasks.find_one({"_id": item["task_id"]})
    if not task or (user["role"] not in PRIVILEGED and task["assignee_id"] != user["_id"]):
        raise HTTPException(403, "You cannot download this attachment")
    path = os.path.join("/app/uploads", item["stored_name"])
    if not os.path.isfile(path):
        raise HTTPException(404, "Attachment file is missing")
    return FileResponse(path, media_type=item["content_type"], filename=item["filename"])

@app.get("/api/tasks/{task_id}/comments")
async def get_task_comments(task_id: str, user: dict = Depends(get_current_user)):
    task = await db.tasks.find_one({"_id": oid(task_id)})
    if not task:
        raise HTTPException(404, "Task not found")
    if user["role"] not in PRIVILEGED and task["assignee_id"] != user["_id"]:
        raise HTTPException(403, "You cannot view comments for this task")
    rows = await db.task_comments.find({"task_id": task["_id"]}).sort("created_at", 1).to_list(300)
    return [{"id": str(x["_id"]), "author": x["author"], "role": x["role"], "text": x["text"], "created_at": x["created_at"]} for x in rows]

@app.post("/api/tasks/{task_id}/comments", status_code=201)
async def add_task_comment(task_id: str, body: dict, request: Request, user: dict = Depends(get_current_user)):
    task = await db.tasks.find_one({"_id": oid(task_id)})
    if not task:
        raise HTTPException(404, "Task not found")
    if user["role"] not in PRIVILEGED and task["assignee_id"] != user["_id"]:
        raise HTTPException(403, "You cannot comment on this task")
    text = body.get("text", "")
    if not isinstance(text, str) or not text.strip() or len(text) > 2000:
        raise HTTPException(422, "Comment must be 1–2000 characters")
    doc = {"task_id": task["_id"], "author_id": user["_id"], "author": user["name"], "role": user["role"], "text": text.strip(), "created_at": utcnow()}
    result = await db.task_comments.insert_one(doc)
    await audit(user, "task_comment_added", task_id, {}, request)
    return {"id": str(result.inserted_id), "author": doc["author"], "role": doc["role"], "text": doc["text"], "created_at": doc["created_at"]}

@app.get("/api/teams")
async def list_teams(user: dict = Depends(get_current_user)):
    docs=await db.teams.find().sort("name",1).to_list(200)
    return [{"id":str(x["_id"]),"name":x["name"],"description":x.get("description","")} for x in docs]

@app.post("/api/teams",status_code=201)
async def create_team(data: TeamCreate, request: Request, actor: dict = Depends(allow("Founder","Core Management"))):
    try: res=await db.teams.insert_one({"name":data.name.strip(),"description":data.description,"created_at":utcnow()})
    except DuplicateKeyError: raise HTTPException(409,"Team already exists")
    await audit(actor,"team_created",str(res.inserted_id),{"name":data.name},request)
    return {"id":str(res.inserted_id),"name":data.name,"description":data.description}

def signed_card_token(member_key: str, card_id: ObjectId) -> str:
    """Create a reproducible signed QR token without storing the raw token."""
    card_key = str(card_id)
    payload = f"technova-card-v2:{member_key}:{card_key}".encode("utf-8")
    signature = hmac.new(settings.jwt_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"{card_key}.{signature}"


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


@app.post("/api/cards/me/issue")
async def issue_own_card(request: Request, actor: dict = Depends(get_current_user)):
    """Return the signed-in user's stable QR card, creating it only if necessary."""
    if actor.get("status") != "Active":
        raise HTTPException(403, "Only active members can issue a digital ID")
    return await mint_card(actor, actor, request, reuse_active=True, action="card_self_issued")


@app.post("/api/cards/{member_id}/issue")
async def issue_card(member_id: str, request: Request, actor: dict = Depends(allow("Founder"))):
    target = await db.users.find_one({"_id": oid(member_id)})
    if not target:
        raise HTTPException(404, "Member not found")
    return await mint_card(target, actor, request, reuse_active=False, action="card_issued")


@app.post("/api/cards/{member_id}/revoke")
async def revoke_card(member_id: str, request: Request, actor: dict = Depends(allow("Founder"))):
    target=await db.users.find_one({"_id":oid(member_id)})
    if not target: raise HTTPException(404,"Member not found")
    await db.cards.update_many({"member_id":str(target["_id"]),"status":"Active"},{"$set":{"status":"Revoked","revoked_at":utcnow()}})
    await audit(actor,"card_revoked",member_id,{},request)
    return {"message":"Active cards revoked"}

@app.get("/api/verify/{token}")
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
    return {"valid": True, "status": "Active", "name": member["name"], "member_id": member["member_id"], "role": member["role"], "team": member.get("team", "Unassigned"), "club": "TechNova"}

@app.post("/api/verify/{token}/confirm")
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

@app.post("/api/tasks/{task_id}/confirm-completion")
async def confirm_task_completion(task_id: str, data: TaskCompletionConfirm, request: Request, actor: dict = Depends(allow("Founder", "Core Management"))):
    """Confirm a Review task only when the assigned person's active QR is scanned."""
    task = await db.tasks.find_one({"_id": oid(task_id)})
    if not task:
        raise HTTPException(404, "Task not found")
    if task.get("status") != "Review":
        raise HTTPException(409, "This task is not awaiting completion confirmation")

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


@app.get("/api/audit")
async def list_audit(limit: int = 50, user: dict = Depends(allow("Founder"))):
    limit=max(1,min(limit,200))
    docs=await db.audit.find().sort("created_at",-1).limit(limit).to_list(limit)
    return [{"id":str(x["_id"]),"actor_role":x.get("actor_role"),"action":x["action"],"target":x.get("target"),"created_at":x.get("created_at"),"details":x.get("details",{})} for x in docs]

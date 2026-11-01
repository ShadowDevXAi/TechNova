"""Shared backend services, authorization helpers and application lifecycle.

Route modules import the database, settings and business helpers from this module.
Keep HTTP route declarations in app/routes/ so each feature remains easy to find.
"""

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
import math
import json
import random
from secrets import token_urlsafe
import urllib.request
import urllib.error
from zoneinfo import ZoneInfo
from datetime import timedelta
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pymongo.errors import DuplicateKeyError
from pymongo import ReturnDocument
from motor.motor_asyncio import AsyncIOMotorDatabase
from .config import settings
from .db import client, db, ensure_indexes
from .firebase_push import send_push_notification
from .security import hash_password, verify_password, create_access_token, decode_access_token, new_card_token, token_hash, utcnow
from .models import RegisterIn, LoginIn, MemberCreate, MemberPatch, TaskCreate, TaskPatch, TaskBulkConfirm, TaskCompletionConfirm, TeamCreate, AnnouncementCreate, MemberSuspendIn, TaskStateIn

bearer = HTTPBearer(auto_error=False)
PRIVILEGED = {"Founder", "Core Management"}
ALL_ROLES = {"Founder", "Core Management", "Faculty", "Member"}

# Credits are awarded only when staff approves a Review submission.
TASK_CREDIT_VALUES = {"F": 5, "E": 10, "D": 20, "C": 35, "B": 55, "A": 85, "S": 125, "SS": 175, "SSS": 250}
MEMBER_RANK_THRESHOLDS = [
    ("SSS", 1800), ("SS", 1200), ("S", 800), ("A", 500),
    ("B", 300), ("C", 150), ("D", 75), ("E", 25), ("F", 0),
]

# Purpose: Return the credit reward configured for a task difficulty rank.
def task_credit_value(task: dict) -> int:
    return TASK_CREDIT_VALUES.get(task.get("difficulty_rank", "F"), TASK_CREDIT_VALUES["F"])

# Purpose: Convert a member's current credit balance into the displayed club rank.
def member_rank(credits: int) -> str:
    # Negative balances are valid after penalties; F is the minimum rank.
    return next((rank for rank, threshold in MEMBER_RANK_THRESHOLDS if credits >= threshold), "F")

# Purpose: Validate a MongoDB ID string and convert it into an ObjectId.
def oid(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(400, "Invalid record ID")
    return ObjectId(value)

# Purpose: Remove private database fields and build the public member response.
def clean_user(doc: dict) -> dict:
    return {"id": str(doc["_id"]), "member_id": doc["member_id"], "name": doc["name"], "email": doc["email"], "role": doc["role"], "team": doc.get("team","Unassigned"), "status": doc["status"], "created_at": doc.get("created_at"), "suspension_until": doc.get("suspension_until"), "suspension_reason": doc.get("suspension_reason"), "suspension_temporary": bool(doc.get("suspension_temporary", False))}

# Purpose: Convert a stored task document into the API's stable task response shape.
def clean_task(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "assignment_group_id": (
            str(doc.get("assignment_group_id"))
            if doc.get("assignment_group_id") is not None else None
        ),
        # Older/imported task rows may not contain all fields from the current schema.
        # Keep one incomplete legacy row from breaking the entire /api/tasks response.
        "title": doc.get("title") or "Untitled task",
        "description": doc.get("description", ""),
        "project": doc.get("project", "Club projects"),
        "assignee_id": str(doc.get("assignee_id") or ""),
        "assignee_name": doc.get("assignee_name", ""),
        "priority": doc.get("priority", "Medium"),
        "difficulty_rank": doc.get("difficulty_rank", "F"),
        "programming_language": doc.get("programming_language", "General"),
        "credits_reward": doc.get("credits_reward", TASK_CREDIT_VALUES["F"]),
        "credits_awarded": doc.get("credits_awarded", 0),
        "late_penalty_points": doc.get("late_penalty_points", 0),
        "task_state": doc.get("task_state", "Active"),
        "task_state_reason": doc.get("task_state_reason", ""),
        "recurrence": doc.get("recurrence", "once"),
        "status": doc.get("status", "Todo"),
        "due_date": doc.get("due_date"),
        "submission_note": doc.get("submission_note", ""),
        "submission_evidence_url": doc.get("submission_evidence_url", ""),
        "project_url": doc.get("project_url", ""),
        "submission_attested": bool(doc.get("submission_attested", False)),
        "review_feedback": doc.get("review_feedback", ""),
        "submitted_at": doc.get("submitted_at"),
        "completion_confirmed_at": doc.get("completion_confirmed_at"),
        "completion_confirmed_by_name": doc.get("completion_confirmed_by_name"),
        "completion_confirmed_by_role": doc.get("completion_confirmed_by_role"),
        "created_by": str(doc.get("created_by") or ""),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        "auto_generated": bool(doc.get("auto_generated", False)),
        "generation_source": doc.get("generation_source", ""),
    }

# Purpose: Generate the next unique club member ID using an atomic database counter.
async def next_member_id(role: str) -> str:
    # Atomic per-role sequence prevents concurrent registrations from reusing an ID.
    prefix = {"Founder": "TN", "Core Management": "TN-CM", "Faculty": "TN-FAC", "Member": "TN-M"}[role]
    counter = await db.counters.find_one_and_update(
        {"_id": f"member:{role}"},
        {"$inc": {"value": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    # ReturnDocument.AFTER is represented by True in PyMongo/Motor.
    return f"{prefix}-{counter['value']:04d}" if role != "Founder" else "TN001"

# Purpose: Write a security/audit event with actor, target, request IP and details.
async def audit(actor: dict | None, action: str, target: str = "", details: dict | None = None, request: Request | None = None):
    await db.audit.insert_one({"actor_id": actor.get("_id") if actor else None, "actor_role": actor.get("role") if actor else None, "action": action, "target": target, "details": details or {}, "ip": request.client.host if request and request.client else None, "created_at": utcnow()})


# Purpose: Convert a stored notification into the response shown in the member inbox.
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


# Purpose: Format a shared task and calculate acceptance/completion counts.
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
        "title": doc.get("title") or "Untitled mission",
        "description": doc.get("description", ""),
        "project": doc.get("project", "Club projects"),
        "priority": doc.get("priority", "Medium"),
        "difficulty_rank": doc.get("difficulty_rank", "F"),
        "programming_language": doc.get("programming_language", "General"),
        "credits_reward": doc.get("credits_reward", TASK_CREDIT_VALUES["F"]),
        "task_state": doc.get("task_state", "Active"),
        "recurrence": doc.get("recurrence", "once"),
        "due_date": doc.get("due_date"),
        "created_by_name": doc.get("created_by_name", "TechNova Management"),
        "auto_generated": bool(doc.get("auto_generated", False)),
        "generation_source": doc.get("generation_source"),
        "created_at": doc.get("created_at"),
        "response_status": response_status,
        "accepted_count": len(accepted_members),
        "accepted_members": accepted_members,
        "completed_count": len(completed_members),
        "completed_members": completed_members,
    }


# Purpose: Send an optional SMTP email notification in a worker thread.
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


# Purpose: Save an in-app notification and send email when SMTP is configured.
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
    # Push delivery is optional and isolated: a Firebase outage never breaks the portal action.
    await send_push_notification(
        recipient["_id"], title, message,
        notification_type=notification_type,
        task_id=task_id,
        common_task_id=common_task_id,
    )

# Purpose: Validate the bearer token, load the active member and expire timed suspensions.
async def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in required")
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = payload.get("sub")
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = await db.users.find_one({"_id": oid(user_id)})
    if user and user.get("status") == "Suspended" and user.get("suspension_temporary") and user.get("suspension_until") and user["suspension_until"] <= utcnow():
        await db.users.update_one({"_id": user["_id"], "status": "Suspended"}, {"$set": {"status": "Active", "suspension_until": None, "suspension_temporary": False, "suspension_expired_at": utcnow()}})
        user = await db.users.find_one({"_id": user["_id"]})
        await resume_member_paused_tasks(user["_id"], utcnow())
    if not user or user.get("status") != "Active":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account is unavailable")
    return user

# Purpose: Create a reusable FastAPI role-check dependency for protected endpoints.
def allow(*roles: str):
    async def dependency(user: dict = Depends(get_current_user)):
        if user.get("role") not in roles:
            raise HTTPException(403, "You do not have permission to perform this action")
        return user
    return dependency



# Purpose: Calculate earned credits minus recorded penalties for one member.
async def member_credit_balance(member_id: ObjectId) -> int:
    earned_rows = await db.tasks.aggregate([
        {"$match": {"assignee_id": member_id, "status": "Done", "credits_awarded": {"$gt": 0}}},
        {"$group": {"_id": None, "earned": {"$sum": "$credits_awarded"}}},
    ]).to_list(length=1)
    penalty_rows = await db.credit_penalties.aggregate([
        {"$match": {"user_id": member_id}},
        {"$group": {"_id": None, "penalties": {"$sum": "$points"}}},
    ]).to_list(length=1)
    earned = int(earned_rows[0].get("earned", 0)) if earned_rows else 0
    penalties = int(penalty_rows[0].get("penalties", 0)) if penalty_rows else 0
    # Negative balances are intentional: penalties are not silently capped at zero.
    return earned - penalties


# XP progression is separate from the letter-based task-credit rank.
# The title changes at each level; square thresholds keep progression open-ended.
LEVEL_TITLES = (
    "Newcomer", "Learner", "Contributor", "Builder", "Developer", "Engineer",
    "Innovator", "Specialist", "Architect", "Master Developer", "TechNova Legend",
)


# Purpose: Calculate a member's level, title and progress to the next level.
def member_level_details(xp: int) -> dict:
    """Return the open-ended XP level and its progress bar values.

    Level 1 starts at 0 XP. Further levels begin at 100, 400, 900, 1600 XP,
    and so on. Credits are calculated separately and never determine this level.
    """
    xp = max(0, int(xp or 0))
    level = math.isqrt(xp // 100) + 1
    level_start_xp = (level - 1) ** 2 * 100
    next_level_xp = level ** 2 * 100
    if level <= len(LEVEL_TITLES):
        level_title = LEVEL_TITLES[level - 1]
    else:
        level_title = f"TechNova Legend · Tier {level - len(LEVEL_TITLES) + 1}"
    span = max(1, next_level_xp - level_start_xp)
    progress = min(100.0, max(0.0, (xp - level_start_xp) * 100.0 / span))
    return {
        "level": level,
        "level_title": level_title,
        "level_start_xp": level_start_xp,
        "next_level_xp": next_level_xp,
        "xp_to_next_level": max(0, next_level_xp - xp),
        "level_progress": round(progress, 1),
    }


# Purpose: Build one consistent XP and credit snapshot for a member profile or ID card.
def founder_progression_details(completed: int, pending: int, credits: int) -> dict:
    """Return the Founder's permanent identity without XP-based rank progression."""
    return {
        "progression_type": "founder",
        "xp": None,
        "level": None,
        "level_title": "Founder · Origin Rank",
        "level_start_xp": None,
        "next_level_xp": None,
        "xp_to_next_level": None,
        "level_progress": None,
        "completed_tasks": completed,
        "pending_reviews": pending,
        "credits": credits,
        "credit_rank": "N/A",
        "xp_approved": None,
        "xp_pending_review": None,
    }


# Purpose: Build one consistent XP and credit snapshot for a member profile or ID card.
async def member_progress_summary(member_id: ObjectId) -> dict:
    """Return permanent Founder identity or normal XP progression for other roles."""
    member = await db.users.find_one({"_id": member_id}, {"role": 1})
    completed = await db.tasks.count_documents({"assignee_id": member_id, "status": "Done"})
    pending = await db.tasks.count_documents({"assignee_id": member_id, "status": "Review"})
    credits = await member_credit_balance(member_id)

    # Founder status is assigned by role and never earned, lost or upgraded through XP.
    if member and member.get("role") == "Founder":
        return founder_progression_details(completed, pending, credits)

    xp = completed * 100 + pending * 25
    return {
        "progression_type": "xp",
        "xp": xp,
        **member_level_details(xp),
        "completed_tasks": completed,
        "pending_reviews": pending,
        "credits": credits,
        "credit_rank": member_rank(credits),
        "xp_approved": completed * 100,
        "xp_pending_review": pending * 25,
    }


# Purpose: Resume tasks paused during a temporary suspension and extend due dates.
async def resume_member_paused_tasks(member_id: ObjectId, now: datetime) -> None:
    paused = await db.tasks.find({
        "assignee_id": member_id, "task_state": "Suspended",
        "suspension_pause_by_member": True, "deleted_at": {"$exists": False},
    }).to_list(500)
    for task in paused:
        changes = {"task_state": "Active", "task_state_reason": "", "paused_at": None,
                   "suspension_pause_by_member": False, "updated_at": now}
        if task.get("paused_at") and task.get("due_date"):
            paused_days = max(1, math.ceil((now - task["paused_at"]).total_seconds() / 86400))
            try:
                changes["due_date"] = (datetime.fromisoformat(task["due_date"]).date() + timedelta(days=paused_days)).isoformat()
            except ValueError:
                pass
        await db.tasks.update_one({"_id": task["_id"], "task_state": "Suspended"}, {"$set": changes})


# Curated fallback pool: used whenever Gemini is not configured or unavailable.
AUTO_TASK_BANK = [
    {"title":"C Program: Student Marks Calculator","description":"Read marks for three subjects, calculate the total and percentage, and print pass/fail using a clear condition. Validate that marks are between 0 and 100.","programming_language":"C","complexity":1,"estimated_minutes":25},
    {"title":"C Program: Even or Odd Checker","description":"Read an integer and determine whether it is even or odd. Handle zero and negative values correctly.","programming_language":"C","complexity":1,"estimated_minutes":15},
    {"title":"C Program: Multiplication Table","description":"Read an integer and print its multiplication table from 1 to 10 using a loop.","programming_language":"C","complexity":1,"estimated_minutes":20},
    {"title":"C Program: Simple Calculator","description":"Build a menu-driven calculator for addition, subtraction, multiplication and division. Prevent division by zero.","programming_language":"C","complexity":2,"estimated_minutes":40},
    {"title":"C++: Student Record Structure","description":"Create a Student structure or class with name, roll number and marks. Read and display records for at least three students.","programming_language":"C++","complexity":3,"estimated_minutes":60},
    {"title":"Python: Word Frequency Counter","description":"Accept a sentence or text and count how many times each word occurs. Ignore letter case and display the most frequent word.","programming_language":"Python","complexity":3,"estimated_minutes":45},
    {"title":"Python: Expense Tracker","description":"Create a command-line expense tracker that stores descriptions and amounts, lists entries and calculates the total expense. Validate numeric input.","programming_language":"Python","complexity":4,"estimated_minutes":90},
    {"title":"HTML/CSS: Responsive Profile Card","description":"Build a responsive profile card with an avatar, name, role, short bio and contact links. Use semantic HTML and a mobile-friendly layout.","programming_language":"HTML/CSS","complexity":2,"estimated_minutes":60},
    {"title":"JavaScript: Interactive To-do List","description":"Create a to-do list that can add, complete and delete tasks. Keep the interface usable on mobile and prevent empty task entries.","programming_language":"JavaScript","complexity":4,"estimated_minutes":90},
    {"title":"JavaScript: Form Validation","description":"Build a registration form and validate required fields, email format and password length. Show clear inline error messages without reloading the page.","programming_language":"JavaScript","complexity":4,"estimated_minutes":75},
    {"title":"React: Task Dashboard","description":"Build a small React dashboard that adds, filters and completes tasks. Use component state and show an empty state when there are no tasks.","programming_language":"React","complexity":5,"estimated_minutes":150},
    {"title":"MongoDB: CRUD Practice API","description":"Create a small FastAPI service with MongoDB operations to create, list, update and delete simple project records. Validate input and handle missing records.","programming_language":"FastAPI / MongoDB","complexity":6,"estimated_minutes":210},
    {"title":"Godot: Player Movement Prototype","description":"Create a 2D Godot scene with a player that moves in four directions, collides with walls and has a camera that follows the player.","programming_language":"Godot / GDScript","complexity":5,"estimated_minutes":150},
    {"title":"C++: Inventory Manager","description":"Create a console inventory manager that adds products, updates stock, searches by ID and reports low-stock items. Use functions and suitable data structures.","programming_language":"C++","complexity":6,"estimated_minutes":210},
    {"title":"Full-stack: Club Task API Design","description":"Design and implement authenticated task endpoints with role checks, input validation, status transitions and tests for unauthorized access.","programming_language":"Python / FastAPI","complexity":7,"estimated_minutes":300},
]

AUTO_TASK_RANKS = {
    1: ("F", 5), 2: ("E", 10), 3: ("D", 20),
    4: ("C", 35), 5: ("B", 55), 6: ("A", 85),
    7: ("S", 125), 8: ("SS", 175), 9: ("SSS", 250),
}


# Purpose: Map a task complexity value to its rank and reward.
def automatic_task_rank(task: dict) -> tuple[str, int]:
    try:
        complexity = int(task.get("complexity", 1))
    except (TypeError, ValueError):
        complexity = 1
    complexity = max(1, min(9, complexity))
    return AUTO_TASK_RANKS[complexity]


# Purpose: Request programming-task templates from Gemini and validate the returned JSON.
def _gemini_task_templates_sync(api_key: str, model: str, count: int) -> list[dict]:
    prompt = (
        "Create " + str(max(5, min(15, count))) + " original, practical programming tasks for a beginner-to-advanced college coding club. "
        "Return ONLY a JSON object with a tasks array. Every task must contain title, description, programming_language, "
        "complexity (integer 1-9), and estimated_minutes (integer 15-480). "
        "Complexity guide: 1 tiny beginner exercise; 2-3 basic logic/loops/functions; 4-5 intermediate multi-step program or UI; "
        "6-7 advanced integration, APIs, data structures or testing; 8-9 genuinely difficult architecture/algorithm work. "
        "Do not inflate complexity. Descriptions must be self-contained, achievable, original and have measurable requirements. "
        "Avoid unsafe, harmful, credential-stealing or privacy-invasive tasks."
    )
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.8},
    }).encode("utf-8")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=25) as response:
        payload = json.loads(response.read().decode("utf-8"))
    text = payload["candidates"][0]["content"]["parts"][0]["text"]
    parsed = json.loads(text)
    tasks = parsed.get("tasks", []) if isinstance(parsed, dict) else []
    valid = []
    for item in tasks:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()[:120]
        description = str(item.get("description", "")).strip()[:3000]
        language = str(item.get("programming_language", "General")).strip()[:60]
        if len(title) < 5 or len(description) < 20 or not language:
            continue
        try:
            complexity = max(1, min(9, int(item.get("complexity", 1))))
            minutes = max(15, min(480, int(item.get("estimated_minutes", 60))))
        except (TypeError, ValueError):
            continue
        valid.append({
            "title": title, "description": description,
            "programming_language": language, "complexity": complexity,
            "estimated_minutes": minutes,
        })
    return valid


# Purpose: Use Gemini when available, otherwise fall back to the built-in task library.
async def automatic_task_templates(count: int) -> tuple[list[dict], str]:
    if settings.gemini_api_key:
        try:
            generated = await asyncio.to_thread(
                _gemini_task_templates_sync,
                settings.gemini_api_key,
                settings.gemini_model,
                count,
            )
            if generated:
                return generated, "Gemini AI"
        except Exception as exc:
            print(f"Gemini task generation unavailable; using task bank: {exc}")
    return list(AUTO_TASK_BANK), "Built-in task bank"


# Purpose: Read and validate the saved daily-task generation settings.
async def auto_task_generation_config() -> dict:
    saved = await db.app_settings.find_one({"_id": "auto_daily_task_config"}) or {}
    mode = saved.get("mode", "custom")
    if mode not in {"custom", "unlimited"}:
        mode = "custom"
    try:
        daily_target = max(1, min(50, int(saved.get("daily_target", 5))))
    except (TypeError, ValueError):
        daily_target = 5
    return {"mode": mode, "daily_target": daily_target, "unlimited_daily_cap": 20}


# Purpose: Summarize today's generated, open and total automatic shared tasks.
async def auto_task_generation_status() -> dict:
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    config = await auto_task_generation_config()
    query = {"auto_generated": True, "occurrence_date": today, "deleted_at": {"$exists": False}}
    generated_today = await db.common_tasks.count_documents(query)
    open_today = await db.common_tasks.count_documents({**query, "status": "Open"})
    total_generated = await db.common_tasks.count_documents({"auto_generated": True, "deleted_at": {"$exists": False}})
    target = config["daily_target"] if config["mode"] == "custom" else config["unlimited_daily_cap"]
    return {**config, "generated_today": generated_today, "open_today": open_today,
            "total_generated": total_generated, "daily_target_effective": target,
            "remaining_today": max(0, target - generated_today), "date": today}


# Purpose: Publish enough shared daily coding tasks to meet the configured target.
async def generate_automatic_daily_tasks() -> dict:
    """Fill today's shared volunteer board up to its configured daily target."""
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    config = await auto_task_generation_config()
    target = config["daily_target"] if config["mode"] == "custom" else config["unlimited_daily_cap"]
    existing = await db.common_tasks.find({
        "auto_generated": True, "occurrence_date": today, "deleted_at": {"$exists": False},
    }, {"title": 1}).to_list(100)
    existing_titles = {str(row.get("title", "")).strip().casefold() for row in existing}
    remaining = max(0, target - len(existing))
    if not remaining:
        return {"generated": 0, "source": "daily_limit_reached", **(await auto_task_generation_status())}

    founder = await db.users.find_one({"role": "Founder", "status": "Active"})
    recipients = await db.users.find({
        "role": {"$in": ["Member", "Faculty"]}, "status": "Active",
    }).limit(5000).to_list(5000)
    created, sequence, sources = 0, len(existing), set()
    while remaining:
        templates, source = await automatic_task_templates(min(15, remaining))
        sources.add(source)
        if source != "Gemini AI" and templates:
            # Expand the local fallback bank with clearly-labelled extensions so custom
            # targets above the bank size still work when no Gemini API key is configured.
            base_templates = list(templates)
            variant_number = 1
            while len(templates) < remaining:
                for base in base_templates:
                    if len(templates) >= remaining:
                        break
                    variant = dict(base)
                    variant["title"] = f'{base["title"]} · Extension {variant_number}'
                    variant["description"] = base["description"] + " Extension requirement: add input validation, handle an edge case, and document the result with a short test example."
                    templates.append(variant)
                variant_number += 1
        random.shuffle(templates)
        inserted_this_batch = 0
        for template in templates:
            if not remaining:
                break
            title_key = str(template.get("title", "")).strip().casefold()
            if not title_key or title_key in existing_titles:
                continue
            rank, reward = automatic_task_rank(template)
            now = utcnow()
            sequence += 1
            common_doc = {
                "_id": ObjectId(), "title": template["title"], "description": template["description"],
                "project": "Daily Coding Challenge",
                "priority": "High" if rank in {"S", "SS", "SSS"} else ("Medium" if rank in {"C", "B", "A"} else "Low"),
                "difficulty_rank": rank, "programming_language": template.get("programming_language", "General"),
                "credits_reward": reward, "late_penalty_points": 0, "task_state": "Active",
                "task_state_reason": "", "recurrence": "daily", "status": "Open",
                "due_date": today, "occurrence_date": today,
                "created_by": founder["_id"] if founder else None,
                "created_by_name": "TechNova Auto Task Engine",
                "created_at": now, "updated_at": now, "auto_generated": True,
                "generation_source": source,
                "auto_generation_key": f"auto-daily-board:{today}:{sequence}",
                "auto_complexity": template.get("complexity", 1),
                "estimated_minutes": template.get("estimated_minutes", 60),
            }
            try:
                result = await db.common_tasks.insert_one(common_doc)
            except DuplicateKeyError:
                continue
            existing_titles.add(title_key)
            created += 1
            remaining -= 1
            inserted_this_batch += 1
            for recipient in recipients:
                await create_notification(
                    recipient, "New daily coding mission",
                    f'{common_doc["title"]} is available on the shared Daily Task Board. Accept it if you want to work on it; it has not been assigned to you.',
                    "common_task", common_task_id=str(result.inserted_id),
                )
            await audit(founder, "automatic_daily_board_task_published", today, {
                "common_task_id": str(result.inserted_id), "source": source,
                "rank": rank, "credits_reward": reward, "assigned_to_members": False,
            })
        if not inserted_this_batch:
            break
    return {"generated": created, "source": ", ".join(sorted(sources)) or "none",
            **(await auto_task_generation_status())}


# Purpose: Migrate legacy generated daily tasks into the shared task-board model.
async def migrate_daily_task_board_only_mode() -> dict:
    """One-time cleanup of penalties and unintended personal auto-assignments."""
    migration_id = "daily_task_board_only_v1"
    if await db.app_settings.find_one({"_id": migration_id}):
        return {"previous_penalties_removed": 0, "old_auto_tasks_archived": 0, "auto_suspensions_reversed": 0, "personal_daily_schedules_disabled": 0}

    now = utcnow()
    penalties_removed = await db.credit_penalties.count_documents({})
    await db.credit_penalties.delete_many({})
    old_penalty_notifications = await db.notifications.delete_many({
        "$or": [
            {"type": "credit_penalty"},
            {"title": "Warning: three task deadlines missed"},
            {"title": "Automatic 24-hour club suspension"},
        ]
    })

    auto_suspended = await db.users.find({
        "role": "Member", "automatic_discipline": True,
    }).to_list(5000)
    for member in auto_suspended:
        await resume_member_paused_tasks(member["_id"], now)

    restored = await db.users.update_many(
        {"role": "Member", "automatic_discipline": True},
        {"$set": {
            "status": "Active", "suspension_until": None,
            "suspension_temporary": False, "updated_at": now,
        }, "$unset": {
            "suspension_reason": "", "suspended_at": "", "suspended_by": "",
            "automatic_discipline": "", "missed_task_warning_level": "",
            "missed_task_warning_sent_at": "",
        }},
    )
    await db.users.update_many(
        {"role": "Member"},
        {"$unset": {"missed_task_warning_level": "", "missed_task_warning_sent_at": ""}},
    )

    archived = await db.tasks.update_many(
        {
            "auto_generated": True,
            "status": {"$ne": "Done"},
            "deleted_at": {"$exists": False},
        },
        {"$set": {
            "deleted_at": now, "deleted_by": None,
            "task_state": "Deleted", "task_state_reason": "Moved to shared Daily Task Board",
            "updated_at": now,
        }},
    )
    await db.tasks.update_many(
        {"$or": [
            {"late_penalty_points": {"$gt": 0}},
            {"missed_task_penalty_applied": True},
        ]},
        {"$set": {"late_penalty_points": 0}, "$unset": {
            "late_penalty_applied_at": "", "missed_task_penalty_applied": "",
        }},
    )
    await db.app_settings.update_one(
        {"_id": migration_id},
        {"$setOnInsert": {
            "completed_at": now,
            "discipline_activated_at": now,
            "penalties_removed": penalties_removed,
            "auto_tasks_archived": archived.modified_count,
            "auto_suspensions_reversed": restored.modified_count,
        }},
        upsert=True,
    )
    disabled_personal_schedules = await db.daily_task_schedules.update_many(
        {"assignment_mode": "individual", "active": True, "deleted_at": {"$exists": False}},
        {"$set": {"active": False, "paused_reason": "Daily missions now publish to the shared volunteer board", "updated_at": now}},
    )
    return {
        "previous_penalties_removed": penalties_removed,
        "old_penalty_notifications_removed": old_penalty_notifications.deleted_count,
        "old_auto_tasks_archived": archived.modified_count,
        "auto_suspensions_reversed": restored.modified_count,
        "personal_daily_schedules_disabled": disabled_personal_schedules.modified_count,
    }



# Purpose: Run scheduled maintenance for daily missions, recurrence and time-based rules.
async def run_daily_maintenance() -> dict:
    now = utcnow()
    local_today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    today_key = local_today.isoformat()
    discipline_cleanup = await migrate_daily_task_board_only_mode()
    # Stop old recurring personal daily assignments; daily auto missions now live on the shared board.
    await db.daily_task_schedules.update_many(
        {"assignment_mode": "individual", "active": True, "deleted_at": {"$exists": False}},
        {"$set": {"active": False, "paused_reason": "Daily missions now publish to the shared volunteer board", "updated_at": now}},
    )
    migration_record = await db.app_settings.find_one({"_id": "daily_task_board_only_v1"}) or {}
    discipline_activated_at = migration_record.get("discipline_activated_at") or migration_record.get("completed_at") or now
    expired_members = await db.users.find({
        "status": "Suspended", "suspension_temporary": True,
        "suspension_until": {"$lte": now},
    }).to_list(500)
    resumed = await db.users.update_many({
        "status": "Suspended", "suspension_temporary": True,
        "suspension_until": {"$lte": now},
    }, {"$set": {
        "status": "Active", "suspension_until": None,
        "suspension_temporary": False, "suspension_expired_at": now,
    }})
    for expired_member in expired_members:
        await resume_member_paused_tasks(expired_member["_id"], now)
    # Close yesterday's unclaimed daily common missions so Members cannot accept stale opportunities.
    closed_daily_missions = await db.common_tasks.update_many({
        "recurrence": "daily", "status": {"$in": ["Open", "Suspended"]},
        "due_date": {"$lt": today_key}, "deleted_at": {"$exists": False},
    }, {"$set": {"status": "Closed", "task_state": "Closed", "closed_at": now}})
    generated = 0
    schedules = await db.daily_task_schedules.find({
        "active": True, "deleted_at": {"$exists": False},
        "start_date": {"$lte": today_key},
    }).limit(500).to_list(500)
    for schedule in schedules:
        template = schedule.get("template", {})
        schedule_id = schedule["_id"]
        if schedule.get("assignment_mode") == "open_to_all":
            common_doc = {
                **template, "_id": ObjectId(), "status": "Open", "task_state": "Active",
                "recurrence": "daily", "daily_schedule_id": schedule_id,
                "occurrence_date": today_key, "due_date": today_key,
                "created_at": now, "updated_at": now,
            }
            try:
                await db.common_tasks.insert_one(common_doc)
                generated += 1
                recipients = await db.users.find({
                    "role": {"$in": ["Member", "Faculty"]}, "status": "Active",
                }).limit(5000).to_list(5000)
                for recipient in recipients:
                    await create_notification(recipient, "New daily common task", f'{common_doc["title"]} is available today. Open Tasks & Projects to review it.', "common_task", common_task_id=str(common_doc["_id"]))
            except DuplicateKeyError:
                pass
            await db.daily_task_schedules.update_one({"_id": schedule_id}, {"$set": {"last_generated_date": today_key}})
            continue

        allowed_roles = ["Member", "Core Management"] if schedule.get("creator_role") == "Founder" else ["Member"]
        for assignee_id in schedule.get("assignee_ids", []):
            target = await db.users.find_one({"_id": assignee_id, "status": "Active", "role": {"$in": allowed_roles}})
            if not target:
                continue
            task_doc = {
                **template, "_id": ObjectId(), "assignee_id": target["_id"],
                "assignee_name": target["name"], "status": "Todo", "task_state": "Active",
                "recurrence": "daily", "daily_schedule_id": schedule_id,
                "occurrence_date": today_key, "due_date": today_key,
                "submission_note": "",
                "submission_evidence_url": "", "submission_attested": False,
                "created_at": now, "updated_at": now,
            }
            try:
                await db.tasks.insert_one(task_doc)
                generated += 1
                await create_notification(target, "New daily task assigned", f'{task_doc["title"]} has been added to your tasks for {today_key}.', "task_assigned", task_id=str(task_doc["_id"]))
            except DuplicateKeyError:
                pass
        await db.daily_task_schedules.update_one({"_id": schedule_id}, {"$set": {"last_generated_date": today_key}})

    # Future automatic discipline: only tasks created after the cleanup activation count.
    overdue = await db.tasks.find({
        "due_date": {"$lt": today_key},
        "created_at": {"$gte": discipline_activated_at},
        "status": {"$in": ["Todo", "In progress", "Review"]},
        "task_state": {"$ne": "Suspended"},
        "deleted_at": {"$exists": False},
    }).limit(5000).to_list(5000)
    penalties_applied = 0
    for task in overdue:
        if task.get("status") == "Review" and task.get("submitted_at"):
            submitted = task["submitted_at"]
            submitted_date = submitted.astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat() if submitted.tzinfo else submitted.date().isoformat()
            if submitted_date <= task.get("due_date", ""):
                continue
        task_key = "missed-task:" + str(task["_id"])
        points = task_credit_value(task)
        try:
            await db.credit_penalties.insert_one({
                "_id": ObjectId(), "reference_key": task_key,
                "user_id": task["assignee_id"], "task_id": task["_id"],
                "points": points, "category": "missed_task",
                "reason": f'Missed task deadline · rank {task.get("difficulty_rank", "F")}.',
                "actor_id": None, "created_at": now,
            })
            penalties_applied += 1
            await create_notification(
                {"_id": task["assignee_id"], "name": task.get("assignee_name", "Member"), "email": ""},
                "Task deadline missed · credit penalty",
                f'{task.get("title", "Task")} was not submitted by its due date. {points} credits (rank {task.get("difficulty_rank", "F")}) were deducted. This penalty is applied only once.',
                "credit_penalty", task_id=str(task["_id"]),
            )
        except DuplicateKeyError:
            pass
        await db.tasks.update_one({"_id": task["_id"]}, {"$set": {
            "late_penalty_applied_at": now, "late_penalty_points": points,
            "missed_task_penalty_applied": True,
        }})

    warning_counts = await db.credit_penalties.aggregate([
        {"$match": {"category": "missed_task", "task_id": {"$exists": True}}},
        {"$group": {"_id": "$user_id", "missed_task_count": {"$sum": 1}}},
        {"$match": {"missed_task_count": {"$gte": 3, "$lt": 5}}},
    ]).to_list(length=5000)
    warnings_sent = 0
    for row in warning_counts:
        member = await db.users.find_one({"_id": row["_id"], "role": "Member", "status": "Active"})
        if not member:
            continue
        warned = await db.users.update_one(
            {"_id": member["_id"], "role": "Member", "status": "Active",
             "$or": [{"missed_task_warning_level": {"$exists": False}}, {"missed_task_warning_level": {"$lt": 3}}]},
            {"$set": {"missed_task_warning_level": 3, "missed_task_warning_sent_at": now, "updated_at": now}},
        )
        if warned.modified_count != 1:
            continue
        warnings_sent += 1
        await create_notification(
            member,
            "Warning: three task deadlines missed",
            f'You have missed {row["missed_task_count"]} assigned task deadlines. Reaching 5 missed tasks triggers an automatic 24-hour club suspension. Complete accepted tasks on time or contact management if a deadline is incorrect.',
            "disciplinary",
        )
        await audit(None, "member_warned_for_three_missed_tasks", str(member["_id"]), {
            "missed_task_count": row["missed_task_count"], "suspension_threshold": 5,
        })

    missed_counts = await db.credit_penalties.aggregate([
        {"$match": {"category": "missed_task", "task_id": {"$exists": True}}},
        {"$group": {"_id": "$user_id", "missed_task_count": {"$sum": 1}}},
        {"$match": {"missed_task_count": {"$gte": 5}}},
    ]).to_list(length=5000)
    auto_suspended = 0
    for row in missed_counts:
        member = await db.users.find_one({"_id": row["_id"], "role": "Member", "status": "Active"})
        if not member:
            continue
        until = now + timedelta(hours=24)
        reason = f'Automatic suspension: {row["missed_task_count"]} assigned tasks were not completed by their deadlines.'
        changed = await db.users.update_one(
            {"_id": member["_id"], "role": "Member", "status": "Active"},
            {"$set": {
                "status": "Suspended", "suspended_at": now,
                "suspension_until": until, "suspension_temporary": True,
                "suspension_reason": reason, "suspended_by": None,
                "automatic_discipline": True, "updated_at": now,
            }},
        )
        if changed.modified_count != 1:
            continue
        auto_suspended += 1
        await db.cards.update_many(
            {"member_id": str(member["_id"]), "status": "Active"},
            {"$set": {"status": "Revoked", "revoked_at": now}},
        )
        await db.tasks.update_many({
            "assignee_id": member["_id"],
            "status": {"$in": ["Todo", "In progress", "Review"]},
            "task_state": {"$ne": "Suspended"},
            "deleted_at": {"$exists": False},
        }, {"$set": {
            "task_state": "Suspended",
            "task_state_reason": "Member temporary suspension after five missed tasks",
            "paused_at": now,
            "suspension_pause_by_member": True,
        }})
        await create_notification(
            member, "Automatic 24-hour club suspension",
            f'You missed {row["missed_task_count"]} assigned tasks. Your account is suspended until {until.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y, %I:%M %p IST")}. Contact club management if you believe this is incorrect.',
            "disciplinary",
        )
        await audit(None, "member_auto_suspended_for_missed_tasks", str(member["_id"]), {
            "missed_task_count": row["missed_task_count"], "duration_hours": 24,
            "suspension_until": until.isoformat(),
        })

    automatic_daily = await generate_automatic_daily_tasks()

    return {
        "suspensions_expired": resumed.modified_count,
        "daily_tasks_generated": generated,
        "automatic_daily_tasks_generated": automatic_daily["generated"],
        "automatic_task_source": automatic_daily["source"],
        "daily_missions_closed": closed_daily_missions.modified_count,
        "discipline_cleanup": discipline_cleanup,
        "late_penalties_applied": penalties_applied,
        "members_warned_for_missed_tasks": warnings_sent,
        "members_auto_suspended": auto_suspended,
        "checked_at": now.isoformat(),
    }


# Purpose: Run the maintenance cycle continuously while the API application is running.
async def maintenance_worker():
    while True:
        try:
            await run_daily_maintenance()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"TechNova maintenance cycle failed: {exc}")
        await asyncio.sleep(60)


# Purpose: Connect to MongoDB, initialize indexes and seed data, then cleanly stop background work.
@asynccontextmanager
async def lifespan(app: FastAPI):
    await client.admin.command("ping")
    await ensure_indexes()
    # Initialize counters once from existing records so upgrades do not collide with old IDs.
    for role, key in [("Member", "member:Member"), ("Core Management", "member:Core Management"), ("Faculty", "member:Faculty")]:
        existing = await db.users.count_documents({"role": role})
        await db.counters.update_one({"_id": key}, {"$setOnInsert": {"value": existing}}, upsert=True)
    founder_email = settings.bootstrap_founder_email.lower()
    if not await db.users.find_one({"email": founder_email}):
        await db.counters.update_one({"_id":"member:Founder"},{"$set":{"value":1}},upsert=True)
        await db.users.insert_one({"member_id":"TN001","name":settings.bootstrap_founder_name,"email":founder_email,"password_hash":hash_password(settings.bootstrap_founder_password),"role":"Founder","team":"Leadership","status":"Active","created_at":utcnow(),"approved_at":utcnow()})
    # Seed initial teams idempotently.
    for name, description in [("Leadership","Club direction and planning"),("Web Development","Websites, interfaces, APIs"),("AI / ML","Applied AI and machine learning"),("Creative & Media","Design, animation, editing"),("Game Development","Game projects and prototyping")]:
        await db.teams.update_one({"name":name},{"$setOnInsert":{"name":name,"description":description,"created_at":utcnow()}},upsert=True)
    maintenance_task = asyncio.create_task(maintenance_worker())
    yield
    maintenance_task.cancel()
    try:
        await maintenance_task
    except asyncio.CancelledError:
        pass
    client.close()


# Shared request rate limiter used by the routers and configured by main.py.
limiter = Limiter(key_func=get_remote_address, default_limits=["300/hour"])

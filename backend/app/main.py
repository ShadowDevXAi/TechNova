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

def task_credit_value(task: dict) -> int:
    return TASK_CREDIT_VALUES.get(task.get("difficulty_rank", "F"), TASK_CREDIT_VALUES["F"])

def member_rank(credits: int) -> str:
    # Negative balances are valid after penalties; F is the minimum rank.
    return next((rank for rank, threshold in MEMBER_RANK_THRESHOLDS if credits >= threshold), "F")

def oid(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(400, "Invalid record ID")
    return ObjectId(value)

def clean_user(doc: dict) -> dict:
    return {"id": str(doc["_id"]), "member_id": doc["member_id"], "name": doc["name"], "email": doc["email"], "role": doc["role"], "team": doc.get("team","Unassigned"), "status": doc["status"], "created_at": doc.get("created_at"), "suspension_until": doc.get("suspension_until"), "suspension_reason": doc.get("suspension_reason"), "suspension_temporary": bool(doc.get("suspension_temporary", False))}

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
        "created_by": str(doc["created_by"]),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        "auto_generated": bool(doc.get("auto_generated", False)),
        "generation_source": doc.get("generation_source", ""),
    }

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
    if user and user.get("status") == "Suspended" and user.get("suspension_temporary") and user.get("suspension_until") and user["suspension_until"] <= utcnow():
        await db.users.update_one({"_id": user["_id"], "status": "Suspended"}, {"$set": {"status": "Active", "suspension_until": None, "suspension_temporary": False, "suspension_expired_at": utcnow()}})
        user = await db.users.find_one({"_id": user["_id"]})
        await resume_member_paused_tasks(user["_id"], utcnow())
    if not user or user.get("status") != "Active":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account is unavailable")
    return user

def allow(*roles: str):
    async def dependency(user: dict = Depends(get_current_user)):
        if user.get("role") not in roles:
            raise HTTPException(403, "You do not have permission to perform this action")
        return user
    return dependency



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


def automatic_task_rank(task: dict) -> tuple[str, int]:
    try:
        complexity = int(task.get("complexity", 1))
    except (TypeError, ValueError):
        complexity = 1
    complexity = max(1, min(9, complexity))
    return AUTO_TASK_RANKS[complexity]


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
            while len(templates) < min(15, remaining):
                for base in base_templates:
                    if len(templates) >= min(15, remaining):
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


async def maintenance_worker():
    while True:
        try:
            await run_daily_maintenance()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"TechNova maintenance cycle failed: {exc}")
        await asyncio.sleep(60)


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


@app.get("/api/admin/database-stats")
async def database_stats(actor: dict = Depends(allow("Founder", "Core Management"))):
    """Live MongoDB database/collection counts and storage statistics."""
    stats = await db.command("dbStats")
    collection_names = await db.list_collection_names()
    collection_names = sorted(collection_names)
    counts = await asyncio.gather(*(db[name].count_documents({}) for name in collection_names))
    collections = [{"name": name, "documents": count} for name, count in zip(collection_names, counts)]
    total_documents = sum(counts)

    storage_bytes = int(stats.get("storageSize", 0)) + int(stats.get("indexSize", 0))
    data_bytes = int(stats.get("dataSize", 0))
    index_bytes = int(stats.get("indexSize", 0))
    try:
        limit_gb = float(os.getenv("MONGODB_STORAGE_LIMIT_GB", "0") or 0)
    except ValueError:
        limit_gb = 0
    limit_bytes = int(limit_gb * 1024 ** 3) if limit_gb > 0 else None
    return {
        "database": db.name,
        "collections_count": len(collection_names),
        "documents_count": total_documents,
        "storage_bytes": storage_bytes,
        "data_bytes": data_bytes,
        "index_bytes": index_bytes,
        "storage_limit_bytes": limit_bytes,
        "remaining_bytes": max(0, limit_bytes - storage_bytes) if limit_bytes else None,
        "storage_limit_configured": bool(limit_bytes),
        "collections": collections,
        "measured_at": utcnow().isoformat(),
    }


@app.post("/api/maintenance/run")
async def run_maintenance_now(actor: dict = Depends(allow("Founder"))):
    return {"message": "Maintenance cycle completed", **(await run_daily_maintenance())}

@app.get("/api/auto-tasks/settings")
async def get_auto_task_settings(actor: dict = Depends(allow("Founder", "Core Management"))):
    return await auto_task_generation_status()


@app.put("/api/auto-tasks/settings")
async def update_auto_task_settings(body: dict, request: Request, actor: dict = Depends(allow("Founder"))):
    mode = body.get("mode", "custom")
    if mode not in {"custom", "unlimited"}:
        raise HTTPException(422, "Mode must be custom or unlimited")
    try:
        daily_target = int(body.get("daily_target", 5))
    except (TypeError, ValueError):
        raise HTTPException(422, "Daily target must be a whole number")
    if daily_target < 1 or daily_target > 50:
        raise HTTPException(422, "Custom daily target must be between 1 and 50")
    await db.app_settings.update_one(
        {"_id": "auto_daily_task_config"},
        {"$set": {"mode": mode, "daily_target": daily_target, "updated_at": utcnow(), "updated_by": actor["_id"]}},
        upsert=True,
    )
    await audit(actor, "auto_daily_task_settings_updated", "auto_daily_task_config", {
        "mode": mode, "daily_target": daily_target, "unlimited_daily_cap": 20,
    }, request)
    return await auto_task_generation_status()


@app.post("/api/auto-tasks/generate")
async def generate_auto_tasks_now(request: Request, actor: dict = Depends(allow("Founder"))):
    result = await generate_automatic_daily_tasks()
    await audit(actor, "auto_daily_tasks_generate_requested", result.get("date", ""), {
        "generated": result.get("generated", 0), "mode": result.get("mode"),
    }, request)
    return {"message": "Daily mission generation run completed", **result}

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
        active_task_filter = {"deleted_at": {"$exists": False}}
        tasks = await db.tasks.count_documents(active_task_filter)
        open_tasks = await db.tasks.count_documents({**active_task_filter, "status":{"$ne":"Done"}})
        done = await db.tasks.count_documents({**active_task_filter, "status":"Done"})
        recent = await db.tasks.find(active_task_filter).sort("created_at",-1).limit(6).to_list(6)
        return {"members_total":total,"members_active":active,"members_pending":pending,"tasks_total":tasks,"tasks_open":open_tasks,"tasks_done":done,"recent_tasks":[clean_task(x) for x in recent]}
    own_tasks = await db.tasks.find({"assignee_id":user["_id"], "deleted_at": {"$exists": False}}).sort("created_at",-1).limit(10).to_list(10)
    return {"members_total":1,"members_active":1,"members_pending":0,"tasks_total":len(own_tasks),"tasks_open":sum(x["status"]!="Done" for x in own_tasks),"tasks_done":sum(x["status"]=="Done" for x in own_tasks),"recent_tasks":[clean_task(x) for x in own_tasks]}

@app.get("/api/credits/ledger")
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


@app.get("/api/leaderboard")
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
    query = {"deleted_at": {"$exists": False}}
    if user["role"] not in PRIVILEGED:
        query["assignee_id"] = user["_id"]
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


@app.post("/api/announcements", status_code=201)
async def broadcast_announcement(
    data: AnnouncementCreate,
    request: Request,
    actor: dict = Depends(allow("Founder", "Core Management")),
):
    recipients = await db.users.find({
        "role": {"$in": ["Member", "Faculty"]},
        "status": "Active",
    }).to_list(5000)
    if not recipients:
        raise HTTPException(409, "There are no active Members or Faculty accounts to notify")

    semaphore = asyncio.Semaphore(8)

    async def deliver(recipient: dict) -> None:
        async with semaphore:
            await create_notification(
                recipient,
                data.title.strip(),
                data.message.strip(),
                "announcement",
            )

    await asyncio.gather(*(deliver(recipient) for recipient in recipients))
    member_count = sum(recipient.get("role") == "Member" for recipient in recipients)
    faculty_count = sum(recipient.get("role") == "Faculty" for recipient in recipients)
    await audit(actor, "announcement_broadcast", data.title.strip(), {
        "recipient_count": len(recipients),
        "member_count": member_count,
        "faculty_count": faculty_count,
    }, request)
    return {
        "message": f"Announcement sent to {len(recipients)} people",
        "recipient_count": len(recipients),
        "member_count": member_count,
        "faculty_count": faculty_count,
    }


@app.get("/api/common-tasks")
async def list_common_tasks(user: dict = Depends(get_current_user)):
    common_query = {"deleted_at": {"$exists": False}, "status": {"$in": ["Open", "Suspended"]} if user["role"] in PRIVILEGED else "Open"}
    docs = await db.common_tasks.find(common_query).sort("created_at", -1).limit(200).to_list(200)
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
    query = {"status": "Review", "deleted_at": {"$exists": False}}
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
        if not task.get("submission_evidence_url") or not task.get("submission_attested"):
            raise HTTPException(
                409,
                f'Task "{task.get("title", "Untitled")}" has no screenshot proof or member attestation. Return it for resubmission before approval.',
            )

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
                "credits_awarded": task_credit_value(task),
                "credits_awarded_at": now,
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
        "status": "Review", "deleted_at": {"$exists": False},
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
    if data.recurrence == "daily" and data.assignment_mode == "individual":
        raise HTTPException(422, "Daily recurring missions now publish to the shared Daily Task Board. Use a one-time task for individual assignments.")
    base = {
        "title": data.title.strip(),
        "description": data.description.strip(),
        "project": data.project.strip() or "Club projects",
        "priority": data.priority,
        "difficulty_rank": data.difficulty_rank,
        "programming_language": data.programming_language,
        "credits_reward": TASK_CREDIT_VALUES[data.difficulty_rank],
        "task_state": "Active",
        "recurrence": data.recurrence,
        "due_date": data.due_date or (datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat() if data.recurrence == "daily" else None),
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
        if data.recurrence == "daily":
            local_today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
            await db.daily_task_schedules.insert_one({
                "title": base["title"], "template": base, "assignment_mode": "open_to_all",
                "assignee_ids": [], "created_by": actor["_id"], "created_by_name": actor["name"],
                "creator_role": actor["role"], "active": True,
                "start_date": (local_today + timedelta(days=1)).isoformat(),
                "created_at": now, "last_generated_date": local_today.isoformat(),
            })
        active_members = await db.users.find({
            "role": {"$in": ["Member", "Faculty"]},
            "status": "Active",
        }).to_list(5000)
        for recipient in active_members:
            recipient_message = (
                f'{actor["name"]} posted "{common_doc["title"]}". Open Tasks & Projects to accept or decline it.'
                if recipient.get("role") == "Member"
                else f'{actor["name"]} published the common task "{common_doc["title"]}" for Members to volunteer.'
            )
            await create_notification(
                recipient,
                "New common task available",
                recipient_message,
                "common_task",
                common_task_id=str(result.inserted_id),
            )
        await audit(actor, "common_task_created", str(result.inserted_id), {
            "notified_members_and_faculty": len(active_members),
            "members": sum(x.get("role") == "Member" for x in active_members),
            "faculty": sum(x.get("role") == "Faculty" for x in active_members),
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

    schedule_id = None
    if data.recurrence == "daily":
        local_today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        saved_schedule = await db.daily_task_schedules.insert_one({
            "title": base["title"], "template": base,
            "assignment_mode": data.assignment_mode,
            "assignee_ids": [target["_id"] for target in targets],
            "created_by": actor["_id"], "created_by_name": actor["name"],
            "creator_role": actor["role"], "active": True,
            "start_date": (local_today + timedelta(days=1)).isoformat(),
            "created_at": now, "last_generated_date": local_today.isoformat(),
        })
        schedule_id = saved_schedule.inserted_id
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
            "daily_schedule_id": schedule_id,
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
    if common.get("task_state", "Active") != "Active":
        raise HTTPException(409, "This common task is temporarily paused by management")
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
            "difficulty_rank": common.get("difficulty_rank", "F"),
            "programming_language": common.get("programming_language", "General"),
            "credits_reward": common.get("credits_reward", TASK_CREDIT_VALUES["F"]),
            "status": "In progress",
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


@app.post("/api/tasks/{task_id}/state")
async def set_task_state(task_id: str, data: TaskStateIn, request: Request, actor: dict = Depends(allow("Founder", "Core Management"))):
    task = await db.tasks.find_one({"_id": oid(task_id), "deleted_at": {"$exists": False}})
    if not task:
        raise HTTPException(404, "Task not found")
    if actor.get("role") == "Core Management":
        assignee = await db.users.find_one({"_id": task["assignee_id"]})
        if not assignee or assignee.get("role") != "Member":
            raise HTTPException(403, "Core Management can pause or resume Member tasks only")
    reason = (data.reason or "").strip()
    if data.state == "Suspended" and len(reason) < 5:
        raise HTTPException(422, "Give a reason of at least 5 characters for pausing a task")
    now = utcnow()
    changes = {"task_state": data.state, "task_state_reason": reason if data.state == "Suspended" else "", "updated_at": now}
    if data.state == "Suspended":
        changes["paused_at"] = now
    else:
        paused_at = task.get("paused_at")
        if paused_at and task.get("due_date"):
            paused_days = max(1, math.ceil((now - paused_at).total_seconds() / 86400))
            try:
                changes["due_date"] = (datetime.fromisoformat(task["due_date"]).date() + timedelta(days=paused_days)).isoformat()
            except ValueError:
                pass
        changes["paused_at"] = None
    await db.tasks.update_one({"_id": task["_id"]}, {"$set": changes})
    await audit(actor, "task_" + data.state.lower(), task_id, {"reason": reason, "deadline_paused": True}, request)
    return clean_task(await db.tasks.find_one({"_id": task["_id"]}))


@app.delete("/api/tasks/{task_id}")
async def soft_delete_task(task_id: str, request: Request, actor: dict = Depends(allow("Founder", "Core Management"))):
    task = await db.tasks.find_one({"_id": oid(task_id), "deleted_at": {"$exists": False}})
    if not task:
        raise HTTPException(404, "Task not found or already deleted")
    if actor.get("role") == "Core Management":
        assignee = await db.users.find_one({"_id": task["assignee_id"]})
        if not assignee or assignee.get("role") != "Member":
            raise HTTPException(403, "Core Management can archive Member tasks only")
    now = utcnow()
    await db.tasks.update_one({"_id": task["_id"]}, {"$set": {"deleted_at": now, "deleted_by": actor["_id"], "task_state": "Deleted", "updated_at": now}})
    await audit(actor, "task_soft_deleted", task_id, {"title": task.get("title", "")}, request)
    return {"message": "Task archived (soft deleted). Its history and audit data are retained."}


@app.post("/api/common-tasks/{common_task_id}/state")
async def set_common_task_state(common_task_id: str, data: TaskStateIn, request: Request, actor: dict = Depends(allow("Founder", "Core Management"))):
    task = await db.common_tasks.find_one({"_id": oid(common_task_id), "deleted_at": {"$exists": False}})
    if not task:
        raise HTTPException(404, "Common task not found")
    reason = (data.reason or "").strip()
    if data.state == "Active" and task.get("recurrence") == "daily" and task.get("due_date"):
        local_today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        if task["due_date"] < local_today:
            await db.common_tasks.update_one(
                {"_id": task["_id"]},
                {"$set": {"status": "Closed", "task_state": "Closed", "closed_at": utcnow()}},
            )
            raise HTTPException(409, "This daily mission has expired. The next scheduled occurrence will be created automatically.")
    if data.state == "Suspended" and len(reason) < 5:
        raise HTTPException(422, "Give a reason of at least 5 characters for pausing a task")
    await db.common_tasks.update_one({"_id": task["_id"]}, {"$set": {
        "status": "Suspended" if data.state == "Suspended" else "Open",
        "task_state": data.state, "task_state_reason": reason if data.state == "Suspended" else "",
        "updated_at": utcnow(),
    }})
    await audit(actor, "common_task_" + data.state.lower(), common_task_id, {"reason": reason}, request)
    return {"message": "Common task " + ("paused" if data.state == "Suspended" else "resumed")}


@app.delete("/api/common-tasks/{common_task_id}")
async def soft_delete_common_task(common_task_id: str, request: Request, actor: dict = Depends(allow("Founder", "Core Management"))):
    task = await db.common_tasks.find_one({"_id": oid(common_task_id), "deleted_at": {"$exists": False}})
    if not task:
        raise HTTPException(404, "Common task not found or already deleted")
    await db.common_tasks.update_one({"_id": task["_id"]}, {"$set": {
        "status": "Deleted", "deleted_at": utcnow(), "deleted_by": actor["_id"],
        "task_state": "Deleted", "updated_at": utcnow(),
    }})
    await audit(actor, "common_task_soft_deleted", common_task_id, {"title": task.get("title", "")}, request)
    return {"message": "Common task archived. Its history is retained."}


@app.post("/api/members/{member_id}/suspend")
async def temporarily_suspend_member(member_id: str, data: MemberSuspendIn, request: Request, actor: dict = Depends(allow("Founder", "Core Management"))):
    target = await db.users.find_one({"_id": oid(member_id)})
    if not target:
        raise HTTPException(404, "Member not found")
    if target.get("role") != "Member":
        raise HTTPException(403, "Temporary discipline action is limited to Member accounts")
    if target.get("status") != "Active":
        raise HTTPException(409, "Only active Members can be temporarily suspended")
    now = utcnow()
    until = now + timedelta(hours=data.duration_hours)
    sanction_id = ObjectId()
    changed = await db.users.update_one({"_id": target["_id"], "status": "Active"}, {"$set": {
        "status": "Suspended", "suspended_at": now, "suspension_until": until,
        "suspension_temporary": True, "suspension_reason": data.reason.strip(),
        "suspended_by": actor["_id"], "updated_at": now,
    }})
    if changed.modified_count != 1:
        raise HTTPException(409, "Member status changed; refresh and retry")
    await db.cards.update_many({"member_id": str(target["_id"]), "status": "Active"}, {"$set": {"status": "Revoked", "revoked_at": now}})
    await db.tasks.update_many({
        "assignee_id": target["_id"], "status": {"$in": ["Todo", "In progress", "Review"]},
        "task_state": {"$ne": "Suspended"}, "deleted_at": {"$exists": False},
    }, {"$set": {"task_state": "Suspended", "task_state_reason": "Member temporary suspension", "paused_at": now, "suspension_pause_by_member": True}})
    # Club discipline deductions may take a member's credit balance below zero.
    actual_penalty = data.credit_penalty
    if actual_penalty > 0:
        await db.credit_penalties.insert_one({
            "_id": sanction_id, "reference_key": "disciplinary:" + str(sanction_id),
            "user_id": target["_id"], "points": actual_penalty,
            "category": "disciplinary", "reason": data.reason.strip(),
            "actor_id": actor["_id"], "created_at": now,
        })
    await create_notification(target, "Temporary account suspension", f"Your TechNova account is suspended until {until.isoformat()}. Reason: {data.reason.strip()}. Credit deduction: {actual_penalty}.", "disciplinary")
    await audit(actor, "member_temporarily_suspended", member_id, {
        "reason": data.reason.strip(), "duration_hours": data.duration_hours,
        "suspension_until": until.isoformat(), "credit_penalty": actual_penalty,
    }, request)
    return {"message": "Member temporarily suspended", "suspension_until": until, "credit_penalty": actual_penalty}


@app.post("/api/members/{member_id}/reinstate")
async def reinstate_member(member_id: str, request: Request, actor: dict = Depends(allow("Founder", "Core Management"))):
    target = await db.users.find_one({"_id": oid(member_id)})
    if not target:
        raise HTTPException(404, "Member not found")
    if target.get("role") != "Member":
        raise HTTPException(403, "Only Member accounts can be reinstated by this action")
    changed = await db.users.update_one({"_id": target["_id"], "status": "Suspended"}, {"$set": {
        "status": "Active", "suspension_until": None, "suspension_temporary": False,
        "reinstated_at": utcnow(), "reinstated_by": actor["_id"],
    }, "$unset": {"suspension_reason": "", "suspended_at": ""}})
    if not changed.modified_count:
        raise HTTPException(409, "This Member is not currently suspended")
    await resume_member_paused_tasks(target["_id"], utcnow())
    await audit(actor, "member_reinstated", member_id, {}, request)
    return clean_user(await db.users.find_one({"_id": target["_id"]}))


@app.get("/api/task-schedules")
async def list_task_schedules(actor: dict = Depends(allow("Founder", "Core Management"))):
    docs = await db.daily_task_schedules.find({"deleted_at": {"$exists": False}}).sort("created_at", -1).limit(200).to_list(200)
    return [{
        "id": str(doc["_id"]), "title": doc.get("title", "Daily task"),
        "assignment_mode": doc.get("assignment_mode", "individual"),
        "active": bool(doc.get("active", True)), "start_date": doc.get("start_date"),
        "last_generated_date": doc.get("last_generated_date"),
        "created_by_name": doc.get("created_by_name", "Management"),
    } for doc in docs]


@app.post("/api/task-schedules/{schedule_id}/toggle")
async def toggle_task_schedule(schedule_id: str, request: Request, actor: dict = Depends(allow("Founder", "Core Management"))):
    schedule = await db.daily_task_schedules.find_one({"_id": oid(schedule_id), "deleted_at": {"$exists": False}})
    if not schedule:
        raise HTTPException(404, "Daily schedule not found")
    active = not bool(schedule.get("active", True))
    await db.daily_task_schedules.update_one({"_id": schedule["_id"]}, {"$set": {"active": active, "updated_at": utcnow()}})
    await audit(actor, "daily_schedule_" + ("resumed" if active else "paused"), schedule_id, {}, request)
    return {"message": "Daily task schedule " + ("resumed" if active else "paused"), "active": active}


@app.delete("/api/task-schedules/{schedule_id}")
async def delete_task_schedule(schedule_id: str, request: Request, actor: dict = Depends(allow("Founder", "Core Management"))):
    schedule = await db.daily_task_schedules.find_one({"_id": oid(schedule_id), "deleted_at": {"$exists": False}})
    if not schedule:
        raise HTTPException(404, "Daily schedule not found")
    await db.daily_task_schedules.update_one({"_id": schedule["_id"]}, {"$set": {"active": False, "deleted_at": utcnow(), "deleted_by": actor["_id"]}})
    await audit(actor, "daily_schedule_deleted", schedule_id, {"title": schedule.get("title", "")}, request)
    return {"message": "Daily task schedule stopped. Generated tasks are kept."}


@app.patch("/api/tasks/{task_id}")
async def update_task(task_id: str, data: TaskPatch, request: Request, actor: dict = Depends(get_current_user)):
    target = await db.tasks.find_one({"_id": oid(task_id), "deleted_at": {"$exists": False}})
    if not target:
        raise HTTPException(404, "Task not found")
    privileged = actor["role"] in PRIVILEGED
    if target.get("task_state", "Active") != "Active" and not privileged:
        raise HTTPException(409, "This task is temporarily paused by management")
    if actor.get("role") == "Faculty":
        raise HTTPException(403, "Faculty accounts have read-only access")
    if not privileged and target["assignee_id"] != actor["_id"]:
        raise HTTPException(403, "You can only update tasks assigned to you")

    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    member_fields = {"status", "submission_note", "submission_evidence_url", "project_url", "submission_attested"}
    if not privileged and set(changes) - member_fields:
        raise HTTPException(403, "Members may only update their task status and submit evidence")
    if not privileged and changes.get("status") not in {None, "Todo", "In progress", "Review"}:
        raise HTTPException(403, "Members must submit tasks for review; completion requires a staff approval")
    if privileged and changes.get("status") == "Review":
        raise HTTPException(403, "Only the assigned Member can submit a task for review")

    if not privileged and any(
        field in changes for field in ("submission_note", "submission_evidence_url", "project_url", "submission_attested")
    ) and changes.get("status") != "Review":
        raise HTTPException(403, "Evidence details can only be saved together with a review submission")

    if not privileged and "status" in changes:
        allowed_transitions = {
            "Todo": {"In progress"},
            "In progress": {"Review"},
            "Review": {"In progress"},
        }
        if changes["status"] != target.get("status") and changes["status"] not in allowed_transitions.get(target.get("status"), set()):
            raise HTTPException(409, f'Invalid task transition: {target.get("status")} → {changes["status"]}')

    if changes.get("status") == "Done":
        raise HTTPException(403, "Only Founder or Core Management can approve a submitted task")

    for field in ("submission_evidence_url", "project_url"):
        value = changes.get(field)
        if value and (not value.startswith("https://") or any(ch.isspace() for ch in value)):
            raise HTTPException(422, f"{field.replace('_', ' ').capitalize()} must be a valid HTTPS link")

    if changes.get("status") == "Review":
        evidence_url = changes.get("submission_evidence_url") or target.get("submission_evidence_url")
        note = changes.get("submission_note", target.get("submission_note", "")).strip()
        if not evidence_url:
            raise HTTPException(422, "Add a screenshot evidence link before submitting for review")
        if not evidence_url.startswith("https://") or any(ch.isspace() for ch in evidence_url):
            raise HTTPException(422, "Screenshot evidence must be a valid HTTPS link")
        if len(note) < 10:
            raise HTTPException(422, "Write at least 10 characters describing what you completed")
        if changes.get("submission_attested") is not True:
            raise HTTPException(422, "Confirm that the screenshot and submitted work represent your current task")
        changes["submission_note"] = note
        changes["submitted_at"] = utcnow()
        changes["submitted_by"] = actor["_id"]
        changes["completion_confirmed_at"] = None
        changes["completion_confirmed_by"] = None
        changes["completion_confirmed_by_name"] = None
        changes["completion_confirmed_by_role"] = None
        changes["review_feedback"] = ""
    elif changes.get("status") == "In progress" and target.get("status") == "Review":
        changes["submitted_at"] = None
        changes["submitted_by"] = None
        changes["submission_evidence_url"] = ""
        changes["project_url"] = ""
        changes["submission_attested"] = False
        if privileged:
            feedback = changes.get("review_feedback", "").strip()
            if not feedback:
                raise HTTPException(422, "Provide feedback explaining what the member must fix")
            changes["review_feedback"] = feedback
        else:
            changes["review_feedback"] = target.get("review_feedback", "")

    reassigned_to = None
    if privileged and "assignee_id" in changes:
        assignee = await db.users.find_one({"_id": oid(changes["assignee_id"])})
        if not assignee or assignee["status"] != "Active":
            raise HTTPException(400, "Assignee must be active")
        if not can_assign_task(actor, assignee):
            raise HTTPException(403, "You cannot assign tasks to this role")
        changes["assignee_id"] = assignee["_id"]
        changes["assignee_name"] = assignee["name"]
        reassigned_to = assignee

    changes["updated_at"] = utcnow()
    await db.tasks.update_one({"_id": target["_id"]}, {"$set": changes})

    if reassigned_to:
        await create_notification(
            reassigned_to,
            "Task assigned to you",
            f'{actor["name"]} assigned you "{target["title"]}".',
            "task_assigned",
            task_id=task_id,
        )

    if changes.get("status") == "In progress" and target.get("status") == "Review":
        assignee = await db.users.find_one({"_id": target["assignee_id"]})
        if assignee:
            message = changes.get("review_feedback") or "Please update your submission evidence and send it for review again."
            await create_notification(
                assignee,
                "Task needs changes",
                f'{actor["name"]} returned "{target["title"]}" for changes: {message}',
                "task_changes_requested",
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
                f'{actor["name"]} submitted "{target["title"]}" with screenshot evidence for review.',
                "task_review",
                task_id=task_id,
            )

    await audit(actor, "task_updated", task_id, {"fields": list(changes)}, request)
    return clean_task(await db.tasks.find_one({"_id": target["_id"]}))

@app.post("/api/tasks/{task_id}/attachments", status_code=201)
async def upload_task_attachment(task_id: str, request: Request, file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    task = await db.tasks.find_one({"_id": oid(task_id), "deleted_at": {"$exists": False}})
    if not task:
        raise HTTPException(404, "Task not found")
    if user["role"] not in PRIVILEGED and task["assignee_id"] != user["_id"]:
        raise HTTPException(403, "You cannot upload to this task")
    if user["role"] not in PRIVILEGED and task.get("task_state", "Active") != "Active":
        raise HTTPException(409, "This task is paused by management; uploads are temporarily disabled.")
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


@app.get("/api/audit")
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

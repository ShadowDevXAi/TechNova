"""Task, notification and announcement endpoints.

Contains individual/shared tasks, approvals, moderation, submissions, comments,
attachments, recurring schedules and temporary member suspension workflows.

All protected operations reuse authentication and role checks from app.core.
"""

import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from ..core import *  # Shared database, schemas, authorization and business helpers.
from ..storage import store_attachment, read_attachment
from ..config import settings

router = APIRouter()
logger = logging.getLogger("technova.tasks")

# Purpose: list tasks handles the tasks feature flow and returns its API result.
@router.get("/api/tasks")
async def list_tasks(user: dict = Depends(get_current_user)):
    # Founder and Core Management can inspect the full club task register.
    # Members only receive tasks assigned to their own account.
    query = {"deleted_at": {"$exists": False}}
    if user.get("role") not in {"Founder", "Core Management"}:
        query["assignee_id"] = user["_id"]
    docs = await db.tasks.find(query).sort("created_at", -1).limit(5000).to_list(5000)
    tasks = []
    skipped = 0
    for doc in docs:
        try:
            tasks.append(clean_task(doc))
        except Exception:
            skipped += 1
            logger.exception(
                "Skipping malformed task record during /api/tasks serialization; task_id=%s",
                str(doc.get("_id", "unknown")) if isinstance(doc, dict) else "unknown",
            )
    if skipped:
        logger.error(
            "/api/tasks returned %s valid task(s); skipped %s malformed task record(s)",
            len(tasks), skipped,
        )
    return tasks


# Purpose: list notifications handles the tasks feature flow and returns its API result.
@router.get("/api/notifications")
async def list_notifications(user: dict = Depends(get_current_user)):
    docs = await db.notifications.find({"user_id": user["_id"]}).sort("created_at", -1).limit(60).to_list(60)
    return [clean_notification(x) for x in docs]


# Purpose: mark notification read handles the tasks feature flow and returns its API result.
@router.post("/api/notifications/{notification_id}/read")
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


# Purpose: broadcast announcement handles the tasks feature flow and returns its API result.
@router.post("/api/announcements", status_code=201)
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


# Purpose: list common tasks handles the tasks feature flow and returns its API result.
@router.get("/api/common-tasks")
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


# Purpose: task review queue handles the tasks feature flow and returns its API result.
@router.get("/api/tasks/review-queue")
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


# Purpose: bulk confirm task completion handles the tasks feature flow and returns its API result.
@router.post("/api/tasks/bulk-confirm")
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
            await create_task_notification(
                member, task,
                "Task completion approved",
                f'{actor["name"]} approved your submission for "{task["title"]}".',
                "task_approved",
                task_id=str(task["_id"]),
                extra_details={"Approved by": actor["name"], "Credits awarded": f'{task_credit_value(task)} credits'},
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


# Purpose: pending completion tasks handles the tasks feature flow and returns its API result.
@router.get("/api/tasks/pending-confirmation")
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


# Purpose: can assign task handles the tasks feature flow and returns its API result.
def can_assign_task(actor: dict, target: dict) -> bool:
    # Founder can assign to Core Management and Members. Core Management can assign only to Members.
    if actor.get("role") == "Founder":
        return target.get("role") in {"Core Management", "Member"}
    if actor.get("role") == "Core Management":
        return target.get("role") == "Member"
    return False


# Purpose: create task handles the tasks feature flow and returns its API result.
@router.post("/api/tasks", status_code=201)
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
            await create_task_notification(
                recipient, common_doc,
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
            **({"daily_schedule_id": schedule_id} if schedule_id is not None else {}),
        }
        result = await db.tasks.insert_one(doc)
        doc["_id"] = result.inserted_id
        created.append(clean_task(doc))
        due_text = f' Due date: {data.due_date}.' if data.due_date else ""
        await create_task_notification(
            target, doc,
            "New task assigned to you",
            f'{actor["name"]} assigned you "{data.title.strip()}". Project: {base["project"]}.{due_text}',
            "task_assigned",
            task_id=str(result.inserted_id),
            extra_details={"Assigned by": actor["name"]},
        )
    await audit(actor, "task_created", group_id or created[0]["id"], {
        "assignee_ids": [str(target["_id"]) for target in targets],
        "task_count": len(created),
        "assignment_group_id": group_id,
    }, request)
    if len(created) == 1:
        return created[0]
    return {"count": len(created), "assignment_group_id": group_id, "tasks": created}


# Purpose: respond to common task handles the tasks feature flow and returns its API result.
@router.post("/api/common-tasks/{common_task_id}/respond")
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
        await create_task_notification(
            creator, common,
            f'Common task {response}',
            f'{user["name"]} {response} "{common["title"]}".',
            "common_task_response",
            task_id=str(personal_task["_id"]) if personal_task else None,
            common_task_id=common_task_id,
            extra_details={"Member response": response, "Member": user["name"]},
        )
    await audit(user, "common_task_responded", common_task_id, {"response": response}, request)
    return {
        "message": "You accepted the task. It is now in your task list." if response == "accepted" else "You declined this common task.",
        "response": response,
        "task_id": str(personal_task["_id"]) if personal_task else None,
    }


# Purpose: set task state handles the tasks feature flow and returns its API result.
@router.post("/api/tasks/{task_id}/state")
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
    previous_state = task.get("task_state", "Active")
    await db.tasks.update_one({"_id": task["_id"]}, {"$set": changes})
    if previous_state != data.state:
        assignee = await db.users.find_one({"_id": task["assignee_id"], "status": "Active"})
        if assignee:
            is_paused = data.state == "Suspended"
            detail = f" Reason: {reason}" if is_paused and reason else ""
            await create_task_notification(
                assignee, task,
                "Task paused by management" if is_paused else "Task resumed by management",
                f"{actor['name']} {'paused' if is_paused else 'resumed'} \"{task['title']}\".{detail}",
                "task_paused" if is_paused else "task_resumed",
                task_id=task_id,
            )
    await audit(actor, "task_" + data.state.lower(), task_id, {"reason": reason, "deadline_paused": True}, request)
    return clean_task(await db.tasks.find_one({"_id": task["_id"]}))


# Purpose: soft delete task handles the tasks feature flow and returns its API result.
@router.delete("/api/tasks/{task_id}")
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


# Purpose: set common task state handles the tasks feature flow and returns its API result.
@router.post("/api/common-tasks/{common_task_id}/state")
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
    previous_state = task.get("task_state", "Active")
    await db.common_tasks.update_one({"_id": task["_id"]}, {"$set": {
        "status": "Suspended" if data.state == "Suspended" else "Open",
        "task_state": data.state, "task_state_reason": reason if data.state == "Suspended" else "",
        "updated_at": utcnow(),
    }})
    if previous_state != data.state:
        responses = await db.common_task_responses.find({
            "common_task_id": task["_id"], "response": "accepted",
        }).to_list(5000)
        accepted_ids = list({row["user_id"] for row in responses if row.get("user_id")})
        recipients = await db.users.find({"_id": {"$in": accepted_ids}, "status": "Active"}).to_list(5000) if accepted_ids else []
        is_paused = data.state == "Suspended"
        detail = f" Reason: {reason}" if is_paused and reason else ""
        for recipient in recipients:
            await create_task_notification(
                recipient, task,
                "Common mission paused" if is_paused else "Common mission reopened",
                f"{actor['name']} {'paused' if is_paused else 'reopened'} \"{task['title']}\".{detail}",
                "common_task_paused" if is_paused else "common_task_resumed",
                common_task_id=common_task_id,
            )
    await audit(actor, "common_task_" + data.state.lower(), common_task_id, {"reason": reason}, request)
    return {"message": "Common task " + ("paused" if data.state == "Suspended" else "resumed")}


# Purpose: soft delete common task handles the tasks feature flow and returns its API result.
@router.delete("/api/common-tasks/{common_task_id}")
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


# Purpose: temporarily suspend member handles the tasks feature flow and returns its API result.
@router.post("/api/members/{member_id}/suspend")
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


# Purpose: reinstate member handles the tasks feature flow and returns its API result.
@router.post("/api/members/{member_id}/reinstate")
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
    await create_notification(
        target,
        "TechNova account reinstated",
        f"Your account access has been restored by {actor['name']}. You can sign in and continue your club work.",
        "account_reinstated",
    )
    await audit(actor, "member_reinstated", member_id, {}, request)
    return clean_user(await db.users.find_one({"_id": target["_id"]}))


# Purpose: list task schedules handles the tasks feature flow and returns its API result.
@router.get("/api/task-schedules")
async def list_task_schedules(actor: dict = Depends(allow("Founder", "Core Management"))):
    docs = await db.daily_task_schedules.find({"deleted_at": {"$exists": False}}).sort("created_at", -1).limit(200).to_list(200)
    return [{
        "id": str(doc["_id"]), "title": doc.get("title", "Daily task"),
        "assignment_mode": doc.get("assignment_mode", "individual"),
        "active": bool(doc.get("active", True)), "start_date": doc.get("start_date"),
        "last_generated_date": doc.get("last_generated_date"),
        "created_by_name": doc.get("created_by_name", "Management"),
    } for doc in docs]


# Purpose: toggle task schedule handles the tasks feature flow and returns its API result.
@router.post("/api/task-schedules/{schedule_id}/toggle")
async def toggle_task_schedule(schedule_id: str, request: Request, actor: dict = Depends(allow("Founder", "Core Management"))):
    schedule = await db.daily_task_schedules.find_one({"_id": oid(schedule_id), "deleted_at": {"$exists": False}})
    if not schedule:
        raise HTTPException(404, "Daily schedule not found")
    active = not bool(schedule.get("active", True))
    await db.daily_task_schedules.update_one({"_id": schedule["_id"]}, {"$set": {"active": active, "updated_at": utcnow()}})
    await audit(actor, "daily_schedule_" + ("resumed" if active else "paused"), schedule_id, {}, request)
    return {"message": "Daily task schedule " + ("resumed" if active else "paused"), "active": active}


# Purpose: delete task schedule handles the tasks feature flow and returns its API result.
@router.delete("/api/task-schedules/{schedule_id}")
async def delete_task_schedule(schedule_id: str, request: Request, actor: dict = Depends(allow("Founder", "Core Management"))):
    schedule = await db.daily_task_schedules.find_one({"_id": oid(schedule_id), "deleted_at": {"$exists": False}})
    if not schedule:
        raise HTTPException(404, "Daily schedule not found")
    await db.daily_task_schedules.update_one({"_id": schedule["_id"]}, {"$set": {"active": False, "deleted_at": utcnow(), "deleted_by": actor["_id"]}})
    await audit(actor, "daily_schedule_deleted", schedule_id, {"title": schedule.get("title", "")}, request)
    return {"message": "Daily task schedule stopped. Generated tasks are kept."}


# Purpose: update task handles the tasks feature flow and returns its API result.
@router.patch("/api/tasks/{task_id}")
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
        await create_task_notification(
            reassigned_to, {**target, **changes},
            "Task assigned to you",
            f'{actor["name"]} assigned you "{target["title"]}".',
            "task_assigned",
            task_id=task_id,
            extra_details={"Assigned by": actor["name"]},
        )

    if changes.get("status") == "In progress" and target.get("status") == "Review":
        assignee = await db.users.find_one({"_id": target["assignee_id"]})
        if assignee:
            message = changes.get("review_feedback") or "Please update your submission evidence and send it for review again."
            await create_task_notification(
                assignee, {**target, **changes},
                "Task needs changes",
                f'{actor["name"]} returned "{target["title"]}" for changes: {message}',
                "task_changes_requested",
                task_id=task_id,
                extra_details={"Review feedback": message, "Reviewed by": actor["name"]},
            )

    if changes.get("status") == "Review":
        staff_roles = ["Founder"] if actor.get("role") == "Core Management" else ["Founder", "Core Management"]
        reviewers = await db.users.find({
            "role": {"$in": staff_roles},
            "status": "Active",
            "_id": {"$ne": actor["_id"]},
        }).to_list(200)
        for reviewer in reviewers:
            await create_task_notification(
                reviewer, {**target, **changes},
                "Task submission awaiting review",
                f'{actor["name"]} submitted "{target["title"]}" with screenshot evidence for review.',
                "task_review",
                task_id=task_id,
                extra_details={"Submitted by": actor["name"]},
            )

    await audit(actor, "task_updated", task_id, {"fields": list(changes)}, request)
    return clean_task(await db.tasks.find_one({"_id": target["_id"]}))

def attachment_signature_is_valid(content_type: str, data: bytes) -> bool:
    """Check basic file signatures so a renamed executable is not accepted as an image/PDF."""
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if mime == "image/webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if mime == "application/pdf":
        return data.startswith(b"%PDF-")
    if mime == "application/zip":
        return data.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))
    if mime == "text/plain":
        try:
            data.decode("utf-8")
            return b"\x00" not in data
        except UnicodeDecodeError:
            return False
    return False


# Purpose: upload task attachment handles the tasks feature flow and returns its API result.
@router.post("/api/tasks/{task_id}/attachments", status_code=201)
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
    if not attachment_signature_is_valid(file.content_type, data):
        raise HTTPException(415, "The file content does not match its declared type. Re-export the file and upload it again.")
    import uuid
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", file.filename or "attachment")[:120]
    stored = f"{uuid.uuid4().hex}_{safe_name}"
    storage_key = f"tasks/{task['_id']}/{stored}"
    try:
        storage_meta = await asyncio.to_thread(store_attachment, storage_key, data, file.content_type)
    except Exception as exc:
        logger.exception("Task attachment storage failed (task_id=%s backend=%s)", task_id, settings.attachment_storage_provider)
        raise HTTPException(503, "Attachment storage is unavailable. Check the backend storage configuration.") from exc
    doc = {
        "task_id": task["_id"], "filename": safe_name,
        "stored_name": storage_meta.get("stored_name"),
        "storage_backend": storage_meta.get("storage_backend", "local"),
        "storage_key": storage_meta.get("storage_key"),
        "content_type": file.content_type, "size": len(data),
        "uploaded_by": user["_id"], "created_at": utcnow(),
    }
    result = await db.attachments.insert_one(doc)
    await audit(user, "task_attachment_uploaded", str(result.inserted_id), {}, request)
    return {"id": str(result.inserted_id), "filename": safe_name, "content_type": file.content_type, "size": len(data)}

# Purpose: list task attachments handles the tasks feature flow and returns its API result.
@router.get("/api/tasks/{task_id}/attachments")
async def list_task_attachments(task_id: str, user: dict = Depends(get_current_user)):
    task = await db.tasks.find_one({"_id": oid(task_id)})
    if not task:
        raise HTTPException(404, "Task not found")
    if user["role"] not in PRIVILEGED and task["assignee_id"] != user["_id"]:
        raise HTTPException(403, "You cannot view attachments for this task")
    rows = await db.attachments.find({"task_id": task["_id"]}).sort("created_at", -1).to_list(100)
    return [{"id":str(x["_id"]), "filename":x["filename"], "content_type":x["content_type"], "size":x["size"], "created_at":x["created_at"]} for x in rows]

# Purpose: download attachment handles the tasks feature flow and returns its API result.
@router.get("/api/attachments/{attachment_id}/download")
async def download_attachment(attachment_id: str, user: dict = Depends(get_current_user)):
    item = await db.attachments.find_one({"_id": oid(attachment_id)})
    if not item:
        raise HTTPException(404, "Attachment not found")
    task = await db.tasks.find_one({"_id": item["task_id"]})
    if not task or (user["role"] not in PRIVILEGED and task["assignee_id"] != user["_id"]):
        raise HTTPException(403, "You cannot download this attachment")
    try:
        data = await asyncio.to_thread(read_attachment, item)
    except FileNotFoundError:
        raise HTTPException(404, "Attachment file is missing")
    except Exception as exc:
        logger.exception("Task attachment download failed (attachment_id=%s)", attachment_id)
        raise HTTPException(503, "Attachment storage is currently unavailable.") from exc
    safe_filename = re.sub(r"[^a-zA-Z0-9._-]", "_", item.get("filename") or "attachment")[:120]
    return StreamingResponse(
        iter([data]),
        media_type=item.get("content_type") or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )

# Purpose: get task comments handles the tasks feature flow and returns its API result.
@router.get("/api/tasks/{task_id}/comments")
async def get_task_comments(task_id: str, user: dict = Depends(get_current_user)):
    task = await db.tasks.find_one({"_id": oid(task_id)})
    if not task:
        raise HTTPException(404, "Task not found")
    if user["role"] not in PRIVILEGED and task["assignee_id"] != user["_id"]:
        raise HTTPException(403, "You cannot view comments for this task")
    rows = await db.task_comments.find({"task_id": task["_id"]}).sort("created_at", 1).to_list(300)
    return [{"id": str(x["_id"]), "author": x["author"], "role": x["role"], "text": x["text"], "created_at": x["created_at"]} for x in rows]

# Purpose: add task comment handles the tasks feature flow and returns its API result.
@router.post("/api/tasks/{task_id}/comments", status_code=201)
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
    if user.get("role") in PRIVILEGED:
        recipient = await db.users.find_one({
            "_id": task.get("assignee_id"),
            "status": "Active",
        })
        if recipient and recipient["_id"] != user["_id"]:
            await create_task_notification(
                recipient, task,
                "New comment on your TechNova task",
                f'{user["name"]} commented on "{task.get("title", "your task")}": {text.strip()}',
                "task_comment",
                task_id=task_id,
                extra_details={"New comment": text.strip(), "Comment by": user["name"]},
            )
    else:
        creator_id = task.get("created_by")
        recipient = await db.users.find_one({"_id": creator_id, "status": "Active"}) if creator_id else None
        if recipient and recipient["_id"] != user["_id"]:
            await create_task_notification(
                recipient, task,
                "New comment on an assigned task",
                f'{user["name"]} commented on "{task.get("title", "task")}": {text.strip()}',
                "task_comment",
                task_id=task_id,
                extra_details={"New comment": text.strip(), "Comment by": user["name"]},
            )
        elif not recipient:
            reviewers = await db.users.find({
                "role": {"$in": ["Founder", "Core Management"]},
                "status": "Active",
                "_id": {"$ne": user["_id"]},
            }).limit(50).to_list(50)
            for reviewer in reviewers:
                await create_task_notification(
                    reviewer, task,
                    "New comment on an assigned task",
                    f'{user["name"]} commented on "{task.get("title", "task")}": {text.strip()}',
                    "task_comment",
                    task_id=task_id,
                    extra_details={"New comment": text.strip(), "Comment by": user["name"]},
                )
    await audit(user, "task_comment_added", task_id, {}, request)
    return {"id": str(result.inserted_id), "author": doc["author"], "role": doc["role"], "text": doc["text"], "created_at": doc["created_at"]}


"""MongoDB client and database index setup for the TechNova backend.

All route and service modules share the same configured async client/database.
"""

from motor.motor_asyncio import AsyncIOMotorClient
from .config import settings

client = AsyncIOMotorClient(settings.mongodb_uri, serverSelectionTimeoutMS=8000)
db = client[settings.database_name]


def partial_object_id_index_is_current(existing: dict | None, field_name: str) -> bool:
    """Check whether a unique schedule index excludes null/missing IDs."""
    return bool(
        existing
        and existing.get("unique") is True
        and existing.get("partialFilterExpression") == {
            field_name: {"$type": "objectId"}
        }
    )


async def ensure_partial_object_id_unique_index(
    collection,
    keys: list[tuple[str, int]],
    index_name: str,
    field_name: str,
) -> None:
    """Replace the old $exists:true index, which incorrectly indexed null IDs."""
    existing = (await collection.index_information()).get(index_name)
    if existing and not partial_object_id_index_is_current(existing, field_name):
        # The old partial filter included documents with field: null. Dropping only
        # this known index is required before recreating it with the safe BSON type filter.
        await collection.drop_index(index_name)

    await collection.create_index(
        keys,
        unique=True,
        name=index_name,
        partialFilterExpression={field_name: {"$type": "objectId"}},
    )


async def ensure_indexes():
    """Create the unique and query indexes required by portal workflows."""
    await db.users.create_index("email", unique=True)
    await db.users.create_index("member_id", unique=True)
    # Verified phone numbers belong to one active account; missing values are not indexed.
    await db.users.create_index("phone_number", unique=True, sparse=True)
    await db.cards.create_index("token_hash", unique=True, sparse=True)
    await db.cards.create_index("member_id")
    await db.tasks.create_index([("assignee_id", 1), ("status", 1)])
    await db.tasks.create_index("created_at")
    await db.tasks.create_index("auto_generation_key", unique=True, sparse=True)
    await db.tasks.create_index([("status", 1), ("assignee_id", 1), ("credits_awarded", 1)])
    # Only actual ObjectId schedule references should participate in these
    # uniqueness constraints. The former $exists:true filter also indexed null
    # values and caused all ordinary tasks for one assignee to collide.
    await ensure_partial_object_id_unique_index(
        db.tasks,
        [("daily_schedule_id", 1), ("occurrence_date", 1), ("assignee_id", 1)],
        "daily_schedule_id_1_occurrence_date_1_assignee_id_1",
        "daily_schedule_id",
    )
    await ensure_partial_object_id_unique_index(
        db.common_tasks,
        [("daily_schedule_id", 1), ("occurrence_date", 1)],
        "daily_schedule_id_1_occurrence_date_1",
        "daily_schedule_id",
    )
    await db.daily_task_schedules.create_index([("active", 1), ("start_date", 1)])
    await db.credit_penalties.create_index("reference_key", unique=True)
    await db.credit_penalties.create_index([("user_id", 1), ("created_at", -1)])
    await db.tasks.create_index(
        [("common_task_id", 1), ("assignee_id", 1)],
        unique=True,
        partialFilterExpression={"common_task_id": {"$exists": True}},
    )
    await db.notifications.create_index([("user_id", 1), ("created_at", -1)])
    await db.push_tokens.create_index("token", unique=True)
    await db.push_tokens.create_index([("user_id", 1), ("updated_at", -1)])
    await db.common_tasks.create_index("created_at")
    await db.common_tasks.create_index("auto_generation_key", unique=True, sparse=True)
    await db.common_task_responses.create_index(
        [("common_task_id", 1), ("user_id", 1)],
        unique=True,
    )
    await db.teams.create_index("name", unique=True)
    await db.audit.create_index("created_at")

    await db.password_resets.create_index("token_hash", unique=True)
    await db.password_resets.create_index("expires_at", expireAfterSeconds=0)
    await db.auth_challenges.create_index("token_hash", unique=True)
    await db.auth_challenges.create_index("expires_at", expireAfterSeconds=0)
    await db.trusted_devices.create_index("token_hash", unique=True)
    await db.trusted_devices.create_index([("user_id", 1), ("expires_at", 1)])
    await db.trusted_devices.create_index("expires_at", expireAfterSeconds=0)
    await db.task_comments.create_index([("task_id", 1), ("created_at", 1)])
    await db.attachments.create_index([("task_id", 1), ("created_at", -1)])

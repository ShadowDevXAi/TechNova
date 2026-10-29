from motor.motor_asyncio import AsyncIOMotorClient
from .config import settings

client = AsyncIOMotorClient(settings.mongodb_uri, serverSelectionTimeoutMS=8000)
db = client[settings.database_name]

async def ensure_indexes():
    await db.users.create_index("email", unique=True)
    await db.users.create_index("member_id", unique=True)
    await db.cards.create_index("token_hash", unique=True, sparse=True)
    await db.cards.create_index("member_id")
    await db.tasks.create_index([("assignee_id", 1), ("status", 1)])
    await db.tasks.create_index("created_at")
    await db.teams.create_index("name", unique=True)
    await db.audit.create_index("created_at")

    await db.password_resets.create_index("token_hash", unique=True)
    await db.password_resets.create_index("expires_at", expireAfterSeconds=0)
    await db.task_comments.create_index([("task_id", 1), ("created_at", 1)])
    await db.attachments.create_index([("task_id", 1), ("created_at", -1)])

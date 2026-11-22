"""Private ID-card photo storage in MongoDB GridFS.

Image bytes live in a dedicated GridFS bucket in the existing TechNova database.
The card_photos collection stores only owner metadata and the GridFS file ID.
"""
from __future__ import annotations

from bson import ObjectId
from gridfs.errors import NoFile
from gridfs import GridFSBucket

from .db import db

BUCKET_NAME = "id_card_photos"


def _bucket() -> GridFSBucket:
    return GridFSBucket(db, bucket_name=BUCKET_NAME)


async def store_id_card_photo(owner_id: ObjectId, data: bytes) -> dict:
    bucket = _bucket()
    file_id = await bucket.upload_from_stream(
        f"{owner_id}.jpg",
        data,
        metadata={"owner_id": owner_id, "purpose": "technova_id_card_photo", "content_type": "image/jpeg"},
    )
    return {"storage_backend": "mongodb_gridfs", "gridfs_id": file_id}


async def read_id_card_photo(record: dict) -> bytes:
    file_id = record.get("gridfs_id")
    if not isinstance(file_id, ObjectId):
        raise FileNotFoundError("MongoDB GridFS photo reference is missing")
    try:
        return await _bucket().open_download_stream(file_id).read()
    except NoFile as exc:
        raise FileNotFoundError("MongoDB GridFS photo does not exist") from exc


async def delete_id_card_photo(record: dict) -> None:
    file_id = record.get("gridfs_id")
    if not isinstance(file_id, ObjectId):
        raise ValueError("MongoDB GridFS photo reference is missing")
    try:
        await _bucket().delete(file_id)
    except NoFile:
        # Idempotent cleanup: metadata may outlive an already removed GridFS file.
        return

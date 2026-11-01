"""Task-attachment storage adapters.

Local disk is retained for development/backward compatibility. Production can use
any S3-compatible object store, including Cloudflare R2, with private objects.
"""
from __future__ import annotations
import logging
import os
from pathlib import Path
from .config import settings

logger = logging.getLogger("technova.storage")
LOCAL_UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/app/uploads"))

def attachment_storage_status() -> dict:
    """Return safe storage readiness without exposing object-store credentials."""
    provider = (settings.attachment_storage_provider or "local").strip().lower()
    if provider == "local":
        return {
            "provider": "Local disk", "configured": True, "durable": False,
            "message": "Local storage can be lost when the host replaces the container. Configure S3-compatible storage for production.",
        }
    if provider != "s3":
        return {
            "provider": provider, "configured": False, "durable": False,
            "missing": ["ATTACHMENT_STORAGE_PROVIDER must be local or s3"],
        }
    missing = []
    for field, value in (
        ("S3_BUCKET", settings.s3_bucket),
        ("S3_ACCESS_KEY_ID", settings.s3_access_key_id),
        ("S3_SECRET_ACCESS_KEY", settings.s3_secret_access_key),
        ("S3_ENDPOINT_URL", settings.s3_endpoint_url),
    ):
        if not str(value or "").strip():
            missing.append(field)
    return {
        "provider": "S3-compatible object storage", "configured": not missing,
        "durable": not missing, "bucket": settings.s3_bucket.strip() or None,
        "endpoint_configured": bool(settings.s3_endpoint_url.strip()),
        "region": settings.s3_region, "missing": missing,
        "message": "Private object storage is ready." if not missing else "Add the missing bucket and access settings to the backend environment.",
    }

def _s3_client():
    status = attachment_storage_status()
    if not status["configured"] or status["provider"] != "S3-compatible object storage":
        missing = ", ".join(status.get("missing", [])) or "ATTACHMENT_STORAGE_PROVIDER=s3"
        raise RuntimeError(f"S3 attachment storage is not configured: {missing}")
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url.strip(),
        region_name=settings.s3_region.strip() or "auto",
        aws_access_key_id=settings.s3_access_key_id.strip(),
        aws_secret_access_key=settings.s3_secret_access_key.strip(),
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )

def store_attachment(storage_key: str, data: bytes, content_type: str) -> dict:
    """Store private attachment bytes and return safe storage metadata."""
    provider = (settings.attachment_storage_provider or "local").strip().lower()
    if provider == "s3":
        _s3_client().put_object(
            Bucket=settings.s3_bucket.strip(), Key=storage_key, Body=data,
            ContentType=content_type, ServerSideEncryption="AES256",
        )
        return {"storage_backend": "s3", "storage_key": storage_key, "stored_name": None}
    if provider != "local":
        raise RuntimeError("ATTACHMENT_STORAGE_PROVIDER must be local or s3")
    LOCAL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = LOCAL_UPLOAD_DIR / Path(storage_key).name
    path.write_bytes(data)
    return {"storage_backend": "local", "storage_key": None, "stored_name": path.name}

def read_attachment(item: dict) -> bytes:
    """Read an attachment from its recorded backend; legacy records remain local."""
    if item.get("storage_backend") == "s3":
        response = _s3_client().get_object(Bucket=settings.s3_bucket.strip(), Key=item["storage_key"])
        return response["Body"].read()
    stored_name = Path(str(item.get("stored_name") or "")).name
    if not stored_name:
        raise FileNotFoundError("Attachment storage key is missing")
    return (LOCAL_UPLOAD_DIR / stored_name).read_bytes()

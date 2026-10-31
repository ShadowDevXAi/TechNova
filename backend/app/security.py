"""Password hashing, access-token signing and digital-ID token helpers.

Keep cryptographic operations in this module so route handlers do not implement
password or token handling independently.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import secrets
from jose import jwt, JWTError
from pwdlib import PasswordHash
from .config import settings

ALGORITHM = "HS256"
password_hash = PasswordHash.recommended()

def hash_password(password: str) -> str:
    """Create a secure password hash for database storage."""
    return password_hash.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    """Check a login password against its stored hash without exposing hash errors."""
    try:
        return password_hash.verify(password, hashed)
    except Exception:
        return False

def create_access_token(subject: str, role: str) -> str:
    """Sign a time-limited JWT containing the member ID and role."""
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": subject, "role": role, "iat": now, "exp": now + timedelta(minutes=settings.jwt_expire_minutes)}, settings.jwt_secret, algorithm=ALGORITHM)

def decode_access_token(token: str) -> dict:
    """Verify a JWT signature and expiry, then return its claims."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])

def new_card_token() -> str:
    """Generate an unguessable secret for a digital ID card."""
    return secrets.token_urlsafe(32)

def token_hash(token: str) -> str:
    """Hash a raw card token before storing or looking it up in MongoDB."""
    return sha256(token.encode("utf-8")).hexdigest()

def utcnow() -> datetime:
    """Return the current UTC timestamp for consistent database records."""
    return datetime.now(timezone.utc)

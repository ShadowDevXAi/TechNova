from datetime import datetime, timedelta, timezone
from hashlib import sha256
import secrets
from jose import jwt, JWTError
from pwdlib import PasswordHash
from .config import settings

ALGORITHM = "HS256"
password_hash = PasswordHash.recommended()

def hash_password(password: str) -> str:
    return password_hash.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    try:
        return password_hash.verify(password, hashed)
    except Exception:
        return False

def create_access_token(subject: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": subject, "role": role, "iat": now, "exp": now + timedelta(minutes=settings.jwt_expire_minutes)}, settings.jwt_secret, algorithm=ALGORITHM)

def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])

def new_card_token() -> str:
    return secrets.token_urlsafe(32)

def token_hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

"""Authentication and member-profile endpoints.

Registration, login, password recovery, session identity, dashboard and credit ledger.

All protected operations reuse authentication and role checks from app.core.
"""

import secrets
from datetime import timedelta, timezone


def normalize_utc_datetime(value):
    """Normalize MongoDB UTC datetimes before comparing with aware UTC values."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

import pyotp
from jose import JWTError, jwt
from fastapi import APIRouter
from ..core import *  # Shared database, schemas, authorization and business helpers.

router = APIRouter()

# Purpose: register handles the auth feature flow and returns its API result.
@router.post("/api/auth/register", status_code=201)
@limiter.limit("8/hour")
async def register(data: RegisterIn, request: Request):
    email = str(data.email).lower()
    if await db.users.find_one({"email":email}):
        raise HTTPException(409,"An account with this email already exists")
    # Public signups can only create pending Member accounts. They must verify email before login/approval.
    member_id = await next_member_id("Member")
    doc = {
        "member_id": member_id, "name": data.name.strip(), "email": email,
        "password_hash": hash_password(data.password), "role": "Member",
        "team": data.team.strip() or "Unassigned", "status": "Pending",
        "created_at": utcnow(), "approved_at": None,
        "email_verification_required": True, "email_verified_at": None,
    }
    try:
        result = await db.users.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "Could not allocate member ID; please retry")

    verification_token = secrets.token_urlsafe(32)
    await db.email_verifications.insert_one({
        "user_id": result.inserted_id,
        "token_hash": token_hash(verification_token),
        "created_at": utcnow(),
        "expires_at": utcnow() + timedelta(hours=24),
    })
    verification_url = settings.public_app_url.rstrip("/") + "/?verify_email=" + verification_token
    try:
        await asyncio.to_thread(
            send_email_message,
            email,
            "Verify your TechNova email address",
            "Welcome to TechNova. Verify this email address to continue your club registration:\n\n"
            + verification_url
            + "\n\nThis link expires in 24 hours. If you did not register, you can ignore this email.",
        )
        email_delivery_status = "sent"
    except Exception as exc:
        email_delivery_status = "failed"
        logger.error("Registration verification email failed (user_id=%s error_type=%s)", result.inserted_id, type(exc).__name__)

    # Keep the receipt in the in-app inbox without sending a duplicate email before verification.
    await db.notifications.insert_one({
        "user_id": result.inserted_id,
        "type": "registration_received",
        "title": "Verify your TechNova email",
        "message": "A verification link was sent to your email if delivery is configured. Verify it before account approval.",
        "task_id": None,
        "common_task_id": None,
        "read_at": None,
        "created_at": utcnow(),
        "email_delivery": {"status": "skipped_verification_pending", "updated_at": utcnow()},
        "sms_delivery": {"status": "skipped_not_enabled", "updated_at": utcnow()},
    })
    managers = await db.users.find({
        "role": {"$in": ["Founder", "Core Management"]},
        "status": "Active",
    }).limit(100).to_list(100)
    for manager in managers:
        await create_notification(
            manager,
            "New member registration awaiting approval",
            f'{doc["name"]} ({doc["member_id"]}) has registered and is waiting for TechNova account approval.',
            "registration_pending",
        )
    await audit(None,"registration_submitted",str(result.inserted_id),{"email":email},request)
    return {"message":"Registration received. Check your inbox to verify your email. After verification, a club administrator must approve your account before you can sign in.","member_id":doc["member_id"]}

# Purpose: login handles the auth feature flow and returns its API result.
@router.post("/api/auth/login")
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
    if user.get("email_verification_required") and not user.get("email_verified_at"):
        raise HTTPException(
            403,
            "Verify your email address before signing in. Use 'Resend verification email' on the sign-in screen if you need a new link.",
        )
    if user["status"] != "Active":
        raise HTTPException(403,"Your account is pending approval or unavailable")
    if user.get("role") in {"Founder", "Core Management"}:
        if not user.get("two_factor_enabled"):
            setup_token = await _create_two_factor_flow_token(user, "setup", minutes=10)
            return {
                "two_factor_setup_required": True,
                "setup_token": setup_token,
                "message": "Management accounts must enroll an authenticator app before entering TechNova.",
            }

        remembered = str(data.trusted_device_token or "").strip()
        if remembered:
            device = await db.trusted_devices.find_one({
                "user_id": user["_id"],
                "token_hash": token_hash(remembered),
                "expires_at": {"$gt": utcnow()},
            })
            if device:
                await db.trusted_devices.update_one(
                    {"_id": device["_id"]},
                    {"$set": {"last_seen_at": utcnow()}},
                )
                token = create_access_token(str(user["_id"]), user["role"], mfa_verified=True)
                await audit(user, "login", str(user["_id"]), {"mfa": "trusted_device"}, request)
                return {"access_token": token, "token_type": "bearer", "user": clean_user(user)}

        challenge_token = await _create_two_factor_flow_token(user, "login", minutes=5)
        return {
            "two_factor_required": True,
            "challenge_token": challenge_token,
            "message": "Enter your authenticator code or a one-time recovery code.",
        }

    token = create_access_token(str(user["_id"]),user["role"])
    await audit(user,"login",str(user["_id"]),{},request)
    return {"access_token":token,"token_type":"bearer","user":clean_user(user)}

# Purpose: Create a short-lived, single-purpose challenge token for management MFA enrollment/login.
async def _create_two_factor_flow_token(user: dict, purpose: str, *, minutes: int) -> str:
    now = utcnow()
    challenge_id = secrets.token_urlsafe(24)
    await db.auth_challenges.insert_one({
        "token_hash": token_hash(challenge_id),
        "user_id": user["_id"],
        "purpose": purpose,
        "created_at": now,
        "expires_at": now + timedelta(minutes=minutes),
    })
    return jwt.encode(
        {
            "sub": str(user["_id"]),
            "purpose": purpose,
            "jti": challenge_id,
            "iat": now,
            "exp": now + timedelta(minutes=minutes),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


# Purpose: Verify a signed MFA flow token and retrieve its active management account.
async def _two_factor_flow_user(raw_token: str, expected_purpose: str) -> tuple[dict, str]:
    try:
        claims = jwt.decode(raw_token, settings.jwt_secret, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(401, "The two-factor session has expired. Sign in again.")
    if claims.get("purpose") != expected_purpose or not claims.get("jti"):
        raise HTTPException(401, "Invalid two-factor challenge.")
    user = await db.users.find_one({
        "_id": oid(claims.get("sub")),
        "status": "Active",
        "role": {"$in": ["Founder", "Core Management"]},
    })
    if not user:
        raise HTTPException(401, "Active management account not found.")
    challenge = await db.auth_challenges.find_one({
        "token_hash": token_hash(claims["jti"]),
        "user_id": user["_id"],
        "purpose": expected_purpose,
        "expires_at": {"$gt": utcnow()},
    })
    if not challenge:
        raise HTTPException(401, "The two-factor challenge has expired or was already used. Sign in again.")
    return user, claims["jti"]


# Purpose: Consume a one-time MFA challenge after the submitted authenticator factor is valid.
async def _consume_two_factor_challenge(user: dict, challenge_id: str, purpose: str) -> None:
    result = await db.auth_challenges.delete_one({
        "token_hash": token_hash(challenge_id),
        "user_id": user["_id"],
        "purpose": purpose,
        "expires_at": {"$gt": utcnow()},
    })
    if result.deleted_count != 1:
        raise HTTPException(409, "This two-factor challenge was already used. Sign in again.")


# Purpose: Issue an optional 30-day trusted-device token without storing its raw value.
async def _remember_two_factor_device(user: dict, request: Request) -> str:
    raw_token = secrets.token_urlsafe(36)
    now = utcnow()
    user_agent = (request.headers.get("user-agent") or "Unknown browser")[:300]
    await db.trusted_devices.insert_one({
        "user_id": user["_id"],
        "token_hash": token_hash(raw_token),
        "device_label": user_agent[:120],
        "user_agent": user_agent,
        "created_at": now,
        "last_seen_at": now,
        "expires_at": now + timedelta(days=30),
    })
    return raw_token


# Purpose: Start mandatory authenticator enrollment for Founder and Core Management.
@router.post("/api/auth/2fa/setup")
@limiter.limit("5/minute")
async def two_factor_setup(body: dict, request: Request):
    setup_token = str(body.get("setup_token") or "")
    user, _ = await _two_factor_flow_user(setup_token, "setup")
    if user.get("two_factor_enabled"):
        raise HTTPException(409, "Authenticator two-factor authentication is already enabled.")
    pending_secret = user.get("two_factor_pending_secret")
    pending_expiry = user.get("two_factor_pending_expires_at")
    if not pending_secret or not pending_expiry or normalize_utc_datetime(pending_expiry) <= utcnow():
        pending_secret = pyotp.random_base32()
        await db.users.update_one(
            {"_id": user["_id"]},
            {"$set": {
                "two_factor_pending_secret": pending_secret,
                "two_factor_pending_expires_at": utcnow() + timedelta(minutes=10),
            }},
        )
    issuer = "TechNova"
    provisioning_uri = pyotp.TOTP(pending_secret).provisioning_uri(
        name=str(user["email"]),
        issuer_name=issuer,
    )
    return {
        "issuer": issuer,
        "account": str(user["email"]),
        "secret": pending_secret,
        "provisioning_uri": provisioning_uri,
        "expires_in_minutes": 10,
        "mandatory": True,
    }


# Purpose: Enable management TOTP and issue one-time recovery codes plus the first MFA session.
@router.post("/api/auth/2fa/enable")
@limiter.limit("6/minute")
async def enable_two_factor(body: dict, request: Request):
    setup_token = str(body.get("setup_token") or "")
    user, challenge_id = await _two_factor_flow_user(setup_token, "setup")
    code = str(body.get("code") or "").strip().replace(" ", "")
    secret = user.get("two_factor_pending_secret")
    pending_expiry = user.get("two_factor_pending_expires_at")
    if not secret or not pending_expiry or normalize_utc_datetime(pending_expiry) <= utcnow():
        raise HTTPException(410, "Authenticator setup expired. Start login again.")
    if not pyotp.TOTP(secret).verify(code, valid_window=1):
        raise HTTPException(400, "That authenticator code is not valid. Check the phone's time and try again.")
    recovery_codes = [secrets.token_hex(4).upper() for _ in range(10)]
    await _consume_two_factor_challenge(user, challenge_id, "setup")
    await db.users.update_one(
        {"_id": user["_id"]},
        {
            "$set": {
                "two_factor_enabled": True,
                "two_factor_secret": secret,
                "two_factor_enabled_at": utcnow(),
                "two_factor_recovery_hashes": [token_hash(code) for code in recovery_codes],
            },
            "$unset": {
                "two_factor_pending_secret": "",
                "two_factor_pending_expires_at": "",
            },
        },
    )
    updated_user = await db.users.find_one({"_id": user["_id"]})
    trusted_device_token = None
    if body.get("remember_device") is True:
        trusted_device_token = await _remember_two_factor_device(updated_user, request)
    token = create_access_token(str(updated_user["_id"]), updated_user["role"], mfa_verified=True)
    await audit(updated_user, "two_factor_enabled", str(updated_user["_id"]), {
        "recovery_codes_issued": len(recovery_codes),
        "trusted_device_created": bool(trusted_device_token),
    }, request)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": clean_user(updated_user),
        "recovery_codes": recovery_codes,
        "trusted_device_token": trusted_device_token,
        "message": "Authenticator protection is enabled. Save your recovery codes now; they are shown only once.",
    }


# Purpose: Complete a management login using a TOTP or one unused recovery code.
@router.post("/api/auth/2fa/login")
@limiter.limit("6/minute")
async def verify_two_factor_login(body: dict, request: Request):
    challenge_token = str(body.get("challenge_token") or "")
    user, challenge_id = await _two_factor_flow_user(challenge_token, "login")
    if not user.get("two_factor_enabled") or not user.get("two_factor_secret"):
        raise HTTPException(409, "Authenticator enrollment is required. Sign in again.")
    code = str(body.get("code") or "").strip().replace(" ", "")
    recovery_code = str(body.get("recovery_code") or "").strip().replace("-", "").replace(" ", "").upper()
    used_recovery = False
    if recovery_code:
        candidate_hash = token_hash(recovery_code)
        recovery_hashes = user.get("two_factor_recovery_hashes") or []
        if candidate_hash not in recovery_hashes:
            raise HTTPException(401, "Recovery code is invalid or already used.")
        consumed = await db.users.update_one(
            {"_id": user["_id"], "two_factor_recovery_hashes": candidate_hash},
            {"$pull": {"two_factor_recovery_hashes": candidate_hash}},
        )
        if consumed.modified_count != 1:
            raise HTTPException(401, "Recovery code is invalid or already used.")
        used_recovery = True
    elif not pyotp.TOTP(user["two_factor_secret"]).verify(code, valid_window=1):
        raise HTTPException(401, "Authenticator code is incorrect. Try again or use a recovery code.")
    await _consume_two_factor_challenge(user, challenge_id, "login")
    token = create_access_token(str(user["_id"]), user["role"], mfa_verified=True)
    trusted_device_token = None
    if body.get("remember_device") is True:
        trusted_device_token = await _remember_two_factor_device(user, request)
    remaining = max(0, len(user.get("two_factor_recovery_hashes") or []) - (1 if used_recovery else 0))
    await audit(user, "login", str(user["_id"]), {
        "mfa": "recovery_code" if used_recovery else "authenticator",
        "trusted_device_created": bool(trusted_device_token),
    }, request)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": clean_user(user),
        "trusted_device_token": trusted_device_token,
        "recovery_codes_remaining": remaining,
    }


# Purpose: Report management MFA and trusted-device state without exposing token material.
@router.get("/api/auth/2fa/status")
async def two_factor_status(user: dict = Depends(get_current_user)):
    if user.get("role") not in {"Founder", "Core Management"}:
        raise HTTPException(403, "Two-factor management settings are for management accounts.")
    recovery_count = len(user.get("two_factor_recovery_hashes") or [])
    trusted_count = await db.trusted_devices.count_documents({
        "user_id": user["_id"],
        "expires_at": {"$gt": utcnow()},
    })
    return {
        "enabled": bool(user.get("two_factor_enabled")),
        "mandatory": True,
        "recovery_codes_remaining": recovery_count,
        "trusted_devices": trusted_count,
        "issuer": "TechNova",
    }


# Purpose: List only the signed-in management account's trusted browsers.
@router.get("/api/auth/2fa/devices")
async def list_two_factor_devices(user: dict = Depends(get_current_user)):
    if user.get("role") not in {"Founder", "Core Management"}:
        raise HTTPException(403, "Two-factor management settings are for management accounts.")
    rows = await db.trusted_devices.find({
        "user_id": user["_id"],
        "expires_at": {"$gt": utcnow()},
    }).sort("last_seen_at", -1).limit(50).to_list(50)
    return [{
        "id": str(row["_id"]),
        "device": row.get("device_label", "Trusted browser"),
        "created_at": row.get("created_at"),
        "last_seen_at": row.get("last_seen_at"),
        "expires_at": row.get("expires_at"),
    } for row in rows]


# Purpose: Revoke one trusted browser so its stored token cannot bypass the next MFA challenge.
@router.delete("/api/auth/2fa/devices/{device_id}")
async def revoke_two_factor_device(device_id: str, request: Request, user: dict = Depends(get_current_user)):
    if user.get("role") not in {"Founder", "Core Management"}:
        raise HTTPException(403, "Two-factor management settings are for management accounts.")
    result = await db.trusted_devices.delete_one({
        "_id": oid(device_id),
        "user_id": user["_id"],
    })
    if result.deleted_count != 1:
        raise HTTPException(404, "Trusted device not found.")
    await audit(user, "trusted_device_revoked", device_id, {}, request)
    return {"message": "Trusted device revoked. It must complete two-factor verification next time."}


# Purpose: Return safe contact and notification-preference settings for the signed-in account.
@router.get("/api/auth/contact/status")
async def contact_notification_status(user: dict = Depends(get_current_user)):
    phone = str(user.get("phone_number") or "")
    preferences = user.get("notification_preferences") or {}
    return {
        "phone_verified": bool(user.get("phone_verified_at")),
        "phone_masked": ("+" + "*" * max(0, len(phone) - 4) + phone[-4:]) if phone else None,
        "sms_consent": bool(user.get("sms_consent_at")),
        "preferences": {
            "email_enabled": preferences.get("email_enabled", True) is not False,
            "push_enabled": preferences.get("push_enabled", True) is not False,
            "sms_enabled": preferences.get("sms_enabled") is True,
        },
        "phone_verification_enabled": settings.phone_verification_enabled,
        "sms_provider": sms_configuration_status(),
    }


# Purpose: Send an opt-in phone verification code; no SMS alert preference is enabled yet.
@router.post("/api/auth/contact/phone/request")
@limiter.limit("3/hour")
async def request_phone_verification(body: dict, request: Request, user: dict = Depends(get_current_user)):
    """
    Start (or resend) phone verification for the signed-in account.

    Flow:
    1. Validate the international-format phone number and explicit SMS consent.
    2. Confirm the SMS provider is configured and the number is not verified elsewhere.
    3. Enforce a 60-second resend cooldown (plus the route's hourly rate limit).
    4. Generate a six-digit OTP, store only its hash, and set a 10-minute expiry.
    5. Send the OTP through Brevo. If delivery fails, remove the pending OTP data.

    Calling this endpoint again after the cooldown sends a fresh code and
    replaces the previous pending code; the previous code can no longer verify.
    """
    # Feature is intentionally paused. Remove this guard only when the owner activates phone verification.
    if not settings.phone_verification_enabled:
        raise HTTPException(503, "Phone verification is temporarily disabled by the TechNova owner.")
    phone = str(body.get("phone_number") or "").strip()
    consent = body.get("consent") is True
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", phone):
        raise HTTPException(422, "Enter a phone number in international format, for example +919876543210.")
    if not consent:
        raise HTTPException(422, "Explicit consent is required before sending a phone-verification SMS.")
    if not sms_configuration_status()["configured"]:
        raise HTTPException(503, "Transactional SMS is not configured. Ask the Founder to configure Brevo SMS sender settings.")
    existing = await db.users.find_one({
        "phone_number": phone,
        "phone_verified_at": {"$exists": True},
        "status": "Active",
        "_id": {"$ne": user["_id"]},
    })
    if existing:
        raise HTTPException(409, "This verified phone number is already linked to another active TechNova account.")
    last_requested = user.get("phone_verification_requested_at")
    if last_requested and (utcnow() - normalize_utc_datetime(last_requested)).total_seconds() < 60:
        raise HTTPException(429, "Please wait at least 60 seconds before requesting another verification code.")
    # Generate a cryptographically random six-digit OTP; never store the raw code in MongoDB.
    code = f"{secrets.randbelow(1_000_000):06d}"
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {
            "phone_number_pending": phone,
            "phone_verification_code_hash": token_hash(code),  # Compare hashes during confirmation.
            "phone_verification_expires_at": utcnow() + timedelta(minutes=10),  # OTP expires after 10 minutes.
            "phone_verification_requested_at": utcnow(),
        }},
    )
    # Send SMS outside the async event loop so the network request does not block other API work.
    try:
        receipt = await asyncio.to_thread(
            send_brevo_sms_message,
            phone,
            f"TechNova verification code: {code}. It expires in 10 minutes.",
        )
    except Exception as exc:
        await db.users.update_one(
            {"_id": user["_id"]},
            {"$unset": {
                "phone_number_pending": "",
                "phone_verification_code_hash": "",
                "phone_verification_expires_at": "",
            }},
        )
        logger.error("Phone verification SMS failed (user_id=%s error_type=%s)", user["_id"], type(exc).__name__)
        raise HTTPException(502, "Could not send the verification SMS. Check Brevo transactional SMS settings and credits.") from exc
    await audit(user, "phone_verification_sms_requested", str(user["_id"]), {
        "phone_suffix": phone[-4:],
        "provider": receipt.get("provider"),
    }, request)
    return {"message": "Verification code sent. It expires in 10 minutes.", "expires_in_minutes": 10}


# Purpose: Verify the SMS code and record explicit consent for transactional club alerts.
@router.post("/api/auth/contact/phone/confirm")
@limiter.limit("6/hour")
async def confirm_phone_verification(body: dict, request: Request, user: dict = Depends(get_current_user)):
    """
    Confirm the OTP sent to the pending phone number.

    Reject malformed, missing, expired, or incorrect codes. On success, move
    the pending number into the verified account field, record consent, clear
    all temporary OTP data, and leave SMS alerts disabled until separately
    enabled in notification preferences.
    """
    # Feature is intentionally paused. Remove this guard only when the owner activates phone verification.
    if not settings.phone_verification_enabled:
        raise HTTPException(503, "Phone verification is temporarily disabled by the TechNova owner.")
    code = str(body.get("code") or "").strip()
    pending_phone = user.get("phone_number_pending")
    expected_hash = user.get("phone_verification_code_hash")
    expires_at = user.get("phone_verification_expires_at")
    if not re.fullmatch(r"[0-9]{6}", code):
        raise HTTPException(422, "Enter the six-digit verification code.")
    # Normalize MongoDB timestamps before comparing expiry with timezone-aware UTC.
    if not pending_phone or not expected_hash or not expires_at or normalize_utc_datetime(expires_at) <= utcnow():
        raise HTTPException(410, "The phone verification code has expired. Request another code.")
    # Constant-time hash comparison avoids comparing the submitted OTP with a stored plaintext value.
    if not secrets.compare_digest(token_hash(code), expected_hash):
        raise HTTPException(400, "The phone verification code is incorrect.")
    try:
        await db.users.update_one(
            {"_id": user["_id"]},
            {
                "$set": {
                    "phone_number": pending_phone,
                    "phone_verified_at": utcnow(),
                    "sms_consent_at": utcnow(),
                    "notification_preferences.sms_enabled": False,  # Verification does not silently opt the user into alerts.
                },
                "$unset": {
                    "phone_number_pending": "",
                    "phone_verification_code_hash": "",
                    "phone_verification_expires_at": "",
                },
            },
        )
    except DuplicateKeyError:
        raise HTTPException(409, "This phone number is already verified on another TechNova account.")
    await audit(user, "phone_number_verified", str(user["_id"]), {"phone_suffix": pending_phone[-4:]}, request)
    return {"message": "Phone number verified. SMS alerts remain off until you enable them in Settings."}


# Purpose: Update per-channel notification preferences with server-enforced SMS consent checks.
@router.patch("/api/auth/contact/preferences")
async def update_contact_notification_preferences(body: dict, request: Request, user: dict = Depends(get_current_user)):
    allowed = {"email_enabled", "push_enabled", "sms_enabled"}
    changes = {key: body[key] for key in allowed if key in body}
    if not changes or any(not isinstance(value, bool) for value in changes.values()):
        raise HTTPException(422, "Provide one or more boolean notification preferences.")
    current = user.get("notification_preferences") or {}
    updated = {
        "email_enabled": current.get("email_enabled", True) is not False,
        "push_enabled": current.get("push_enabled", True) is not False,
        "sms_enabled": current.get("sms_enabled") is True,
        **changes,
    }
    if updated["sms_enabled"] and not settings.phone_verification_enabled:
        raise HTTPException(503, "SMS notifications are temporarily disabled by the TechNova owner.")
    if updated["sms_enabled"] and not (user.get("phone_verified_at") and user.get("sms_consent_at") and user.get("phone_number")):
        raise HTTPException(409, "Verify your phone number and give SMS consent before enabling SMS alerts.")
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"notification_preferences": updated}},
    )
    await audit(user, "notification_preferences_updated", str(user["_id"]), {
        "email_enabled": updated["email_enabled"],
        "push_enabled": updated["push_enabled"],
        "sms_enabled": updated["sms_enabled"],
    }, request)
    return {"message": "Notification preferences saved.", "preferences": updated}


# Purpose: Remove an account phone number and revoke SMS permission.
@router.delete("/api/auth/contact/phone")
async def remove_verified_phone(request: Request, user: dict = Depends(get_current_user)):
    await db.users.update_one(
        {"_id": user["_id"]},
        {
            "$unset": {
                "phone_number": "",
                "phone_verified_at": "",
                "sms_consent_at": "",
                "phone_number_pending": "",
                "phone_verification_code_hash": "",
                "phone_verification_expires_at": "",
                "phone_verification_requested_at": "",
            },
            "$set": {"notification_preferences.sms_enabled": False},
        },
    )
    await audit(user, "phone_number_removed", str(user["_id"]), {}, request)
    return {"message": "Phone number removed and SMS alerts disabled."}


# Purpose: Resend a fresh expiring verification link without revealing whether an email is registered.
@router.post("/api/auth/email-verification/resend")
@limiter.limit("3/hour")
async def resend_email_verification(body: dict, request: Request):
    email = str(body.get("email") or "").strip().lower()
    response = {"message": "If this account needs verification, a new link will be sent when email delivery is available."}
    if not email or len(email) > 320:
        return response
    user = await db.users.find_one({
        "email": email,
        "email_verification_required": True,
        "email_verified_at": None,
        "status": {"$ne": "Suspended"},
    })
    if not user or not smtp_configuration_status()["configured"]:
        return response
    verification_token = secrets.token_urlsafe(32)
    await db.email_verifications.delete_many({"user_id": user["_id"]})
    await db.email_verifications.insert_one({
        "user_id": user["_id"],
        "token_hash": token_hash(verification_token),
        "created_at": utcnow(),
        "expires_at": utcnow() + timedelta(hours=24),
    })
    verification_url = settings.public_app_url.rstrip("/") + "/?verify_email=" + verification_token
    try:
        await asyncio.to_thread(
            send_email_message,
            email,
            "Verify your TechNova email address",
            "Use this link to verify your TechNova account email address:\n\n"
            + verification_url
            + "\n\nThis link expires in 24 hours. If you did not request it, ignore this email.",
        )
    except Exception as exc:
        logger.error("Email verification resend failed (user_id=%s error_type=%s)", user["_id"], type(exc).__name__)
        return response
    await audit(None, "email_verification_resent", str(user["_id"]), {}, request)
    return response


# Purpose: Confirm a single-use email verification token and unlock the account approval flow.
@router.post("/api/auth/email-verification/confirm")
@limiter.limit("10/hour")
async def confirm_email_verification(body: dict, request: Request):
    raw_token = str(body.get("token") or "").strip()
    if len(raw_token) < 30 or len(raw_token) > 200:
        raise HTTPException(422, "A valid email verification link is required.")
    record = await db.email_verifications.find_one({
        "token_hash": token_hash(raw_token),
        "expires_at": {"$gt": utcnow()},
    })
    if not record:
        raise HTTPException(400, "This email verification link is invalid or expired. Request a new one from the sign-in screen.")
    consumed = await db.email_verifications.delete_one({
        "_id": record["_id"],
        "expires_at": {"$gt": utcnow()},
    })
    if consumed.deleted_count != 1:
        raise HTTPException(409, "This email verification link has already been used.")
    user = await db.users.find_one({"_id": record["user_id"]})
    if not user:
        raise HTTPException(404, "TechNova account not found.")
    await db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"email_verified_at": utcnow(), "email_verification_required": False}},
    )
    await audit(None, "email_verified", str(user["_id"]), {}, request)
    return {
        "message": "Email verified successfully. Your TechNova account is waiting for administrator approval.",
        "member_id": user.get("member_id", ""),
    }


# Purpose: me handles the auth feature flow and returns its API result.
@router.get("/api/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return clean_user(user)

# Purpose: update profile handles the auth feature flow and returns its API result.
@router.patch("/api/auth/profile")
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

# Purpose: change password handles the auth feature flow and returns its API result.
@router.post("/api/auth/change-password")
async def change_password(body: dict, user: dict = Depends(get_current_user)):
    old = body.get("current_password",""); new = body.get("new_password","")
    if not isinstance(new,str) or len(new)<12 or len(new)>128:
        raise HTTPException(422,"New password must be 12–128 characters")
    if not verify_password(old,user["password_hash"]):
        raise HTTPException(400,"Current password is incorrect")
    await db.users.update_one({"_id":user["_id"]},{"$set":{"password_hash":hash_password(new),"password_changed_at":utcnow()}})
    await create_notification(
        user,
        "TechNova password changed",
        "Your TechNova account password was changed. If you did not make this change, contact the club Founder immediately.",
        "account_security",
    )
    await audit(user,"password_changed",str(user["_id"]))
    return {"message":"Password changed. A security confirmation email will be sent if email delivery is available."}

# Purpose: password reset request handles the auth feature flow and returns its API result.
@router.post("/api/auth/password-reset/request")
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
            email_status = smtp_configuration_status()
            if not email_status["configured"]:
                raise HTTPException(
                    503,
                    "Password reset email is not configured. Check the Email configuration in Founder Settings.",
                )
            try:
                await asyncio.to_thread(
                    send_email_message,
                    email,
                    "Reset your TechNova portal password",
                    "A password reset was requested for your TechNova account. "
                    "Use this one-time token within 20 minutes:\\n\\n"
                    f"{raw}\\n\\nIf you did not request this, ignore this email.",
                )
            except Exception:
                logger.exception("Password reset email delivery failed (user_id=%s)", user["_id"])
                raise HTTPException(503, "Could not deliver password reset email; check the configured email provider and backend logs")
    return response

# Purpose: password reset confirm handles the auth feature flow and returns its API result.
@router.post("/api/auth/password-reset/confirm")
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

# Purpose: dashboard handles the auth feature flow and returns its API result.
@router.get("/api/dashboard")
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

# Purpose: credit ledger handles the auth feature flow and returns its API result.
@router.get("/api/credits/ledger")
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



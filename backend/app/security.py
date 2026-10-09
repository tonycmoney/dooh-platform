import base64
import hashlib
import hmac
import json
import secrets
import time

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Device

PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_pairing_code() -> str:
    return "".join(secrets.choice(PAIRING_ALPHABET) for _ in range(6))


def new_secret() -> str:
    return secrets.token_urlsafe(32)


# --- Admin tokens: HMAC-signed, stateless -------------------------------------


def _sign(payload: bytes) -> str:
    return hmac.new(settings.secret_key.encode(), payload, hashlib.sha256).hexdigest()


def create_admin_token() -> str:
    payload = json.dumps({"exp": int(time.time()) + settings.admin_token_days * 86400})
    body = base64.urlsafe_b64encode(payload.encode()).decode()
    return f"{body}.{_sign(body.encode())}"


def verify_admin_token(token: str) -> bool:
    try:
        body, sig = token.rsplit(".", 1)
    except ValueError:
        return False
    if not hmac.compare_digest(sig, _sign(body.encode())):
        return False
    try:
        payload = json.loads(base64.urlsafe_b64decode(body))
    except ValueError:
        return False
    return payload.get("exp", 0) > time.time()


def check_admin_password(password: str) -> bool:
    return hmac.compare_digest(password.encode(), settings.admin_password.encode())


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    return authorization[7:].strip()


def require_admin(authorization: str | None = Header(default=None)) -> None:
    if not verify_admin_token(_bearer(authorization)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired login")


def require_device(
    authorization: str | None = Header(default=None), db: Session = Depends(get_db)
) -> Device:
    token = _bearer(authorization)
    device = db.scalar(select(Device).where(Device.token_hash == sha256_hex(token)))
    if device is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown device token")
    return device

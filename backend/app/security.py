import base64
import hashlib
import hmac
import json
import secrets
import threading
import time
from collections import deque

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


class LoginThrottle:
    """Slows password guessing: after `per_client` wrong passwords from one
    address, or `overall` from everyone, within `window` seconds, logins are
    refused until the oldest failure ages out."""

    def __init__(self, per_client: int = 10, overall: int = 100, window: int = 15 * 60):
        self.per_client, self.overall, self.window = per_client, overall, window
        self._failures: dict[str, deque[float]] = {}
        self._all: deque[float] = deque()
        self._lock = threading.Lock()

    def _trim(self, times: deque[float], now: float) -> None:
        while times and times[0] <= now - self.window:
            times.popleft()

    def retry_after(self, client: str) -> int:
        """Seconds until this client may try again (0 = allowed now)."""
        now = time.monotonic()
        with self._lock:
            mine = self._failures.get(client, deque())
            self._trim(mine, now)
            self._trim(self._all, now)
            waits = [times[0] + self.window - now for times, limit in
                     ((mine, self.per_client), (self._all, self.overall)) if len(times) >= limit]
            return int(max(waits)) + 1 if waits else 0

    def failed(self, client: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._failures.setdefault(client, deque()).append(now)
            self._all.append(now)
            if len(self._failures) > 10_000:  # forget idle clients
                for key in [k for k, v in self._failures.items() if not v or v[-1] <= now - self.window]:
                    del self._failures[key]

    def reset(self, client: str) -> None:
        with self._lock:
            self._failures.pop(client, None)


login_throttle = LoginThrottle()


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

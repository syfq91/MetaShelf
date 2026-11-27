"""Password hashing, signed session cookies, CSRF tokens, and login rate limiting."""

import hmac
import secrets
import time
from collections import defaultdict

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

_ph = PasswordHasher()
SESSION_COOKIE_NAME = "metashelf_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2id."""
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against an Argon2 hash."""
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def _serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt="metashelf-session")


def create_session_cookie(secret_key: str, username: str) -> str:
    """Create a signed session token containing username and CSRF token."""
    payload = {"u": username, "csrf": secrets.token_urlsafe(24)}
    return _serializer(secret_key).dumps(payload)


def read_session_cookie(secret_key: str, token: str) -> dict[str, str] | None:
    """Validate and decode a signed session token."""
    try:
        data = _serializer(secret_key).loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(data, dict) or "u" not in data or "csrf" not in data:
        return None
    return {"u": str(data["u"]), "csrf": str(data["csrf"])}


def verify_csrf_token(expected: str, provided: str | None) -> bool:
    """Constant-time comparison of CSRF tokens."""
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected, provided)


class LoginRateLimiter:
    """Simple in-memory sliding-window rate limiter for failed login attempts."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 60) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, list[float]] = defaultdict(list)

    def is_limited(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        recent = [t for t in self._attempts[key] if t > cutoff]
        self._attempts[key] = recent
        return len(recent) >= self.max_attempts

    def record_failure(self, key: str) -> None:
        self._attempts[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        self._attempts.pop(key, None)

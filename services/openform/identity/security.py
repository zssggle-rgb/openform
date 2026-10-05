"""Opaque credentials and maintained password hashing; no bearer tokens in Web storage."""
import hashlib
import hmac
import re
import secrets
from threading import BoundedSemaphore

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from openform.errors import ApiError

PASSWORDS = PasswordHash.recommended()
AUTH_SLOTS = BoundedSemaphore(4)
DUMMY_HASH = PASSWORDS.hash(secrets.token_urlsafe(32))
COOKIE_NAME = "openform_session"
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(value: str) -> str:
    if not TOKEN_PATTERN.fullmatch(value):
        raise ApiError(401, "UNAUTHENTICATED", "凭据无效，请重新验证。")
    return hashlib.sha256(value.encode()).hexdigest()


def csrf_token(session_token: str) -> str:
    return hmac.new(session_token.encode(), b"openform.csrf/1", hashlib.sha256).hexdigest()


def hash_password(password: str) -> str:
    if not AUTH_SLOTS.acquire(blocking=False):
        raise ApiError(429, "RATE_LIMITED", "登录服务繁忙，请稍后重试。", retryable=True)
    try:
        return PASSWORDS.hash(password)
    finally:
        AUTH_SLOTS.release()


def verify_password(password: str, stored: str | None) -> bool:
    if not AUTH_SLOTS.acquire(blocking=False):
        raise ApiError(429, "RATE_LIMITED", "登录服务繁忙，请稍后重试。", retryable=True)
    try:
        try:
            valid = PASSWORDS.verify(password, stored or DUMMY_HASH)
        except UnknownHashError:
            valid = False
        return stored is not None and valid
    finally:
        AUTH_SLOTS.release()

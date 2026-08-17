from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .database import PlanningDatabase


@dataclass(frozen=True)
class Principal:
    username: str
    role: str


bearer = HTTPBearer(auto_error=False)


def hash_password(password: str, salt: bytes | None = None) -> str:
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    return f"pbkdf2_sha256$600000${_encode(salt)}${_encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, iterations, salt, expected = encoded.split("$", 3)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), _decode(salt), int(iterations))
        return hmac.compare_digest(actual, _decode(expected))
    except (ValueError, TypeError):
        return False


def issue_token(principal: Principal, secret: str, lifetime_seconds: int = 8 * 3600) -> str:
    payload = _encode(json.dumps({"sub": principal.username, "role": principal.role, "exp": int(time.time()) + lifetime_seconds}, separators=(",", ":")).encode())
    signature = _encode(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def verify_token(token: str, secret: str) -> Principal:
    try:
        payload, supplied = token.split(".", 1)
        expected = _encode(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(supplied, expected):
            raise ValueError
        data = json.loads(_decode(payload))
        if int(data["exp"]) < time.time():
            raise ValueError
        return Principal(str(data["sub"]), str(data["role"]))
    except (ValueError, KeyError, json.JSONDecodeError) as error:
        raise HTTPException(401, "Invalid or expired access token") from error


def configure_auth(database: PlanningDatabase) -> None:
    username = os.getenv("BOOTSTRAP_ADMIN_USERNAME")
    password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD")
    if username and password and database.get_user(username) is None:
        database.upsert_user(username, hash_password(password), "admin")


def current_principal(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Principal:
    if os.getenv("AUTH_ENABLED", "false").casefold() != "true":
        return Principal("local-user", "admin")
    if credentials is None:
        raise HTTPException(401, "Authentication required")
    secret = os.environ.get("APP_SECRET_KEY")
    if not secret or len(secret) < 32:
        raise HTTPException(503, "Authentication secret is not configured")
    return verify_token(credentials.credentials, secret)


def require_roles(*roles: str):
    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if principal.role not in roles:
            raise HTTPException(403, "Insufficient permission")
        return principal
    return dependency


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

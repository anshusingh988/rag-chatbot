"""OAuth2-style auth: JWT access tokens + rotating refresh tokens, RBAC (admin/user)."""
import hashlib
import hmac
import os
import secrets
import time

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import config
from .db import get_db

bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return salt.hex() + "$" + dk.hex()


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, dk_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 200_000)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


def make_access_token(user) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user["id"]),
        "email": user["email"],
        "role": user["role"],
        "iat": now,
        "exp": now + config.ACCESS_TOKEN_MINUTES * 60,
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_refresh_token(user_id: int) -> str:
    token = secrets.token_urlsafe(48)
    get_db().run(
        "INSERT INTO refresh_tokens(token_hash,user_id,expires_at) VALUES(?,?,?)",
        (_h(token), user_id, time.time() + config.REFRESH_TOKEN_DAYS * 86400),
    )
    return token


def rotate_refresh_token(token: str):
    """Validate + consume old refresh token, return (user_row, new_refresh)."""
    db = get_db()
    row = db.one("SELECT * FROM refresh_tokens WHERE token_hash=?", (_h(token),))
    if not row or row["expires_at"] < time.time():
        raise HTTPException(401, "Invalid refresh token")
    db.run("DELETE FROM refresh_tokens WHERE token_hash=?", (_h(token),))
    user = db.one("SELECT * FROM users WHERE id=?", (row["user_id"],))
    if not user:
        raise HTTPException(401, "User not found")
    return user, issue_refresh_token(user["id"])


def current_user(cred: HTTPAuthorizationCredentials = Depends(bearer)) -> dict:
    if not cred:
        raise HTTPException(401, "Not authenticated")
    claims = decode_access_token(cred.credentials)
    return {"id": int(claims["sub"]), "email": claims["email"], "role": claims["role"]}


def require_admin(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    return user

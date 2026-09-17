"""
Authentication Domain Services.

Encapsulates password hashing/verification primitives, JWT token signing/validation,
and API endpoint authentication guards.
"""

from functools import wraps
import logging
import time
from typing import Any, Dict, Optional

import bcrypt
import jwt
from flask import g, jsonify, request

from config import JWT_ACCESS_TOKEN_EXPIRES_DAYS, JWT_SECRET_KEY

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    if not password:
        raise ValueError("Password cannot be empty.")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a stored bcrypt or werkzeug hash."""
    if not password or not password_hash:
        return False
    try:
        if password_hash.startswith(("$2a$", "$2b$", "$2y$")):
            return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))

        from werkzeug.security import check_password_hash
        return check_password_hash(password_hash, password)
    except Exception as exc:
        logger.warning("Password verification failed: %s", exc)
        return False


def create_jwt_for_user(user: Dict[str, Any]) -> str:
    """Generate a signed JWT token with standard claims for an authenticated user."""
    if not user or "id" not in user:
        raise ValueError("Invalid user object for JWT generation.")

    now = int(time.time())
    payload = {
        "sub": str(user["id"]),
        "email": user.get("email", ""),
        "iat": now,
        "exp": now + (JWT_ACCESS_TOKEN_EXPIRES_DAYS * 86400),
    }

    return jwt.encode(payload, JWT_SECRET_KEY, algorithm="HS256")


def decode_jwt_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and validate a JWT token string."""
    if not token:
        return None

    try:
        return jwt.decode(token, JWT_SECRET_KEY, algorithms=["HS256"])
    except Exception:
        return None


def get_bearer_token() -> Optional[str]:
    """Extract the Bearer token from the incoming HTTP Authorization header."""
    header = request.headers.get("Authorization", "").strip()
    if not header:
        return None

    parts = header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None

    token = parts[1].strip()
    return token or None


def current_user() -> Optional[Dict[str, Any]]:
    """Retrieve the currently authenticated user from the Bearer token."""
    token = get_bearer_token()
    if not token:
        return None

    payload = decode_jwt_token(token)
    if not payload:
        return None

    user_id = payload.get("sub")
    if user_id is None:
        return None

    try:
        user_id_int = int(user_id)
    except (TypeError, ValueError):
        return None

    from services.db_service import get_user_by_id
    return get_user_by_id(user_id_int)


def login_required_api(function):
    """Decorator to require JWT authentication on API endpoints."""
    @wraps(function)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({
                "success": False,
                "error": "Authentication required.",
            }), 401

        g.current_user = user
        return function(*args, **kwargs)

    return wrapper
from functools import wraps
import jwt
import logging
import time

from flask import request, jsonify, g

from config import JWT_SECRET_KEY, JWT_ACCESS_TOKEN_EXPIRES_DAYS
from services.db_service import get_user_by_id

logger = logging.getLogger(__name__)


def create_jwt_for_user(user):
    if not user:
        raise ValueError("Invalid user.")

    now = int(time.time())

    payload = {
        "sub": str(user["id"]),
        "email": user["email"],
        "iat": now,
        # JWTs previously had no expiration. Uses the same
        # JWT_ACCESS_TOKEN_EXPIRES_DAYS config as flask-jwt-extended
        # for consistency.
        "exp": now + (JWT_ACCESS_TOKEN_EXPIRES_DAYS * 86400),
    }

    return jwt.encode(payload, JWT_SECRET_KEY, algorithm="HS256")


def decode_jwt_token(token):
    if not token:
        return None

    try:
        return jwt.decode(token, JWT_SECRET_KEY, algorithms=["HS256"])

    except Exception:
        # Originally "except (jwt.InvalidTokenError, Exception):".
        # `jwt` was shadowed elsewhere by `jwt = JWTManager(app)`, so
        # `jwt.InvalidTokenError` didn't exist on that object. Evaluating
        # a broken except-tuple on every invalid/expired token raised an
        # AttributeError *inside* the except clause itself, which Flask
        # turned into an unhandled 500 instead of a clean "logged out"
        # response. This was the likely cause of intermittent
        # "sometimes it just doesn't load" symptoms.
        #
        # NOTE: this is a wide catch by design — any JWT decode failure
        # results in a clean "logged out" response. If JWT issues come
        # up again, add specific logging here temporarily.
        return None


def get_bearer_token():
    header = request.headers.get("Authorization", "").strip()

    if not header:
        return None

    parts = header.split(" ", 1)

    if len(parts) != 2:
        return None

    if parts[0].lower() != "bearer":
        return None

    token = parts[1].strip()
    return token or None


def current_user():
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
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None

    return get_user_by_id(user_id)


def login_required_api(function):
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
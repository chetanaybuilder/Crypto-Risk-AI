from functools import wraps
import jwt
import logging
import datetime
import time
from flask import request, jsonify, g
from config import *
from services.db_service import get_user_by_id

logger = logging.getLogger(__name__)

def create_jwt_for_user(
    user,
):

    if not user:
        raise ValueError(
            "Invalid user."
        )

    now = int(time.time())

    payload = {
        "sub": str(
            user["id"]
        ),

        "email": user["email"],

        "iat": now,

        # FIX (Bug 9): JWTs previously had no expiration.
        # Uses the same JWT_ACCESS_TOKEN_EXPIRES_DAYS config
        # as flask-jwt-extended for consistency.
        "exp": now + (
            JWT_ACCESS_TOKEN_EXPIRES_DAYS
            * 86400
        ),
    }

    return pyjwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm="HS256",
    )


def decode_jwt_token(
    token,
):

    if not token:
        return None

    try:

        return pyjwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[
                "HS256"
            ],
        )

    except Exception:
        # FIX: originally "except (jwt.InvalidTokenError, Exception):".
        # `jwt` was shadowed earlier by `jwt = JWTManager(app)`, so
        # `jwt.InvalidTokenError` didn't exist on that object. Evaluating
        # a broken except-tuple on every invalid/expired token raised an
        # AttributeError *inside* the except clause itself, which Flask
        # turned into an unhandled 500 instead of a clean "logged out"
        # response. This is the single most likely cause of your
        # intermittent "sometimes it just doesn't load" symptom.
        #
        # NOTE: This is a wide catch by design — any JWT decode failure
        # should result in a clean "logged out" response. However, this
        # also means unrelated bugs in this block (e.g., future refactors
        # accidentally raising TypeError) will be silently swallowed.
        # If JWT issues arise, add specific logging here temporarily.

        return None


def get_bearer_token():

    header = request.headers.get(
        "Authorization",
        "",
    ).strip()

    if not header:
        return None

    parts = header.split(
        " ",
        1,
    )

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

    payload = decode_jwt_token(
        token
    )

    if not payload:
        return None

    user_id = payload.get(
        "sub"
    )

    if user_id is None:
        return None

    try:

        user_id = int(
            user_id
        )

    except (
        TypeError,
        ValueError,
    ):

        return None

    return get_user_by_id(
        user_id
    )


def login_required_api(
    function,
):

    @wraps(function)
    def wrapper(
        *args,
        **kwargs,
    ):

        user = current_user()

        if not user:

            return jsonify({
                "success": False,
                "error": (
                    "Authentication required."
                ),
            }), 401

        g.current_user = user

        return function(
            *args,
            **kwargs,
        )

    return wrapper



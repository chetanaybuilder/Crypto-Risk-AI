import requests
import logging
from flask import Blueprint, request, jsonify, redirect, url_for

logger = logging.getLogger(__name__)
from config import *
from services.auth_service import login_required_api, current_user, create_jwt_for_user
from services.db_service import create_local_user, get_user_by_email, create_or_update_google_user
from werkzeug.security import check_password_hash

bp = Blueprint('auth', __name__)

@bp.post("/api/auth/signup")
def signup():

    try:

        data = (
            request.get_json(
                silent=True
            )
            or {}
        )

        email = str(
            data.get(
                "email",
                "",
            )
        ).strip().lower()

        # Rate limit: max 3 signup attempts per 15 minutes per IP
        blocked = rate_limit(
            3,
            900,
            "signup",
        )(
            lambda: _client_ip()
        )
        if blocked is not None:
            return blocked

        password = str(
            data.get(
                "password",
                "",
            )
        )

        name = str(
            data.get(
                "name",
                "",
            )
        ).strip()

        if not email or "@" not in email:

            return jsonify({
                "success": False,
                "error": (
                    "Enter a valid email."
                ),
            }), 400

        if len(password) < 8:

            return jsonify({
                "success": False,
                "error": (
                    "Password must contain "
                    "at least 8 characters."
                ),
            }), 400

        existing = get_user_by_email(
            email
        )

        if existing:

            return jsonify({
                "success": False,
                "error": (
                    "An account with this email "
                    "already exists."
                ),
            }), 409

        user = create_local_user(
            email,
            password,
            name,
        )

        token = create_jwt_for_user(
            user
        )

        return jsonify({
            "success": True,
            "token": token,
            "user": user,
        })

    except ValueError as exc:

        return jsonify({
            "success": False,
            "error": str(exc),
        }), 400

    except Exception as exc:

        logger.exception(
            "Signup failed: %s",
            exc,
        )

        return jsonify({
            "success": False,
            "error": (
                "Signup failed."
            ),
        }), 500


@bp.post("/api/auth/login")
def login():

    try:

        data = (
            request.get_json(
                silent=True
            )
            or {}
        )

        email = str(
            data.get(
                "email",
                "",
            )
        ).strip().lower()

        password = str(
            data.get(
                "password",
                "",
            )
        )

        # Rate limit: max 5 login attempts per 15 minutes per IP+email
        blocked = rate_limit(
            5,
            900,
            "login",
        )(
            lambda: f"{_client_ip()}:{email}"
        )
        if blocked is not None:
            return blocked

        if not email or not password:

            return jsonify({
                "success": False,
                "error": (
                    "Email and password are required."
                ),
            }), 400

        row = get_user_by_email(
            email
        )

        if not row:

            return jsonify({
                "success": False,
                "error": (
                    "Invalid email or password."
                ),
            }), 401

        user = row_to_user(
            row
        )

        password_hash = row[4]

        if not password_hash:

            return jsonify({
                "success": False,
                "error": (
                    "This account uses "
                    "Google sign-in."
                ),
            }), 401

        if not bcrypt.check_password_hash(
            password_hash,
            password,
        ):

            return jsonify({
                "success": False,
                "error": (
                    "Invalid email or password."
                ),
            }), 401

        token = create_jwt_for_user(
            user
        )

        return jsonify({
            "success": True,
            "token": token,
            "user": user,
        })

    except Exception as exc:

        logger.exception(
            "Login failed: %s",
            exc,
        )

        return jsonify({
            "success": False,
            "error": (
                "Login failed."
            ),
        }), 500


@bp.get("/api/auth/google")
def google_login():

    if (
        not GOOGLE_CLIENT_ID
        or not GOOGLE_CLIENT_SECRET
    ):

        return jsonify({
            "success": False,
            "error": (
                "Google OAuth is not configured."
            ),
        }), 503

    try:

        redirect_uri = url_for(
            "google_callback",
            _external=True,
        )

        return (
            oauth.google
            .authorize_redirect(
                redirect_uri
            )
        )

    except Exception as exc:

        logger.exception(
            "Google authorization failed: %s",
            exc,
        )

        return jsonify({
            "success": False,
            "error": (
                "Unable to start "
                "Google authentication."
            ),
        }), 500


@bp.get("/api/auth/google/callback")
def google_callback():

    if (
        not GOOGLE_CLIENT_ID
        or not GOOGLE_CLIENT_SECRET
    ):

        return redirect(
            "/?error=google_not_configured"
        )

    try:

        token = (
            oauth.google
            .authorize_access_token()
        )

        userinfo = None

        # ----------------------------------------------------
        # Authlib may already return userinfo.
        # ----------------------------------------------------

        try:

            userinfo = token.get(
                "userinfo"
            )

        except Exception:

            userinfo = None

        # ----------------------------------------------------
        # Fallback to OIDC userinfo endpoint.
        # ----------------------------------------------------

        if not userinfo:

            try:

                userinfo = (
                    oauth.google
                    .userinfo()
                )

            except Exception:

                userinfo = None

        if not userinfo:

            return redirect(
                "/?error=google_userinfo_failed"
            )

        google_id = (
            userinfo.get("sub")
            or userinfo.get("id")
        )

        email = (
            userinfo.get("email")
        )

        name = (
            userinfo.get("name")
            or email
            or "Google User"
        )

        picture = (
            userinfo.get("picture")
        )

        if not google_id or not email:

            return redirect(
                "/?error=google_account_invalid"
            )

        user = (
            create_or_update_google_user(
                google_id,
                email,
                name,
                picture,
            )
        )

        jwt_token = (
            create_jwt_for_user(
                user
            )
        )

        return redirect(
            "/dashboard?token="
            + quote(
                jwt_token,
                safe="",
            )
        )

    except Exception as exc:

        logger.exception(
            "Google OAuth callback failed: %s",
            exc,
        )

        return redirect(
            "/?error=google_auth_failed"
        )


@bp.post("/api/auth/logout")
def logout():

    return jsonify({
        "success": True,
        "message": "Logged out.",
    })


@bp.get("/api/auth/me")
@login_required_api
def me():

    return jsonify({
        "success": True,
        "user": g.current_user,
    })



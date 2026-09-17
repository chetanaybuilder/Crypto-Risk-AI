"""
HTTP Error Handlers & API Exception Translation.

Intercepts application-level HTTP errors and formats uniform JSON responses
with correlation tracking for REST clients while allowing static views to render.
"""

import logging
from flask import Blueprint, g, jsonify, request

logger = logging.getLogger(__name__)

bp = Blueprint("error_handlers", __name__)


def _is_api_request() -> bool:
    """Determine whether the current request is targeting an API route."""
    return request.path.startswith("/api/")


def _api_error(message: str, status_code: int):
    """Construct standard JSON error payload with correlation ID."""
    return jsonify({
        "success": False,
        "error": message,
        "request_id": g.get("request_id"),
    }), status_code


@bp.app_errorhandler(400)
def bad_request(error):
    """Handle client syntax/parameter validation errors."""
    if _is_api_request():
        return _api_error("Bad request.", 400)
    return error


@bp.app_errorhandler(401)
def unauthorized(error):
    """Handle missing or expired session/bearer credentials."""
    if _is_api_request():
        return _api_error("Authentication required.", 401)
    return error


@bp.app_errorhandler(404)
def not_found(error):
    """Handle missing route or resource lookups."""
    if _is_api_request():
        return _api_error("Endpoint not found.", 404)
    return error


@bp.app_errorhandler(500)
def internal_server_error(error):
    """Log unhandled server exceptions and mask internal stack details from client."""
    logger.error("Unhandled server error: %s", error, exc_info=True)
    if _is_api_request():
        return _api_error("Internal server error.", 500)
    return error
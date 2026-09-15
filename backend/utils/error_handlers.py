from flask import Blueprint, jsonify

bp = Blueprint('error_handlers', __name__)

@bp.app_errorhandler(400)
def bad_request(
    error,
):

    if request.path.startswith(
        "/api/"
    ):

        return jsonify({
            "success": False,

            "error": (
                "Bad request."
            ),

            "request_id": g.get(
                "request_id"
            ),
        }), 400

    return error


@bp.app_errorhandler(401)
def unauthorized(
    error,
):

    if request.path.startswith(
        "/api/"
    ):

        return jsonify({
            "success": False,

            "error": (
                "Authentication required."
            ),

            "request_id": g.get(
                "request_id"
            ),
        }), 401

    return error


@bp.app_errorhandler(404)
def not_found(
    error,
):

    if request.path.startswith(
        "/api/"
    ):

        return jsonify({
            "success": False,

            "error": (
                "Endpoint not found."
            ),

            "request_id": g.get(
                "request_id"
            ),
        }), 404

    return error


@bp.app_errorhandler(500)
def internal_server_error(
    error,
):

    logger.error(
        "Unhandled server error: %s",
        error,
    )

    if request.path.startswith(
        "/api/"
    ):

        return jsonify({
            "success": False,

            "error": (
                "Internal server error."
            ),

            "request_id": g.get(
                "request_id"
            ),
        }), 500

    return error



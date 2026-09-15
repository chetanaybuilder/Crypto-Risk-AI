import logging
logger = logging.getLogger(__name__)
from flask import Blueprint, jsonify
from services.auth_service import login_required_api, current_user
from services.db_service import get_analysis_by_id, delete_analysis, delete_all_analyses

bp = Blueprint('history', __name__)

@bp.get(
    "/api/history/<analysis_id>"
)
@login_required_api
def history_single(
    analysis_id,
):

    try:

        analysis = get_analysis_by_id(
            analysis_id,
            g.current_user["id"],
        )

        if not analysis:

            return jsonify({
                "success": False,
                "error": (
                    "Analysis not found."
                ),
            }), 404

        return jsonify({
            "success": True,

            "analysis": analysis,

            "report": analysis[
                "report"
            ],
        })

    except Exception as exc:

        logger.exception(
            "History lookup failed: %s",
            exc,
        )

        return jsonify({
            "success": False,
            "error": (
                "Unable to load analysis."
            ),
        }), 500


@bp.delete(
    "/api/history/<analysis_id>"
)
@login_required_api
def history_delete(
    analysis_id,
):

    try:

        deleted = delete_analysis(
            analysis_id,
            g.current_user["id"],
        )

        if not deleted:

            return jsonify({
                "success": False,
                "error": (
                    "Analysis not found."
                ),
            }), 404

        return jsonify({
            "success": True,

            "message": (
                "Analysis deleted."
            ),

            "history": get_user_history(
                g.current_user["id"]
            ),
        })

    except Exception as exc:

        logger.exception(
            "History delete failed: %s",
            exc,
        )

        return jsonify({
            "success": False,
            "error": (
                "Unable to delete analysis."
            ),
        }), 500


@bp.delete("/api/history")
@login_required_api
def history_delete_all():

    try:

        count = delete_all_analyses(
            g.current_user["id"]
        )

        return jsonify({
            "success": True,

            "deleted": count,

            "history": [],
        })

    except Exception as exc:

        logger.exception(
            "Delete all history failed: %s",
            exc,
        )

        return jsonify({
            "success": False,
            "error": (
                "Unable to delete history."
            ),
        }), 500



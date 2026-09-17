"""
Historical Analysis Records & Management Endpoints.

Provides authenticated CRUD operations for reviewing, inspecting, and deleting
persisted risk reports associated with the active user account.
"""

import logging

from flask import Blueprint, g, jsonify

from services.auth_service import login_required_api
from services.db_service import (
    delete_all_analyses,
    delete_analysis,
    get_analysis_by_id,
    get_user_history,
)

logger = logging.getLogger(__name__)

bp = Blueprint("history", __name__)


@bp.get("/api/history/<analysis_id>")
@login_required_api
def history_single(analysis_id):
    """Retrieve a single saved analysis report by ID."""
    try:
        analysis = get_analysis_by_id(analysis_id, g.current_user["id"])
        if not analysis:
            return jsonify({
                "success": False,
                "error": "Analysis not found.",
            }), 404

        return jsonify({
            "success": True,
            "analysis": analysis,
            "report": analysis["report"],
        })

    except Exception as exc:
        logger.exception("History lookup failed: %s", exc)
        return jsonify({
            "success": False,
            "error": "Unable to load analysis.",
        }), 500


@bp.delete("/api/history/<analysis_id>")
@login_required_api
def history_delete(analysis_id):
    """Delete a single analysis report for the authenticated user."""
    try:
        deleted = delete_analysis(analysis_id, g.current_user["id"])
        if not deleted:
            return jsonify({
                "success": False,
                "error": "Analysis not found.",
            }), 404

        return jsonify({
            "success": True,
            "message": "Analysis deleted.",
            "history": get_user_history(g.current_user["id"]),
        })

    except Exception as exc:
        logger.exception("History delete failed: %s", exc)
        return jsonify({
            "success": False,
            "error": "Unable to delete analysis.",
        }), 500


@bp.delete("/api/history")
@login_required_api
def history_delete_all():
    """Delete all analysis reports for the authenticated user."""
    try:
        count = delete_all_analyses(g.current_user["id"])
        return jsonify({
            "success": True,
            "deleted": count,
            "history": [],
        })

    except Exception as exc:
        logger.exception("Delete all history failed: %s", exc)
        return jsonify({
            "success": False,
            "error": "Unable to delete history.",
        }), 500
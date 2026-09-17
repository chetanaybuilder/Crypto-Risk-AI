"""
Dashboard Routing & Initial State Aggregation.

Serves the authenticated dashboard SPA view and provides aggregated initialization
state (user profile, recent analysis history, and latest report snapshot).
"""

import logging

from flask import Blueprint, g, jsonify, render_template

from services.auth_service import login_required_api
from services.db_service import get_analysis_by_id, get_user_history

logger = logging.getLogger(__name__)

bp = Blueprint("dashboard", __name__)


@bp.get("/dashboard")
def dashboard():
    """Render the dashboard application shell."""
    return render_template("dashboard.html")


@bp.get("/api/dashboard")
@login_required_api
def dashboard_api():
    """Fetch initial aggregate state for the dashboard workspace."""
    try:
        history = get_user_history(g.current_user["id"])

        latest = None
        if history:
            latest_id = history[0]["id"]
            latest_analysis = get_analysis_by_id(latest_id, g.current_user["id"])
            if latest_analysis:
                latest = latest_analysis.get("report")

        return jsonify({
            "success": True,
            "user": g.current_user,
            "latest": latest,
            "history": history,
        })

    except Exception as exc:
        logger.exception("Dashboard API aggregation failed: %s", exc)
        return jsonify({
            "success": False,
            "error": "Unable to load dashboard.",
        }), 500
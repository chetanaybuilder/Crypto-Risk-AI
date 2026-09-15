import logging
logger = logging.getLogger(__name__)
from flask import Blueprint, jsonify, render_template
from services.auth_service import login_required_api, current_user
from services.db_service import get_user_history

bp = Blueprint('dashboard', __name__)

@bp.get("/dashboard")
def dashboard():

    return render_template(
        "dashboard.html"
    )


@bp.get("/api/dashboard")
@login_required_api
def dashboard_api():

    try:

        history = get_user_history(
            g.current_user["id"]
        )

        latest = None

        if history:

            latest_id = history[0][
                "id"
            ]

            latest_analysis = (
                get_analysis_by_id(
                    latest_id,
                    g.current_user["id"],
                )
            )

            if latest_analysis:

                latest = (
                    latest_analysis
                    .get("report")
                )

        return jsonify({
            "success": True,

            "user": g.current_user,

            "latest": latest,

            "history": history,
        })

    except Exception as exc:

        logger.exception(
            "Dashboard API failed: %s",
            exc,
        )

        return jsonify({
            "success": False,
            "error": (
                "Unable to load dashboard."
            ),
        }), 500



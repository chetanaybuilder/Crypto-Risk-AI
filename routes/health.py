"""
System Health Diagnostics & Landing Route.

Exposes container liveness/readiness probes, runtime schema versions, and provider
telemetry for uptime monitoring and infrastructure automation.
"""

from flask import Blueprint, jsonify, render_template

from config import (
    ANALYSIS_EXECUTOR_WORKERS,
    ANALYSIS_JOB_TIMEOUT_SECONDS,
    APP_NAME,
    APP_VERSION,
    COINGECKO_API_KEY,
    COINGECKO_API_URL,
    COINGECKO_PLAN,
    GEMINI_API_KEY,
    REPORT_SCHEMA_VERSION,
)
from utils.helpers import utc_now_iso

bp = Blueprint("health", __name__)


@bp.get("/health")
def health():
    """Liveness probe reporting provider status, worker pool capacity, and configuration state."""
    return jsonify({
        "success": True,
        "status": "healthy",
        "service": APP_NAME,
        "version": APP_VERSION,
        "schema_version": REPORT_SCHEMA_VERSION,
        "timestamp": utc_now_iso(),
        "gemini_configured": bool(GEMINI_API_KEY),
        "analysis_workers": ANALYSIS_EXECUTOR_WORKERS,
        "analysis_job_timeout_seconds": ANALYSIS_JOB_TIMEOUT_SECONDS,
        "coingecko_plan": COINGECKO_PLAN,
        "coingecko_key_configured": bool(COINGECKO_API_KEY),
        "coingecko_base_url": COINGECKO_API_URL,
        "market_data_provider": "CoinGecko",
    })


@bp.get("/")
def index():
    """Serve public landing and marketing view."""
    return render_template("index.html")
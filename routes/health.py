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
    """Health check endpoint exposing system status, versioning, and provider configuration."""
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
    """Serve landing page."""
    return render_template("index.html")
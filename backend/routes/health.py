from flask import Blueprint, jsonify, render_template
from config import (
    APP_NAME, APP_VERSION, REPORT_SCHEMA_VERSION, 
    ANALYSIS_EXECUTOR_WORKERS, ANALYSIS_JOB_TIMEOUT_SECONDS,
    COINGECKO_PLAN, COINGECKO_API_KEY
)
from utils.helpers import utc_now_iso
import os

bp = Blueprint('health', __name__)

@bp.get("/health")
def health():
    return jsonify({
        "success": True,
        "status": "healthy",
        "service": APP_NAME,
        "version": APP_VERSION,
        "schema_version": REPORT_SCHEMA_VERSION,
        "timestamp": utc_now_iso(),
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY")),
        "analysis_workers": ANALYSIS_EXECUTOR_WORKERS,
        "analysis_job_timeout_seconds": ANALYSIS_JOB_TIMEOUT_SECONDS,
        "coingecko_plan": COINGECKO_PLAN,
        "coingecko_key_configured": bool(COINGECKO_API_KEY),
        "coingecko_base_url": "https://api.coingecko.com/api/v3" if COINGECKO_PLAN == "free" else "https://pro-api.coingecko.com/api/v3",
        "market_data_provider": "CoinGecko (exclusive)",
    })

@bp.get("/")
def index():
    return render_template("index.html")

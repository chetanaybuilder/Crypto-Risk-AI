import logging
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, g

from utils.helpers import is_valid_symbol, normalize_symbol, utc_now_iso
from utils.errors import MarketDataUnavailableError, UnsupportedAssetError
from config import ANALYSIS_JOB_TIMEOUT_SECONDS
from services.coingecko import resolve_coin_id
from extensions import get_db_connection
from services.auth_service import login_required_api
from services.risk_engine import run_analysis
from services.db_service import (
    update_analysis_job,
    cleanup_old_analysis_jobs,
    submit_analysis_job,
    save_analysis,
    create_analysis_job,
    get_user_history,
    get_analysis_job,
)

logger = logging.getLogger(__name__)

bp = Blueprint('risk', __name__)


@bp.post("/api/analyze")
@login_required_api
def analyze():
    raw_symbol = None
    try:
        data = request.get_json(silent=True) or {}

        raw_symbol = data.get("token_symbol") or data.get("symbol")

        if not is_valid_symbol(raw_symbol):
            return jsonify({
                "success": False,
                "error": "Invalid token symbol. Use 1-15 letters or digits.",
            }), 400

        symbol = normalize_symbol(raw_symbol)
        chain_id = data.get("chain_id") or data.get("chain") or data.get("network")
        contract_address = data.get("contract_address") or data.get("contractAddress")
        print(f"[PIPELINE TRACE 2] Analysis requested for symbol={symbol}, chain={chain_id}, address={contract_address}")

        if not symbol:
            return jsonify({
                "success": False,
                "error": "Token symbol is required.",
            }), 400

        report = run_analysis(
            symbol,
            chain_id=chain_id,
            contract_address=contract_address,
            force_market_refresh=False,
            # Synchronous path: force zero Gemini retries to cap
            # worst-case latency at GEMINI_TIMEOUT_SECONDS instead
            # of GEMINI_TIMEOUT_SECONDS * (GEMINI_MAX_RETRIES + 1).
            gemini_max_retries_override=0,
        )

        # Persist to DB — but never let persistence failure
        # break the response. The report is the source of
        # truth and must always reach the frontend.
        try:
            analysis_id = save_analysis(g.current_user["id"], symbol, report)
        except Exception as db_exc:
            logger.warning("save_analysis failed: %s", db_exc)
            analysis_id = None

        try:
            history = get_user_history(g.current_user["id"])
        except Exception as db_exc:
            logger.warning("get_user_history failed: %s", db_exc)
            history = []

        return jsonify({
            "success": True,
            "analysis": {
                "id": analysis_id,
                "token_symbol": symbol,
                "report": report,
                "created_at": utc_now_iso(),
            },
            "latest": report,
            "history": history,
            "user": g.current_user,
            "meta": {
                "analysis_id": analysis_id,
                "mode": "synchronous",
                "ai_provider": report.get("ai", {}).get("provider"),
                "fallback_used": report.get("ai", {}).get("fallback_used", False),
            },
        })

    except MarketDataUnavailableError as exc:
        logger.exception("Market data unavailable during analysis: %s", exc)
        return jsonify({
            "success": False,
            "error": str(exc),
            "code": "MARKET_DATA_UNAVAILABLE",
        }), 502

    except UnsupportedAssetError as exc:
        # Explicit handling for unsupported assets — return the
        # specific error message instead of a generic "Analysis failed"
        # so users know exactly why their request was rejected.
        # This provides consistent error handling between /api/analyze
        # and /api/market/<symbol> endpoints.
        #
        # NOTE: uses raw_symbol (captured before validation/normalization)
        # instead of `symbol`, since `symbol` may not be assigned yet if
        # this exception originates before that line runs.
        logger.warning("Unsupported asset requested: %s - %s", raw_symbol, exc)
        return jsonify({
            "success": False,
            "error": str(exc),
            "code": "UNSUPPORTED_ASSET",
        }), 400

    except ValueError as exc:
        return jsonify({
            "success": False,
            "error": str(exc),
        }), 400

    except Exception as exc:
        logger.exception("Synchronous analysis failed: %s", exc)
        return jsonify({
            "success": False,
            "error": "Analysis failed. Please try again.",
        }), 500


@bp.post("/api/analyze/start")
@login_required_api
def start_analysis():
    try:
        cleanup_old_analysis_jobs()

        data = request.get_json(silent=True) or {}
        raw_symbol = data.get("token_symbol") or data.get("symbol")

        if not is_valid_symbol(raw_symbol):
            return jsonify({
                "success": False,
                "error": "Invalid token symbol. Use 1-15 letters or digits.",
            }), 400

        symbol = normalize_symbol(raw_symbol)
        chain_id = data.get("chain_id") or data.get("chain") or data.get("network")
        contract_address = data.get("contract_address") or data.get("contractAddress")
        print(f"[DEBUG] Analysis requested for symbol={symbol}, chain={chain_id}, address={contract_address}")

        if not symbol:
            return jsonify({
                "success": False,
                "error": "Token symbol is required.",
            }), 400

        # Fail fast for symbols that cannot be resolved to a CoinGecko
        # asset id, so the user gets a clear 400 UNSUPPORTED_ASSET
        # immediately instead of a job that runs and fails later with
        # a raw provider error.
        try:
            resolve_coin_id(symbol)
        except UnsupportedAssetError as exc:
            logger.warning("Unsupported asset requested (job start): %s - %s", symbol, exc)
            return jsonify({
                "success": False,
                "error": str(exc),
                "code": "UNSUPPORTED_ASSET",
            }), 400

        # Prevent duplicate active jobs.
        #
        # A job that was "running" when the dyno/instance restarted
        # (common on free hosting that sleeps/redeploys) is treated as
        # dead, not active, once updated_at goes stale — not just
        # created_at — so it never blocks retries indefinitely.
        connection = None
        active_job = None

        try:
            connection = get_db_connection()

            with connection.cursor() as cursor:
                # Use a single consistent time window for both created_at
                # and updated_at checks so they never contradict each other.
                job_dedup_window_seconds = max(
                    600,  # minimum 10 minutes
                    ANALYSIS_JOB_TIMEOUT_SECONDS * 2,
                )
                cursor.execute(
                    """
                    SELECT id
                    FROM analysis_jobs
                    WHERE user_id = %s
                      AND token_symbol = %s
                      AND status IN ('queued', 'running', 'saving')
                      AND created_at > NOW() - (%s * INTERVAL '1 second')
                      AND updated_at > NOW() - (%s * INTERVAL '1 second')
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (
                        g.current_user["id"],
                        symbol,
                        job_dedup_window_seconds,
                        job_dedup_window_seconds,
                    ),
                )

                row = cursor.fetchone()
                if row:
                    active_job = str(row[0])

        finally:
            if connection:
                connection.close()

        if active_job:
            return jsonify({
                "success": True,
                "existing_job": True,
                "job_id": active_job,
                "message": "An analysis for this asset is already running.",
            }), 200

        job_id = create_analysis_job(
            g.current_user["id"],
            symbol,
            chain_id=chain_id,
            contract_address=contract_address,
        )

        submitted = submit_analysis_job(job_id)

        if not submitted:
            return jsonify({
                "success": False,
                "error": "Unable to start analysis worker.",
            }), 500

        job = get_analysis_job(job_id, g.current_user["id"])

        return jsonify({
            "success": True,
            "job_id": job_id,
            "job": job,
        }), 202

    except ValueError as exc:
        return jsonify({
            "success": False,
            "error": str(exc),
        }), 400

    except Exception as exc:
        logger.exception("Could not start analysis: %s", exc)
        return jsonify({
            "success": False,
            "error": "Unable to start analysis.",
        }), 500


@bp.get("/api/analyze/status/<job_id>")
@login_required_api
def analysis_status(job_id):
    try:
        job = get_analysis_job(job_id, g.current_user["id"])

        if not job:
            return jsonify({
                "success": False,
                "error": "Analysis job not found.",
            }), 404

        # Detect stale jobs.
        if job["status"] in {"queued", "running", "saving"}:
            updated_at = job.get("updated_at")

            if updated_at:
                try:
                    # NOTE: was `datetime.fromisoformat(...)` where
                    # `datetime` was the *module* (import datetime),
                    # not the class — that raises AttributeError on
                    # every single call. Now imports the class directly
                    # (from datetime import datetime, timezone).
                    updated_dt = datetime.fromisoformat(
                        updated_at.replace("Z", "+00:00")
                    )

                    age = (datetime.now(timezone.utc) - updated_dt).total_seconds()

                    if age > ANALYSIS_JOB_TIMEOUT_SECONDS:
                        update_analysis_job(
                            job_id,
                            status="failed",
                            progress=100,
                            stage="timeout",
                            stage_title="Analysis timed out",
                            message="The analysis worker stopped responding.",
                            error="Analysis job exceeded the server-side activity timeout.",
                            completed=True,
                        )
                        job = get_analysis_job(job_id, g.current_user["id"])

                except Exception as exc:
                    logger.debug("Could not evaluate job age: %s", exc)

        response = {
            "success": True,
            "job": {
                "id": job["id"],
                "token_symbol": job["token_symbol"],
                "status": job["status"],
                "progress": job["progress"],
                "stage": job["stage"],
                "stage_title": job["stage_title"],
                "message": job["message"],
                "error": job["error"],
                "created_at": job["created_at"],
                "started_at": job["started_at"],
                "updated_at": job["updated_at"],
                "completed_at": job["completed_at"],
            },
        }

        # Completed analysis.
        if job["status"] == "completed":
            meta = job.get("meta") or {}
            analysis_id = meta.get("analysis_id")
            history = get_user_history(g.current_user["id"])

            response.update({
                "latest": job["report"],
                "analysis": {
                    "id": analysis_id,
                    "token_symbol": job["token_symbol"],
                    "report": job["report"],
                    "created_at": job["completed_at"],
                },
                "history": history,
                "user": g.current_user,
                "meta": meta,
            })

        return jsonify(response)

    except Exception as exc:
        logger.exception("Analysis status failed: %s", exc)
        return jsonify({
            "success": False,
            "error": "Unable to read analysis status.",
        }), 500
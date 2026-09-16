import logging

from flask import Blueprint, request, jsonify

from utils.helpers import is_valid_symbol, normalize_symbol
from utils.errors import UnsupportedAssetError
from services.auth_service import login_required_api
from services.coingecko import fetch_market_data

logger = logging.getLogger(__name__)

bp = Blueprint('market', __name__)


@bp.get("/api/market/<symbol>")
@login_required_api
def market_api(symbol):
    try:
        raw_symbol = str(symbol or "").strip()

        if not is_valid_symbol(raw_symbol):
            return jsonify({
                "success": False,
                "error": "Invalid token symbol. Use 1-15 letters or digits.",
            }), 400

        symbol = normalize_symbol(raw_symbol)

        if not symbol:
            return jsonify({
                "success": False,
                "error": "Invalid token symbol.",
            }), 400

        # Respect the market cache by default; caller must explicitly
        # request a fresh pull with ?refresh=true to avoid burning
        # through CoinGecko rate limits.
        force_refresh = str(
            request.args.get("refresh", "false")
        ).strip().lower() in ("1", "true", "yes")

        market = fetch_market_data(symbol, force_refresh=force_refresh)

        # Return 200 even if market.get("available") is False, so the
        # frontend can render missing values gracefully instead of
        # treating it as a fatal error.
        if isinstance(market, dict):
            return jsonify({
                "success": True,
                "symbol": symbol,
                "market": market,
            })

        # Should never hit here since fetch_market_data returns dict
        return jsonify({
            "success": False,
            "error": "Failed to fetch market data",
        }), 502

    except UnsupportedAssetError as exc:
        return jsonify({
            "success": False,
            "error": str(exc),
            "code": "UNSUPPORTED_ASSET",
        }), 400

    except Exception as exc:
        logger.exception("Market API failed: %s", exc)
        return jsonify({
            "success": False,
            "error": "Market data unavailable.",
        }), 502
from flask import Blueprint, request, jsonify
from services.auth_service import login_required_api
from services.coingecko import fetch_market_data

bp = Blueprint('market', __name__)

@bp.get("/api/market/<symbol>")
@login_required_api
def market_api(
    symbol,
):

    try:

        raw_symbol = str(symbol or "").strip()

        if not is_valid_symbol(raw_symbol):
            return jsonify({
                "success": False,
                "error": "Invalid token symbol. Use 1-15 letters or digits.",
            }), 400

        symbol = normalize_symbol(
            raw_symbol
        )

        if not symbol:

            return jsonify({
                "success": False,
                "error": (
                    "Invalid token symbol."
                ),
            }), 400

        # FIX: this always forced a live upstream refetch,
        # bypassing the market cache entirely. On a busy
        # dashboard that polls this endpoint, that burns
        # through CoinGecko rate limits fast — once
        # you get 429'd, fetch_market_data() legitimately
        # returns "available": false, which looks exactly like
        # "sometimes it just doesn't fetch." Respect the cache
        # by default; let the caller explicitly ask for a
        # fresh pull with ?refresh=true.
        force_refresh = str(
            request.args.get(
                "refresh",
                "false",
            )
        ).strip().lower() in ("1", "true", "yes")

        market = fetch_market_data(
            symbol,
            force_refresh=force_refresh,
        )

        # FIX: Even if market.get("available") is false, we return 200 OK.
        # This allows the frontend to gracefully render missing values
        # instead of throwing a fatal 502 error and blanking the screen.
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

        # FIX: removed traceback.print_exc() — it was printing raw stack
        # traces to stdout, bypassing the structured logger and leaking
        # internals in production. logger.exception() already captures
        # the full traceback in the structured log stream.
        logger.exception(
            "Market API failed: %s",
            exc,
        )

        return jsonify({
            "success": False,
            "error": "Market data unavailable.",
        }), 502



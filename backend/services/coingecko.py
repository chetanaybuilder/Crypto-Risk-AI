import time
import logging
import requests
from utils.helpers import percentage_change, numeric, _mark_provider_failure, optional_numeric, utc_now_iso, normalize_symbol, json_safe, _get_symbol_fetch_lock, _clear_provider_success, empty_market_data, _provider_is_cooling
from typing import Dict, Any, List, Optional
from config import *
from extensions import *
from utils.helpers import *
from utils.errors import *

logger = logging.getLogger(__name__)

def _cache_coin_resolution(
    symbol: str,
    coin_id: Optional[str],
) -> None:
    """Store a (possibly negative) coin-id resolution result."""

    with _cache_lock:
        _coin_resolution_cache[symbol] = {
            "coin_id": coin_id,
            "cached_at": time.time(),
        }


def resolve_coin_id(
    symbol: str,
) -> Optional[str]:
    """
    Resolve a user-supplied ticker to a verified CoinGecko coin id.

    FIX (Bug 5): previously this was a pure TOKEN_MAP lookup and any
    ticker outside the hardcoded allowlist raised
    UnsupportedAssetError immediately — a hard, permanent failure
    that users perceived as "sometimes it just doesn't work". Now:

      1. TOKEN_MAP is checked first (no network call).
      2. The persistent _coin_resolution_cache is consulted
         (positive results cached for COIN_RESOLUTION_CACHE_TTL,
         misses for the shorter COIN_RESOLUTION_MISS_TTL).
      3. Unknown symbols are resolved dynamically via CoinGecko's
         /search endpoint and cached.
      4. UnsupportedAssetError is raised only when a symbol truly
         cannot be resolved — a clear 400 UNSUPPORTED_ASSET,
         distinct from the 502 MARKET_DATA_UNAVAILABLE used for
         provider failures.

    Returns None (without raising) when CoinGecko is on cooldown or
    the lookup fails transiently, so callers degrade to a
    market-unavailable response instead of claiming the asset is
    unsupported.
    """

    symbol = normalize_symbol(
        symbol
    )

    if not symbol:
        return None

    now = time.time()

    # 1. Static allowlist — cheapest path, no network call.
    coin_id = TOKEN_MAP.get(symbol)

    if coin_id:
        return coin_id

    # 2. Cached result from an earlier resolution.
    with _cache_lock:
        cached = _coin_resolution_cache.get(symbol)

    if isinstance(cached, dict):

        try:
            cached_at = float(cached.get("cached_at") or 0)
        except (TypeError, ValueError):
            cached_at = 0

        cached_id = cached.get("coin_id")

        ttl = (
            COIN_RESOLUTION_CACHE_TTL
            if cached_id
            else COIN_RESOLUTION_MISS_TTL
        )

        if now - cached_at < ttl:

            if cached_id:
                return cached_id

            raise UnsupportedAssetError(
                f"Unsupported asset '{symbol}'. "
                "This token isn't supported yet."
            )

    # 3. Dynamic resolution via CoinGecko /search. While CoinGecko
    # is cooling down, return None so callers produce a market-
    # unavailable response rather than a false "unsupported asset".
    if _provider_is_cooling("CoinGecko"):
        return None

    try:

        response, status_code, error_reason = _http_get_market(
            f"{COINGECKO_API_URL}/search",
            params={"query": symbol},
            timeout=MARKET_TIMEOUT,
        )

        if (
            response is None
            or (
                status_code is not None
                and status_code >= 400
            )
        ):
            # Transient provider failure — do NOT cache a negative
            # result; leave un-resolved and treat as unavailable.
            logger.info(
                "[COIN] /search lookup failed for %s: %s",
                symbol,
                error_reason or f"HTTP {status_code}",
            )

            return None

        payload = response.json()

        matches = (
            payload.get("coins")
            if isinstance(payload, dict)
            else None
        )

        resolved_id = None

        if isinstance(matches, list):

            # Only accept an EXACT symbol match (case-insensitive).
            # /search returns fuzzy matches; blindly taking the first
            # entry would silently analyze the wrong asset.
            wanted = symbol.lower()

            for entry in matches:

                if not isinstance(entry, dict):
                    continue

                entry_id = entry.get("id")

                if not entry_id:
                    continue

                entry_symbol = str(
                    entry.get("symbol", "")
                ).strip().lower()

                if entry_symbol == wanted:
                    resolved_id = entry_id
                    break

        if resolved_id:

            _cache_coin_resolution(symbol, resolved_id)

            logger.info(
                "[COIN] resolved %s -> %s via CoinGecko /search",
                symbol,
                resolved_id,
            )

            return resolved_id

        # Genuinely unresolvable — cache the miss briefly and raise
        # a distinct UNSUPPORTED_ASSET error (HTTP 400).
        _cache_coin_resolution(symbol, None)

        raise UnsupportedAssetError(
            f"Unsupported asset '{symbol}'. "
            "This token isn't supported yet."
        )

    except UnsupportedAssetError:
        raise

    except Exception as exc:
        logger.warning(
            "[COIN] dynamic resolution failed for %s: %s",
            symbol,
            exc,
        )
        return None


def fetch_coingecko_market(
    symbol: str,
    bypass_cooldown: bool = False,
) -> dict:
    """
    Fetch current market snapshot from CoinGecko (/coins/markets).

    Uses the status-aware HTTP helper so 429/403/451/5xx responses
    are recorded via the provider cooldown system and returned as
    a precise unavailable result.
    """

    symbol = normalize_symbol(symbol)

    if not symbol:
        return empty_market_data(symbol)

    # Skip if currently on cooldown.
    if not bypass_cooldown and _provider_is_cooling("CoinGecko"):
        market = empty_market_data(symbol)
        market["unavailable_reason"] = "CoinGecko is temporarily cooling down after a provider failure."
        return market

    coin_id = resolve_coin_id(symbol)

    if not coin_id:
        market = empty_market_data(symbol)
        market["unavailable_reason"] = f"CoinGecko could not resolve symbol {symbol}."
        return market

    # CoinGecko is now the single source — wrap the upstream call in a
    # short retry loop so a single transient hiccup (timeout, 5xx,
    # connection reset) doesn't take down the whole report. 429s and
    # 4xx (bad request) are NOT retried here: 429 is handled by the
    # provider cooldown system (Retry-After), and 4xx means the request
    # itself is bad and retrying would be pointless.
    last_error_reason = None
    last_status_code = None
    for attempt in range(1, COINGECKO_MAX_RETRIES + 1):
        response, status_code, error_reason = _http_get_market(
            f"{COINGECKO_API_URL}/coins/markets",
            params={
                "vs_currency": "usd",
                "ids": coin_id,
                "order": "market_cap_desc",
                "per_page": 1,
                "page": 1,
                "sparkline": "false",
                "price_change_percentage": "7d",
            },
            timeout=MARKET_TIMEOUT,
        )

        if response is not None and (status_code is None or status_code < 400):
            # Success (or at least a response we can parse) — break out.
            break

        last_error_reason = error_reason
        last_status_code = status_code

        # Decide whether this failure is retryable.
        retryable = False
        smart_wait = None
        if response is None:
            # No response at all: timeout, connection error, DNS, etc.
            retryable = True
        elif status_code is not None and status_code >= 500:
            # Server-side failure — worth retrying.
            retryable = True
        elif status_code == 429:
            # Check if we can wait out the cooldown within the job timeout
            match = re.search(r"retry_after=([0-9]+(?:\.[0-9]+)?)", str(error_reason or ""))
            if match:
                retry_after_val = float(match.group(1))
                if retry_after_val <= 2.0:
                    retryable = True
                    smart_wait = retry_after_val + 1.0

        if not retryable or attempt >= COINGECKO_MAX_RETRIES:
            break

        if smart_wait is not None:
            backoff = smart_wait
            logger.info(
                "[MARKET] CoinGecko rate limited (429) for %s. Smart waiting %.1fs before retry...",
                symbol,
                backoff,
            )
        else:
            backoff = 0.5 * (2 ** (attempt - 1))
            logger.info(
                "[MARKET] CoinGecko attempt %d/%d for %s after %s, retrying in %.1fs",
                attempt,
                COINGECKO_MAX_RETRIES,
                symbol,
                error_reason or f"HTTP {status_code}",
                backoff,
            )
        time.sleep(backoff)

    if response is None:
        _mark_provider_failure(
            "CoinGecko",
            last_status_code,
            last_error_reason or "no_response",
        )
        market = empty_market_data(symbol)
        market["unavailable_reason"] = (
            f"CoinGecko request failed: {last_error_reason or 'no response'}."
        )
        return market

    if last_status_code is not None and last_status_code >= 400:
        _mark_provider_failure(
            "CoinGecko",
            last_status_code,
            last_error_reason or f"HTTP {last_status_code}",
        )
        market = empty_market_data(symbol)
        market["unavailable_reason"] = (
            f"CoinGecko returned {last_error_reason or f'HTTP {last_status_code}'}."
        )
        return market

    try:
        payload = response.json()

        if not isinstance(payload, list) or not payload:
            _mark_provider_failure(
                "CoinGecko",
                status_code,
                "malformed_json",
            )
            market = empty_market_data(symbol)
            market["unavailable_reason"] = (
                "CoinGecko returned an empty or malformed market response."
            )
            return market

        coin = payload[0]

        if not isinstance(coin, dict):
            market = empty_market_data(symbol)
            market["unavailable_reason"] = (
                "CoinGecko returned an invalid market record."
            )
            return market

        field_errors = {}
        price = _read_market_number(
            coin, "current_price", "CoinGecko", field_errors
        )
        volume = _read_market_number(
            coin, "total_volume", "CoinGecko", field_errors
        )
        market_cap = _read_market_number(
            coin, "market_cap", "CoinGecko", field_errors
        )
        change_24h = _read_market_number(
            coin, "price_change_percentage_24h", "CoinGecko", field_errors
        )
        change_7d = _read_market_number(
            coin, "price_change_percentage_7d_in_currency", "CoinGecko", field_errors
        )
        high_24h = _read_market_number(
            coin, "high_24h", "CoinGecko", field_errors
        )
        low_24h = _read_market_number(
            coin, "low_24h", "CoinGecko", field_errors
        )

        if price is None:
            market = empty_market_data(symbol)
            market["unavailable_reason"] = (
                "CoinGecko returned no usable price."
            )
            return market

        _clear_provider_success("CoinGecko")
        timestamp = utc_now_iso()
        last_updated = coin.get("last_updated")

        if last_updated:
            try:
                timestamp = datetime.fromisoformat(
                    str(last_updated).replace("Z", "+00:00")
                ).isoformat()
            except (TypeError, ValueError):
                pass

        logger.info(
            "[MARKET] CoinGecko SUCCESS price=%.4f source=CoinGecko",
            price,
        )

        return json_safe({
            "symbol": symbol,
            "coin_id": coin_id,
            "price": price,
            "price_change_24h_pct": change_24h,
            "price_change_7d_pct": change_7d,
            "volume_24h": volume,
            "market_cap": market_cap,
            "high_24h": high_24h,
            "low_24h": low_24h,
            "source": "CoinGecko",
            "timestamp": timestamp,
            "source_timestamps": {
                "CoinGecko": timestamp,
            },
            "available": True,
            "field_errors": field_errors,
        })

    except UnsupportedAssetError:
        # FIX (Bug 5): let "unsupported asset" bubble up so the API
        # layer can return a distinct 400 UNSUPPORTED_ASSET instead
        # of a generic 502 market-unavailable response.
        raise

    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        logger.warning("[MARKET] CoinGecko parse failed: %s", exc)
        market = empty_market_data(symbol)
        market["unavailable_reason"] = f"CoinGecko response parsing failed: {exc}."
        return market

    except Exception as exc:
        logger.warning("[MARKET] CoinGecko failed unexpectedly: %s", exc)
        market = empty_market_data(symbol)
        market["unavailable_reason"] = f"CoinGecko request failed unexpectedly: {exc}."
        return market


def _read_market_number(
    payload: dict,
    key: str,
    source: str,
    field_errors: dict,
):
    """Read one numeric provider field without affecting other fields."""

    try:
        value = optional_numeric(payload.get(key))
        if value is None:
            field_errors[key] = f"{source} returned no usable {key}."
            return 0
        return value
    except Exception as exc:
        field_errors[key] = f"{source} {key} parsing failed: {exc}."
        logger.exception("[MARKET] %s field %s failed", source, key)
        return 0


def fetch_market_data(
    symbol: str,
    force_refresh: bool = False,
    skip_7d_enrich: bool = False,
) -> dict:
    """CoinGecko-only market fetcher with stale-cache fallback."""

    try:

        symbol = normalize_symbol(symbol)

        if not symbol:
            return empty_market_data(symbol)

        now = time.time()
        stale_cached = None

        # Always try to populate stale_cached so that if a forced refresh fails,
        # we can fall back to the last known good state.
        try:
            with _cache_lock:
                cached = _market_cache.get(symbol)

            if isinstance(cached, dict) and cached:
                if cached.get("available"):
                    stale_cached = dict(cached)

                if not force_refresh:
                    cached_at = numeric(
                        cached.get("_cached_at", 0),
                        default=0,
                    )

                    effective_ttl = 86400 if symbol.upper() == "BTC" else MARKET_CACHE_TTL
                    if (
                        cached.get("available")
                        and (now - cached_at) < effective_ttl
                    ):
                        result = dict(cached)
                        result.pop("_cached_at", None)

                        logger.info(
                            "[MARKET] %s cache HIT (source=%s, age=%.0fs)",
                            symbol,
                            result.get("source", "unknown"),
                            now - cached_at,
                        )

                        return json_safe(result)

        except Exception as exc:
            logger.debug("Market cache read failed: %s", exc)

        # Per-symbol lock to prevent duplicate concurrent calls
        lock = _get_symbol_fetch_lock(symbol)

        with lock:
            # Re-check cache after acquiring lock
            try:
                with _cache_lock:
                    cached = _market_cache.get(symbol)

                if isinstance(cached, dict) and cached:
                    if cached.get("available"):
                        stale_cached = dict(cached)

                    if not force_refresh:
                        cached_at = numeric(
                            cached.get("_cached_at", 0),
                            default=0,
                        )

                        effective_ttl = 86400 if symbol.upper() == "BTC" else MARKET_CACHE_TTL
                        if (
                            cached.get("available")
                            and (now - cached_at) < effective_ttl
                        ):
                            result = dict(cached)
                            result.pop("_cached_at", None)

                            logger.info(
                                "[MARKET] %s cache HIT after lock (source=%s)",
                                symbol,
                                result.get("source", "unknown"),
                            )

                            return json_safe(result)

            except Exception:
                pass

            logger.info("[MARKET] %s cache MISS — fetching from CoinGecko", symbol)

            market = empty_market_data(symbol)

            # CoinGecko is the single source. fetch_coingecko_market()
            # already retries internally on transient errors; if it
            # still returns unavailable we fall through to the stale
            # cache below.
            try:
                market = fetch_coingecko_market(symbol)
            except UnsupportedAssetError:
                # FIX (Bug 5): propagate so the API layer can return a
                # distinct 400 UNSUPPORTED_ASSET. Not a provider
                # failure — do not touch the failure streak.
                raise
            except Exception as exc:
                logger.exception(
                    "[MARKET] CoinGecko failed for %s: %s",
                    symbol,
                    exc,
                )
                market = empty_market_data(symbol)
                market["unavailable_reason"] = (
                    f"CoinGecko request failed unexpectedly: {exc}."
                )

            # Cache market cap from a successful snapshot so that a
            # later stale-serve path can report it even if CoinGecko
            # is down on the next request.
            if (
                isinstance(market, dict)
                and market.get("available")
            ):
                primary_cap = optional_numeric(
                    market.get("market_cap")
                )
                if primary_cap is not None:
                    with _cache_lock:
                        _market_cap_cache[symbol] = {
                            "value": primary_cap,
                            "timestamp": market.get(
                                "timestamp",
                                utc_now_iso(),
                            ),
                            "cached_at": time.time(),
                        }

            if not market.get("available"):
                logger.warning(
                    "[MARKET] %s CoinGecko unavailable: %s",
                    symbol,
                    market.get("unavailable_reason", "unknown"),
                )

                if stale_cached:
                    cached_at = numeric(
                        stale_cached.get("_cached_at", 0),
                        default=0,
                    )
                    # Only serve stale if it isn't hopelessly old.
                    if (now - cached_at) < MARKET_STALE_MAX_AGE:
                        market = dict(stale_cached)
                        market.pop("_cached_at", None)
                        market["stale"] = True
                        market["stale_reason"] = (
                            "CoinGecko is temporarily unavailable; "
                            "serving the last known snapshot."
                        )

            # --------------------------------------------------------
            # Binance / CoinMarketCap fallback
            # --------------------------------------------------------
            # Only reached when:
            #   1. CoinGecko live call returned unavailable, AND
            #   2. Stale cache is missing or too old.
            # The entire market dict is replaced — fields from two
            # providers are never mixed within one report.
            #
            # FIX: Binance is geoblocked (HTTP 451) from Render's IP
            # ranges — this is a permanent network-level block, not a
            # transient failure, so calling it on every CoinGecko
            # failure only adds latency and log noise with zero chance
            # of success. Gated behind ENABLE_BINANCE_FALLBACK (default
            # off); re-enable if you move to a host Binance doesn't block.
            # --------------------------------------------------------
            if not market.get("available") and ENABLE_BINANCE_FALLBACK:
                try:
                    binance_market = fetch_binance_market(symbol)
                    if isinstance(binance_market, dict) and binance_market.get("available"):
                        market = binance_market
                        market["is_fallback_provider"] = True
                        logger.info(
                            "[MARKET] %s served by fallback provider Binance",
                            symbol,
                        )
                except Exception as exc:
                    logger.warning("[MARKET] Binance fallback failed for %s: %s", symbol, exc)

            if not market.get("available") and CMC_API_KEY:
                try:
                    cmc_market = fetch_cmc_market(symbol)
                    if isinstance(cmc_market, dict) and cmc_market.get("available"):
                        market = cmc_market
                        market["is_fallback_provider"] = True
                        logger.info(
                            "[MARKET] %s served by fallback provider CoinMarketCap",
                            symbol,
                        )
                except Exception as exc:
                    logger.warning(
                        "[MARKET] CMC fallback failed for %s: %s",
                        symbol,
                        exc,
                    )

            market.setdefault("source_timestamps", {})
            if market.get("source") and market.get("timestamp"):
                market["source_timestamps"].setdefault(
                    market["source"],
                    market["timestamp"],
                )

            # Enrich with 7d change from history if needed.
            # P1: when the caller already has the history series (e.g.
            # run_analysis fetched the 30-day window), it passes
            # skip_7d_enrich=True and enriches the market itself using
            # that same series — avoiding a second, overlapping 8-day
            # CoinGecko request.
            if not market.get("stale") and not skip_7d_enrich:
                try:
                    market = enrich_market_7d(
                        market,
                        symbol,
                        force_refresh=force_refresh,
                    )

                except Exception as exc:
                    logger.debug("Market 7d enrichment failed: %s", exc)

            if not isinstance(market, dict):
                market = empty_market_data(symbol)

            market = json_safe(market)

            # Cache only usable snapshots. A 429/error must never poison
            # the cache and turn a temporary provider failure permanent.
            if market.get("available") and not market.get("stale"):
                try:
                    cache_value = dict(market)
                    cache_value["_cached_at"] = time.time()

                    with _cache_lock:
                        _market_cache[symbol] = cache_value

                except Exception as exc:
                    logger.debug("Market cache write failed: %s", exc)

            logger.info(
                "[MARKET] %s returning source=%s available=%s",
                symbol,
                market.get("source", "unknown"),
                market.get("available", False),
            )

            return market

    except UnsupportedAssetError:
        # FIX (Bug 5): propagate so /api/analyze and /api/market can
        # return a distinct 400 UNSUPPORTED_ASSET response.
        raise

    except Exception as exc:

        logger.warning(
            "fetch_market_data failed unexpectedly: %s",
            exc,
        )

        try:
            return empty_market_data(symbol)
        except Exception:
            return empty_market_data("")


def _price_series_change(
    prices: list,
    lookback: int = 7,
):
    """
    Compute the percentage change over the trailing
    ``lookback`` observations from a daily price series.

    Also returns the actual lookback window used, which may be
    shorter than requested if the price series has fewer points
    than expected (e.g., partial history data).

    Returns:
        tuple: (change_pct, actual_lookback) where:
            change_pct: float or None - percentage change, or None
                if the series is too short or anchor price is invalid.
            actual_lookback: int or None - the actual number of data
                points between latest and anchor, or None if unusable.
    """

    if not isinstance(
        prices,
        list,
    ) or not prices:
        return None, None

    clean = []

    for raw in prices:

        value = optional_numeric(
            raw
        )

        if (
            value is not None
            and value > 0
        ):
            clean.append(value)

    if len(clean) < 2:
        return None, None

    latest = clean[-1]

    requested_lookback = max(
        1,
        _safe_lookback(lookback),
    )

    anchor_index = max(
        0,
        len(clean) - 1 - requested_lookback,
    )

    anchor = clean[anchor_index]

    # Calculate actual lookback window used
    actual_lookback = len(clean) - 1 - anchor_index

    change = percentage_change(
        latest,
        anchor,
    )

    return change, actual_lookback


def enrich_market_7d(
    market: dict,
    symbol: str,
    force_refresh: bool = False,
    history: list = None,
) -> dict:
    """
    Populate ``price_change_7d_pct`` on a market payload when
    the provider itself did not supply it.

    Uses the already-cached (or freshly fetched) daily price
    series so the dashboard's "7D CHANGE" card never renders
    an empty dash while history data is available.

    NOTE: fetch_price_history() is CoinGecko-only, so the
    recomputed value comes from the same CoinGecko dataset as the
    live snapshot — no cross-provider drift can occur. This path
    only activates when CoinGecko's /coins/markets response didn't
    include a usable price_change_percentage_7d_in_currency field.

    P1: when ``history`` is supplied (e.g. from run_analysis()'s
    30-day series), reuse it directly instead of triggering a
    second independent CoinGecko call for an overlapping 8-day
    window. This keeps a single analysis to exactly one history
    request per symbol.
    """

    try:

        market = (
            dict(market)
            if isinstance(
                market,
                dict,
            )
            else {}
        )

        if market.get(
            "price_change_7d_pct"
        ) is not None:
            return json_safe(market)

        symbol = normalize_symbol(
            symbol
        )

        if not symbol:
            return json_safe(market)

        if history is not None:
            # P1 — caller already has the history series; use the last
            # 8 entries for the 7d lookback instead of fetching again.
            if not isinstance(history, list):
                history = []
            history = history[-8:] if len(history) > 8 else list(history)
        else:
            history = fetch_price_history(
                symbol,
                days=8,
            )

        change_7d, actual_lookback = _price_series_change(
            _prices_only(history),
            lookback=7,
        )

        if change_7d is None:
            change_7d = optional_numeric(
                market.get(
                    "change_7d_pct"
                )
            )
            actual_lookback = None

        if change_7d is not None:
            market[
                "price_change_7d_pct"
            ] = round(
                float(change_7d),
                2,
            )
            # Include actual lookback window so consumers know
            # if the "7d" change was computed over a shorter
            # period due to partial history data.
            if actual_lookback is not None and actual_lookback < 7:
                market[
                    "price_change_7d_actual_days"
                ] = actual_lookback
                market[
                    "price_change_7d_is_partial"
                ] = True

        return json_safe(market)

    except Exception as exc:

        logger.debug(
            "enrich_market_7d failed: %s",
            exc,
        )

        try:

            if isinstance(
                market,
                dict,
            ):
                return json_safe(market)

        except Exception:
            pass

        return {}


def fetch_coingecko_history(
    symbol: str,
    days: int = SUPPORTED_HISTORY_DAYS,
) -> list:
    """
    Fetch historical daily closing prices from CoinGecko.

    CoinGecko is the single source for all historical price data.
    Uses the same resolve_coin_id() path as fetch_coingecko_market()
    so the historical series and the live snapshot come from one
    dataset. Retries internally on transient errors (timeout, 5xx,
    connection reset) with short exponential backoff. 429s are NOT
    retried here — they are handled by the provider cooldown system.

    P2: returns a list of {"timestamp": <UNIX ms int>, "price": <float>}
    dicts (preserving CoinGecko-provided timestamps) rather than bare
    floats. Callers that only need the price values should use
    ``_prices_only(series)`` to extract them.
    """

    symbol = normalize_symbol(
        symbol
    )

    coin_id = resolve_coin_id(
        symbol
    )

    if not coin_id:
        return []

    # Retry loop — same rationale as fetch_coingecko_market(): a
    # single transient hiccup shouldn't take down the whole report.
    last_error_reason = None
    response = None
    status_code = None
    for attempt in range(1, COINGECKO_MAX_RETRIES + 1):
        response, status_code, error_reason = _http_get_market(
            f"{COINGECKO_API_URL}/coins/"
            f"{quote(coin_id, safe='')}/market_chart",
            params={
                "vs_currency": "usd",
                "days": _safe_lookback(
                    days,
                    default=SUPPORTED_HISTORY_DAYS,
                ),
                "interval": "daily",
            },
            timeout=MARKET_TIMEOUT,
        )

        if response is not None and (status_code is None or status_code < 400):
            break

        last_error_reason = error_reason

        retryable = False
        smart_wait = None
        if response is None:
            retryable = True
        elif status_code is not None and status_code >= 500:
            retryable = True
        elif status_code == 429:
            match = re.search(r"retry_after=([0-9]+(?:\.[0-9]+)?)", str(error_reason or ""))
            if match:
                retry_after_val = float(match.group(1))
                if retry_after_val <= 2.0:
                    retryable = True
                    smart_wait = retry_after_val + 1.0

        if not retryable or attempt >= COINGECKO_MAX_RETRIES:
            break

        if smart_wait is not None:
            backoff = smart_wait
            logger.info(
                "[HISTORY] CoinGecko rate limited (429) for %s. Smart waiting %.1fs before retry...",
                symbol,
                backoff,
            )
        else:
            backoff = 0.5 * (2 ** (attempt - 1))
            logger.info(
                "[HISTORY] CoinGecko attempt %d/%d for %s after %s, retrying in %.1fs",
                attempt,
                COINGECKO_MAX_RETRIES,
                symbol,
                error_reason or f"HTTP {status_code}",
                backoff,
            )
        time.sleep(backoff)

    if response is None:
        logger.info(
            "[HISTORY] CoinGecko unavailable for %s: %s",
            symbol,
            last_error_reason or "no response",
        )
        return []

    if status_code is not None and status_code >= 400:
        logger.info(
            "[HISTORY] CoinGecko returned %s for %s",
            last_error_reason or f"HTTP {status_code}",
            symbol,
        )
        return []

    try:

        payload = response.json()

        if not isinstance(
            payload,
            dict,
        ):
            return []

        prices = payload.get(
            "prices",
            [],
        )

        if not isinstance(
            prices,
            list,
        ):
            return []

        result = []

        for item in prices:

            if (
                not isinstance(
                    item,
                    list,
                )
                or len(item) < 2
            ):
                continue

            timestamp_ms = optional_numeric(
                item[0]
            )

            price = optional_numeric(
                item[1]
            )

            if (
                price is None
                or price <= 0
            ):
                continue

            # P2: preserve the CoinGecko-provided timestamp so beta
            # alignment can join by calendar date rather than by raw
            # list position.
            if timestamp_ms is None:
                timestamp_ms = 0

            result.append({
                "timestamp": int(timestamp_ms),
                "price": price,
            })

        return result

    except (
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
    ) as exc:

        logger.warning(
            "CoinGecko history parsing failed: %s",
            exc,
        )

        return []

    except Exception as exc:

        logger.warning(
            "CoinGecko history failed unexpectedly: %s",
            exc,
        )

        return []


def _safe_lookback(
    value,
    default: int = 7,
) -> int:
    """Coerce a lookback window to a positive int without raising."""
    try:
        number = int(value)
        if number <= 0:
            return int(default)
        return number
    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        try:
            return int(default)
        except Exception:
            return 7


def _prices_only(series: list) -> list:
    """Extract bare price floats from a rich history series (P2).

    Handles both the new ``{"timestamp": ..., "price": ...}`` dicts and
    bare floats for backward compatibility with any cached legacy data.
    """
    if not isinstance(series, list):
        return []
    prices = []
    for item in series:
        if isinstance(item, dict):
            price = optional_numeric(item.get("price"))
        else:
            price = optional_numeric(item)
        if price is not None and price > 0:
            prices.append(price)
    return prices


def fetch_price_history(
    symbol: str,
    days: int = SUPPORTED_HISTORY_DAYS,
) -> list:

    try:

        symbol = normalize_symbol(
            symbol
        )

        if not symbol:
            return []

        days = max(
            1,
            min(
                SUPPORTED_HISTORY_DAYS,
                _safe_lookback(
                    days,
                    default=SUPPORTED_HISTORY_DAYS,
                ),
            ),
        )

        cache_key = (
            f"{symbol}:{days}"
        )

        now = time.time()
        stale_prices = None
        cached_at = 0

        try:

            with _cache_lock:

                cached = _history_cache.get(
                    cache_key
                )

            if isinstance(
                cached,
                dict,
            ) and cached:
                stale_prices = cached.get("prices", [])
                
                cached_at = numeric(
                    cached.get(
                        "_cached_at",
                        0,
                    ),
                    default=0,
                )

                # BTC history is a global benchmark that updates daily; cache it for 24h
                effective_ttl = 86400 if symbol.upper() == "BTC" else HISTORY_CACHE_TTL

                if (
                    now - cached_at
                    < effective_ttl
                ):

                    cached_prices = stale_prices

                    if isinstance(
                        cached_prices,
                        list,
                    ):
                        logger.info(
                            "[HISTORY] symbol=%s source=memory_cache candles=%d",
                            symbol,
                            len(cached_prices),
                        )
                        return list(cached_prices)

        except Exception as exc:

            logger.debug(
                "History cache read failed: %s",
                exc,
            )

        # CoinGecko-only price history (daily OHLC series used for
        # volatility, beta, and max-drawdown). Cached per
        # (symbol, days) with HISTORY_CACHE_TTL. The same resolved
        # coin_id is used here as in fetch_coingecko_market() so the
        # historical series and the live snapshot come from one dataset.
        #
        # FIX: skip the live call entirely if CoinGecko is already on
        # cooldown (e.g. the market fetch just got 429'd). Firing a
        # second request into the same rate-limit window wastes a call
        # against a quota that will fail anyway, and delays falling
        # through to the stale cache / fallback providers below.
        if _provider_is_cooling("CoinGecko"):
            logger.info(
                "[HISTORY] symbol=%s CoinGecko cooling down — skipping live call",
                symbol,
            )
            prices = []
        else:
            prices = fetch_coingecko_history(symbol, days)
        history_source = "CoinGecko"

        if not isinstance(
            prices,
            list,
        ):
            prices = []

        logger.info(
            "[HISTORY] symbol=%s source=%s candles=%d",
            symbol,
            history_source,
            len(prices),
        )

        if not prices and stale_prices and isinstance(stale_prices, list):
            if (now - cached_at) < HISTORY_STALE_MAX_AGE:
                logger.info(
                    "[HISTORY] symbol=%s source=stale_cache candles=%d",
                    symbol,
                    len(stale_prices),
                )
                return list(stale_prices)

        # --------------------------------------------------------
        # Binance history fallback
        # --------------------------------------------------------
        # FIX: gated off by default — see ENABLE_BINANCE_FALLBACK note
        # in fetch_market_data(). Binance returns HTTP 451 (geoblocked)
        # on Render, so this call never succeeds there; it only adds
        # latency to the failure path.
        if not prices and ENABLE_BINANCE_FALLBACK:
            try:
                binance_prices = fetch_binance_history(symbol, days)
                if isinstance(binance_prices, list) and len(binance_prices) > 0:
                    prices = binance_prices
                    history_source = "Binance"
                    logger.info(
                        "[HISTORY] %s served by fallback provider Binance (%d candles)",
                        symbol,
                        len(prices),
                    )
            except Exception as exc:
                logger.warning("[HISTORY] Binance history fallback failed for %s: %s", symbol, exc)

        # --------------------------------------------------------
        # CoinMarketCap history fallback
        # --------------------------------------------------------
        # Only reached when CoinGecko history AND stale cache both
        # failed. The full window must be available from CMC — partial
        # results are discarded to prevent splicing two providers.
        # --------------------------------------------------------
        if not prices and CMC_API_KEY:
            try:
                cmc_prices = fetch_cmc_history(symbol, days)
                if isinstance(cmc_prices, list) and len(cmc_prices) >= days:
                    prices = cmc_prices
                    history_source = "CoinMarketCap"
                    logger.info(
                        "[HISTORY] %s served by fallback provider CoinMarketCap (%d candles)",
                        symbol,
                        len(prices),
                    )
            except Exception as exc:
                logger.warning(
                    "[HISTORY] CMC history fallback failed for %s: %s",
                    symbol,
                    exc,
                )

        # Only cache NON-EMPTY results. Caching an empty list would
        # freeze "0 candles" for the full TTL when the provider fails
        # temporarily (e.g., 451/429), causing volatility, beta and
        # 7d change to stay missing even after the provider recovers.
        if prices:

            try:

                with _cache_lock:

                    _history_cache[
                        cache_key
                    ] = {
                        "prices": list(prices),
                        "_cached_at": now,
                    }

            except Exception as exc:

                logger.debug(
                    "History cache write failed: %s",
                    exc,
                )

        return list(prices)

    except Exception as exc:

        logger.warning(
            "fetch_price_history failed: %s",
            exc,
        )

        return []


def _series_date_map(
    series: list,
) -> dict:
    """
    Build a {date: price} mapping from a rich history series (P2).

    Accepts both the new ``{"timestamp": <UNIX ms>, "price": <float>}``
    dicts and bare floats (for backward compatibility — bare floats are
    skipped since they carry no date information). Timestamps are
    normalized to UTC calendar dates so two series can be joined by
    the days they actually share, regardless of differing lengths or
    small gaps.
    """
    if not isinstance(series, list):
        return {}

    date_map = {}
    for item in series:
        if isinstance(item, dict):
            timestamp_ms = optional_numeric(item.get("timestamp"))
            price = optional_numeric(item.get("price"))
        else:
            # Bare float — no timestamp, cannot align by date.
            continue

        if price is None or price <= 0:
            continue
        if timestamp_ms is None or timestamp_ms <= 0:
            continue

        try:
            dt = datetime.fromtimestamp(
                int(timestamp_ms) / 1000.0,
                tz=timezone.utc,
            )
            day = dt.date()
        except (OSError, OverflowError, ValueError):
            continue

        # If CoinGecko returns multiple points for the same day (e.g. a
        # finalizing candle plus the next day's first), keep the latest
        # one — it represents the closing price for that calendar day.
        date_map[day] = price

    return date_map


def _align_series_by_date(
    asset_series: list,
    btc_series: list,
) -> tuple:
    """
    Align two rich history series by shared calendar date (P2).

    Returns ``(asset_prices_aligned, btc_prices_aligned,
    aligned_dates_sorted)`` — three parallel lists where entry i of each
    corresponds to the same calendar day. Only dates present in *both*
    series are included, so a return on day T is always paired with a
    return on day T for the other asset, never with a return on a
    different day.
    """
    asset_map = _series_date_map(asset_series)
    btc_map = _series_date_map(btc_series)

    common_days = sorted(
        set(asset_map.keys()) & set(btc_map.keys())
    )

    asset_aligned = [asset_map[d] for d in common_days]
    btc_aligned = [btc_map[d] for d in common_days]

    return asset_aligned, btc_aligned, common_days



import logging
logger = logging.getLogger(__name__)
import re
import time
import math
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple, Dict
from flask import request, abort
from config import *
from extensions import *

import threading
_rate_limit_lock = threading.Lock()
_rate_limit_buckets = {}
_symbol_fetch_locks_guard = threading.Lock()
_symbol_fetch_locks = {}
_provider_cooldown_lock = threading.Lock()
_provider_cooldown = {}
_provider_failure_counts = {}
_coin_resolution_cache = {}


def _rate_limit_check(
    bucket: str,
    max_attempts: int,
    window_seconds: int,
) -> tuple:
    """
    Returns (allowed: bool, remaining: int, retry_after: int).
    Prunes stale entries in the same call so the dict stays bounded.
    """

    now = time.time()
    window_start = now - window_seconds

    with _rate_limit_lock:
        entries = _rate_limit_buckets.setdefault(bucket, [])
        # Prune stale timestamps
        entries[:] = [
            ts for ts in entries if ts > window_start
        ]

        if len(entries) >= max_attempts:
            oldest = min(entries)
            retry_after = int(oldest + window_seconds - now) + 1
            return False, 0, max(1, retry_after)

        entries.append(now)
        remaining = max_attempts - len(entries)
        return True, remaining, 0


def _client_ip() -> str:
    """Best-effort client IP, honoring X-Forwarded-For behind a proxy."""
    forwarded = request.headers.get(
        "X-Forwarded-For",
        "",
    )
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    return request.remote_addr or "unknown"


def rate_limit(
    max_attempts: int,
    window_seconds: int,
    bucket_prefix: str,
) -> Optional[tuple]:
    """
    Decorator factory: returns a 429 response tuple if the limit is
    exceeded, or None if the request is allowed to proceed.

    Usage inside a route:
        blocked = rate_limit(5, 900, "login")(
            lambda: f"{_client_ip()}:{email.lower().strip()}"
        )
        if blocked is not None:
            return blocked
    """

    def resolver(resolver_fn):
        bucket = f"{bucket_prefix}:{resolver_fn()}"
        allowed, remaining, retry_after = _rate_limit_check(
            bucket,
            max_attempts,
            window_seconds,
        )
        if not allowed:
            logger.warning(
                "[RATE LIMIT] bucket=%s blocked (retry_after=%ds)",
                bucket,
                retry_after,
            )
            response = jsonify({
                "success": False,
                "error": (
                    f"Too many attempts. Try again in "
                    f"{retry_after} seconds."
                ),
            })
            response.status_code = 429
            response.headers["Retry-After"] = str(retry_after)
            return response
        return None

    return resolver


def _periodic_cache_cleanup() -> None:
    """Purge expired entries from every in-process cache dict."""

    now = time.time()

    try:

        # _market_cache entries carry "_cached_at"
        with _cache_lock:
            expired_markets = [
                k
                for k, v in _market_cache.items()
                if not isinstance(v, dict)
                or (now - numeric(
                    v.get("_cached_at", 0),
                    default=0,
                )) > MARKET_STALE_MAX_AGE
            ]
            for k in expired_markets:
                _market_cache.pop(k, None)

        # _history_cache entries carry "_cached_at"
        with _cache_lock:
            expired_history = [
                k
                for k, v in _history_cache.items()
                if not isinstance(v, dict)
                or (now - numeric(
                    v.get("_cached_at", 0),
                    default=0,
                )) > MARKET_STALE_MAX_AGE
            ]
            for k in expired_history:
                _history_cache.pop(k, None)

        # _coin_resolution_cache entries carry "cached_at"
        with _cache_lock:
            expired_resolutions = [
                k
                for k, v in _coin_resolution_cache.items()
                if not isinstance(v, dict)
                or (now - float(v.get("cached_at") or 0))
                > max(COIN_RESOLUTION_CACHE_TTL, COIN_RESOLUTION_MISS_TTL) * 2
            ]
            for k in expired_resolutions:
                _coin_resolution_cache.pop(k, None)

        # _market_cap_cache entries carry "cached_at"
        with _cache_lock:
            expired_caps = [
                k
                for k, v in _market_cap_cache.items()
                if not isinstance(v, dict)
                or (now - numeric(
                    v.get("cached_at", 0),
                    default=0,
                )) > MARKET_STALE_MAX_AGE
            ]
            for k in expired_caps:
                _market_cap_cache.pop(k, None)

        with _provider_cooldown_lock:
            expired_cooldowns = [
                k
                for k, v in _provider_cooldown.items()
                if isinstance(v, dict)
                and time.time() >= v.get("until", 0)
            ]
            for k in expired_cooldowns:
                _provider_cooldown.pop(k, None)
                _provider_failure_counts.pop(k, None)

        # _symbol_fetch_locks: prune only stale (garbage-collected) refs
        # is not applicable — Lock objects are cheap and never GC'd
        # while referenced. We leave them; their count is bounded by
        # the number of distinct symbols fetched, which is small.

        total_purged = (
            len(expired_markets)
            + len(expired_history)
            + len(expired_resolutions)
            + len(expired_caps)
            + len(expired_cooldowns)
        )
        if total_purged > 0:
            logger.info(
                "[CLEANUP] purged %d stale cache entries "
                "(market=%d history=%d resolution=%d mcap=%d cooldown=%d)",
                total_purged,
                len(expired_markets),
                len(expired_history),
                len(expired_resolutions),
                len(expired_caps),
                len(expired_cooldowns),
            )

    except Exception as exc:
        logger.warning("[CLEANUP] cache cleanup failed: %s", exc)


def _schedule_cache_cleanup() -> None:
    """Run one cleanup cycle and reschedule the next."""

    try:
        _periodic_cache_cleanup()
    except Exception as exc:
        logger.exception("[CLEANUP] periodic cache cleanup failed: %s", exc)
    finally:
        # Always reschedule — a single failed run must not kill the loop.
        timer = Timer(
            CLEANUP_INTERVAL_SECONDS,
            _schedule_cache_cleanup,
        )
        timer.daemon = True
        timer.start()


def _mask_secret(
    value: str,
) -> str:
    """Return a masked, log-safe representation of a secret."""

    if not value:
        return "(not set)"

    if len(value) <= 8:
        return f"***({len(value)} chars)"

    return (
        f"{value[:4]}…{value[-4:]} "
        f"({len(value)} chars)"
    )


def _provider_is_cooling(
    name: str,
) -> bool:
    """Return True if *name* is currently on cooldown."""
    with _provider_cooldown_lock:
        entry = _provider_cooldown.get(
            name
        )
        if (
            entry
            and isinstance(
                entry,
                dict,
            )
            and time.time() < entry.get(
                "until",
                0
            )
        ):
            logger.info(
                "[MARKET] %s on cooldown (%s), skipping",
                name,
                entry.get(
                    "reason",
                    "cooldown",
                ),
            )
            return True

        # FIX: when a cooldown has expired, also reset the failure
        # count for this provider. Previously the count was only
        # cleared after a successful fetch — but during cooldown the
        # provider is never called, so it could never succeed and
        # the count never reset. Backoff then escalated to the 300s
        # cap permanently ("always on 429 cooldown"). Expiry now
        # starts a fresh cooldown episode at the base duration.
        if name in _provider_cooldown:
            _provider_cooldown.pop(name, None)
            _provider_failure_counts.pop(name, None)

        return False


def _mark_provider_failure(
    name: str,
    status_code,
    reason: str,
) -> None:
    """Record a provider failure and start its cooldown."""
    if status_code == 429:
        retry_after = None
        match = re.search(
            r"retry_after=([0-9]+(?:\.[0-9]+)?)",
            str(reason or ""),
        )

        if match:
            retry_after = float(match.group(1))

        with _provider_cooldown_lock:
            # FIX: if the previous cooldown already expired, this is
            # a fresh episode — start counting from zero so backoff
            # does not inherit escalation from a stale failure count.
            previous = _provider_cooldown.get(name)
            if (
                previous is None
                or time.time() >= previous.get("until", 0)
            ):
                _provider_failure_counts.pop(name, None)

            failures = _provider_failure_counts.get(name, 0) + 1
            _provider_failure_counts[name] = failures

        backoff = min(
            120,
            PROVIDER_COOLDOWN_429 * (2 ** min(failures - 1, 4)),
        )
        seconds = max(
            backoff,
            ceil(retry_after or 0),
        )
    elif status_code in (
        403,
        451,
    ):
        seconds = PROVIDER_COOLDOWN_FORBIDDEN
    elif (
        status_code is not None
        and status_code >= 500
    ):
        seconds = PROVIDER_COOLDOWN_DEFAULT
    else:
        seconds = PROVIDER_COOLDOWN_DEFAULT

    with _provider_cooldown_lock:
        _provider_cooldown[name] = {
            "until": time.time() + seconds,
            "reason": reason,
        }

    logger.warning(
        "[MARKET] %s marked on cooldown for %ds (%s)",
        name,
        seconds,
        reason,
    )


def _clear_provider_success(
    name: str,
) -> None:
    """Clear a provider's cooldown after a successful fetch."""
    with _provider_cooldown_lock:
        if name in _provider_cooldown:
            logger.info(
                "[MARKET] %s recovered, clearing cooldown",
                name,
            )
            _provider_cooldown.pop(
                name,
                None,
            )
        _provider_failure_counts.pop(name, None)


def _get_symbol_fetch_lock(
    symbol: str,
) -> Lock:
    """Return (creating if necessary) the per-symbol dedup lock."""
    with _symbol_fetch_locks_guard:
        lock = _symbol_fetch_locks.get(
            symbol
        )
        if lock is None:
            lock = Lock()
            _symbol_fetch_locks[symbol] = lock
        return lock


def utc_now_iso() -> str:

    return datetime.now(
        timezone.utc
    ).isoformat()


def numeric(
    value: Any,
    default: float = 0.0,
) -> float:
    """
    Convert a value to a finite float.

    Never return NaN or infinity.
    """

    try:

        if value is None:
            raise TypeError(
                "None is not numeric"
            )

        if isinstance(
            value,
            bool,
        ):
            return float(value)

        if isinstance(
            value,
            (
                list,
                dict,
                tuple,
                set,
            ),
        ):
            raise TypeError(
                "Non-scalar is not numeric"
            )

        if isinstance(
            value,
            (
                str,
                bytes,
            ),
        ):

            try:
                text = value.decode() if isinstance(
                    value,
                    bytes,
                ) else value
            except Exception:
                raise TypeError(
                    "Undecodable bytes"
                )

            text = str(text).strip().replace(
                ",",
                "",
            )

            if not text:
                raise ValueError(
                    "Empty numeric string"
                )

            result = float(text)

        else:

            result = float(value)

        if not math.isfinite(result):
            return float(default)

        return result

    except (
        TypeError,
        ValueError,
        ArithmeticError,
        OverflowError,
    ):

        try:
            fallback = float(default)

            if not math.isfinite(fallback):
                return 0.0

            return fallback

        except (
            TypeError,
            ValueError,
            ArithmeticError,
            OverflowError,
        ):

            return 0.0


def optional_numeric(
    value: Any,
) -> Optional[float]:
    """
    Convert a value to float or return None.

    Unlike numeric(), this preserves unavailable data.
    """

    try:

        if value is None:
            return None

        if isinstance(
            value,
            bool,
        ):
            return float(value)

        if isinstance(
            value,
            (
                list,
                dict,
                tuple,
                set,
            ),
        ):
            return None

        if isinstance(
            value,
            (
                str,
                bytes,
            ),
        ):

            try:
                text = value.decode() if isinstance(
                    value,
                    bytes,
                ) else value
            except Exception:
                return None

            text = str(text).strip().replace(
                ",",
                "",
            )

            if not text:
                return None

            result = float(text)

        else:

            result = float(value)

        if not math.isfinite(result):
            return None

        return result

    except (
        TypeError,
        ValueError,
        ArithmeticError,
        OverflowError,
    ):

        return None


def clamp(
    value: Any,
    minimum: float,
    maximum: float,
) -> float:

    value = numeric(value)

    return max(
        minimum,
        min(
            maximum,
            value,
        ),
    )


def safe_divide(
    numerator: Any,
    denominator: Any,
    default: float = 0.0,
) -> float:

    denominator = numeric(
        denominator,
        default=0.0,
    )

    if denominator == 0:
        return float(default)

    return numeric(
        numeric(numerator)
        / denominator,
        default=default,
    )


def percentage_change(
    current: Any,
    previous: Any,
) -> Optional[float]:

    current = optional_numeric(
        current
    )

    previous = optional_numeric(
        previous
    )

    if (
        current is None
        or previous is None
    ):
        return None

    if previous == 0:
        return None

    return (
        (
            current - previous
        )
        / abs(previous)
    ) * 100.0


def clean_text(
    value: Any,
    default: str = "",
    max_length: int = 2000,
) -> str:

    if value is None:
        return default

    text = str(value).strip()

    if not text:
        return default

    return text[:max_length]


def normalize_symbol(
    symbol: Any,
) -> str:

    if symbol is None:
        return ""

    symbol = str(
        symbol
    ).strip().upper()

    symbol = re.sub(
        r"[^A-Z0-9]",
        "",
        symbol,
    )

    return symbol[
        :MAX_TOKEN_SYMBOL_LENGTH
    ]


def is_valid_symbol(
    symbol: Any,
) -> bool:

    normalized = normalize_symbol(
        symbol
    )

    if not normalized:
        return False

    return bool(
        re.fullmatch(
            r"[A-Z0-9]{1,15}",
            normalized,
        )
    )


def json_safe(
    value: Any,
) -> Any:

    if value is None:
        return None

    # bool must be checked before int (bool subclasses int).
    if isinstance(
        value,
        bool,
    ):
        return value

    if isinstance(
        value,
        (
            str,
            int,
        ),
    ):
        return value

    if isinstance(
        value,
        float,
    ):

        if math.isfinite(value):
            return value

        return None

    if isinstance(
        value,
        Decimal,
    ):

        try:

            number = float(value)

            if math.isfinite(number):
                return number

            return None

        except (
            ArithmeticError,
            TypeError,
            ValueError,
            OverflowError,
        ):
            return None

    if isinstance(
        value,
        (
            date,
            datetime,
        ),
    ):
        try:
            return value.isoformat()
        except Exception:
            return None

    if isinstance(
        value,
        dict,
    ):

        try:
            items = list(value.items())
        except Exception:
            return None

        safe_dict = {}

        for key, item in items:

            try:
                safe_key = str(key)
            except Exception:
                continue

            safe_dict[safe_key] = json_safe(item)

        return safe_dict

    if isinstance(
        value,
        (
            list,
            tuple,
            set,
            frozenset,
        ),
    ):

        try:
            items = list(value)
        except Exception:
            return []

        return [
            json_safe(item)
            for item in items
        ]

    try:
        return str(value)

    except Exception:
        return None


def empty_market_data(
    symbol: str,
) -> dict:

    return {
        "symbol": normalize_symbol(
            symbol
        ),
        "price": None,
        "price_change_24h_pct": None,
        "price_change_7d_pct": None,
        "volume_24h": None,
        "market_cap": None,
        "high_24h": None,
        "low_24h": None,
        "source": "unavailable",
        "unavailable_reason": "CoinGecko did not return a usable market snapshot.",
        "timestamp": utc_now_iso(),
        "available": False,
    }


def first_defined(*values):
    """
    Return the first value that is not None.

    Important:
    False, 0 and empty strings are valid values and are
    therefore not treated as missing.
    """

    for value in values:
        if value is not None:
            return value

    return None


def format_number(
    value,
    decimals=2,
):
    """
    Safely format a numeric value for human-readable text.
    """

    if value is None:
        return "N/A"

    try:
        number = float(value)

        if not math.isfinite(number):
            return "N/A"

        return f"{number:,.{decimals}f}"

    except (
        TypeError,
        ValueError,
    ):
        return "N/A"



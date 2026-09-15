import logging
import math
import re
import threading
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from threading import Lock, Timer
from typing import Any, Dict, List, Optional, Tuple
from flask import abort, jsonify, request
from config import *
from extensions import *
logger = logging.getLogger(__name__)
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
) -> Tuple[bool, int, int]:
    """
    Check and update an in-process rate-limit bucket.
    Returns:
        (allowed, remaining, retry_after_seconds)
    Stale timestamps are removed during the same operation so
    individual buckets remain bounded.
    """
    try:
        max_attempts = int(max_attempts)
        window_seconds = int(window_seconds)
    except (TypeError, ValueError):
        logger.warning(
            "[RATE LIMIT] Invalid configuration for bucket=%s",
            bucket,
        )
        return False, 0, 1
    if max_attempts <= 0 or window_seconds <= 0:
        logger.warning(
            "[RATE LIMIT] Invalid limits for bucket=%s "
            "(max_attempts=%s, window_seconds=%s)",
            bucket,
            max_attempts,
            window_seconds,
        )
        return False, 0, 1
    now = time.time()
    window_start = now - window_seconds
    with _rate_limit_lock:
        entries = _rate_limit_buckets.setdefault(
            bucket,
            [],
        )
        entries[:] = [
            timestamp
            for timestamp in entries
            if isinstance(timestamp, (int, float))
            and timestamp > window_start
        ]
        if len(entries) >= max_attempts:
            oldest = min(entries)
            retry_after = int(
                oldest + window_seconds - now
            ) + 1
            return (
                False,
                0,
                max(1, retry_after),
            )
        entries.append(now)
        remaining = max_attempts - len(entries)
        return (
            True,
            remaining,
            0,
        )
def _client_ip() -> str:
    """
    Return the best-effort client IP.
    X-Forwarded-For is supported for deployments behind a reverse
    proxy. The first address is treated as the originating client.
    """
    forwarded = request.headers.get(
        "X-Forwarded-For",
        "",
    ).strip()
    if forwarded:
        client_ip = forwarded.split(
            ",",
            1,
        )[0].strip()
        if client_ip:
            return client_ip
    return request.remote_addr or "unknown"
def rate_limit(
    max_attempts: int,
    window_seconds: int,
    bucket_prefix: str,
) -> Optional[tuple]:
    """
    Check a dynamically resolved rate-limit bucket.
    Usage:
        blocked = rate_limit(
            5,
            900,
            "login",
        )(
            lambda: f"{_client_ip()}:{email.lower().strip()}"
        )
        if blocked is not None:
            return blocked
    """
    def resolver(resolver_fn):
        if not callable(resolver_fn):
            logger.warning(
                "[RATE LIMIT] Invalid bucket resolver for prefix=%s",
                bucket_prefix,
            )
            return _api_rate_limit_response(
                1,
            )
        try:
            resolved_bucket = resolver_fn()
        except Exception as exc:
            logger.warning(
                "[RATE LIMIT] Bucket resolver failed: %s",
                exc,
            )
            return _api_rate_limit_response(
                1,
            )
        bucket = (
            f"{bucket_prefix}:{resolved_bucket}"
        )
        allowed, remaining, retry_after = _rate_limit_check(
            bucket,
            max_attempts,
            window_seconds,
        )
        if not allowed:
            logger.warning(
                "[RATE LIMIT] bucket=%s blocked "
                "(retry_after=%ds)",
                bucket,
                retry_after,
            )
            return _api_rate_limit_response(
                retry_after,
            )
        return None
    return resolver
def _api_rate_limit_response(
    retry_after: int,
):
    """Build a standard rate-limit response."""
    retry_after = max(
        1,
        int(retry_after),
    )
    response = jsonify({
        "success": False,
        "error": (
            "Too many attempts. "
            f"Try again in {retry_after} seconds."
        ),
    })
    response.status_code = 429
    response.headers["Retry-After"] = str(
        retry_after
    )
    return response
def _periodic_cache_cleanup() -> None:
    """
    Purge expired entries from in-process caches and rate-limit state.
    Cleanup is best-effort: corruption in one cache must not prevent
    other caches from being cleaned.
    """
    now = time.time()
    total_purged = 0
    expired_markets = 0
    expired_history = 0
    expired_resolutions = 0
    expired_caps = 0
    expired_cooldowns = 0
    expired_rate_limit_buckets = 0
    try:
        with _cache_lock:
            expired_market_keys = []
            for key, value in _market_cache.items():
                if not isinstance(value, dict):
                    expired_market_keys.append(key)
                    continue
                cached_at = numeric(
                    value.get(
                        "_cached_at",
                        0,
                    ),
                    default=0,
                )
                if (
                    now - cached_at
                    > MARKET_STALE_MAX_AGE
                ):
                    expired_market_keys.append(key)
            for key in expired_market_keys:
                _market_cache.pop(
                    key,
                    None,
                )
            expired_markets = len(
                expired_market_keys
            )
    except Exception as exc:
        logger.warning(
            "[CLEANUP] market cache cleanup failed: %s",
            exc,
        )
    try:
        with _cache_lock:
            expired_history_keys = []
            for key, value in _history_cache.items():
                if not isinstance(value, dict):
                    expired_history_keys.append(key)
                    continue
                cached_at = numeric(
                    value.get(
                        "_cached_at",
                        0,
                    ),
                    default=0,
                )
                if (
                    now - cached_at
                    > MARKET_STALE_MAX_AGE
                ):
                    expired_history_keys.append(key)
            for key in expired_history_keys:
                _history_cache.pop(
                    key,
                    None,
                )
            expired_history = len(
                expired_history_keys
            )
    except Exception as exc:
        logger.warning(
            "[CLEANUP] history cache cleanup failed: %s",
            exc,
        )
    try:
        resolution_ttl = max(
            COIN_RESOLUTION_CACHE_TTL,
            COIN_RESOLUTION_MISS_TTL,
        ) * 2
        with _cache_lock:
            expired_resolution_keys = []
            for key, value in _coin_resolution_cache.items():
                if not isinstance(value, dict):
                    expired_resolution_keys.append(key)
                    continue
                cached_at = numeric(
                    value.get(
                        "cached_at",
                        0,
                    ),
                    default=0,
                )
                if (
                    now - cached_at
                    > resolution_ttl
                ):
                    expired_resolution_keys.append(key)
            for key in expired_resolution_keys:
                _coin_resolution_cache.pop(
                    key,
                    None,
                )
            expired_resolutions = len(
                expired_resolution_keys
            )
    except Exception as exc:
        logger.warning(
            "[CLEANUP] resolution cache cleanup failed: %s",
            exc,
        )
    try:
        with _cache_lock:
            expired_cap_keys = []
            for key, value in _market_cap_cache.items():
                if not isinstance(value, dict):
                    expired_cap_keys.append(key)
                    continue
                cached_at = numeric(
                    value.get(
                        "cached_at",
                        0,
                    ),
                    default=0,
                )
                if (
                    now - cached_at
                    > MARKET_STALE_MAX_AGE
                ):
                    expired_cap_keys.append(key)
            for key in expired_cap_keys:
                _market_cap_cache.pop(
                    key,
                    None,
                )
            expired_caps = len(
                expired_cap_keys
            )
    except Exception as exc:
        logger.warning(
            "[CLEANUP] market-cap cache cleanup failed: %s",
            exc,
        )
    try:
        with _provider_cooldown_lock:
            expired_cooldown_keys = []
            for key, value in _provider_cooldown.items():
                if not isinstance(value, dict):
                    expired_cooldown_keys.append(key)
                    continue
                until = numeric(
                    value.get(
                        "until",
                        0,
                    ),
                    default=0,
                )
                if now >= until:
                    expired_cooldown_keys.append(key)
            for key in expired_cooldown_keys:
                _provider_cooldown.pop(
                    key,
                    None,
                )
                _provider_failure_counts.pop(
                    key,
                    None,
                )
            expired_cooldowns = len(
                expired_cooldown_keys
            )
    except Exception as exc:
        logger.warning(
            "[CLEANUP] provider cooldown cleanup failed: %s",
            exc,
        )
    try:
        with _rate_limit_lock:
            empty_or_expired_buckets = []
            for bucket, entries in _rate_limit_buckets.items():
                if not isinstance(entries, list):
                    empty_or_expired_buckets.append(bucket)
                    continue
                cleaned_entries = [
                    timestamp
                    for timestamp in entries
                    if isinstance(timestamp, (int, float))
                    and timestamp > now - max(
                        1,
                        int(
                            CLEANUP_INTERVAL_SECONDS
                        ),
                    )
                ]
                if cleaned_entries:
                    _rate_limit_buckets[bucket] = cleaned_entries
                else:
                    empty_or_expired_buckets.append(bucket)
            for bucket in empty_or_expired_buckets:
                _rate_limit_buckets.pop(
                    bucket,
                    None,
                )
            expired_rate_limit_buckets = len(
                empty_or_expired_buckets
            )
    except Exception as exc:
        logger.warning(
            "[CLEANUP] rate-limit cleanup failed: %s",
            exc,
        )
    total_purged = (
        expired_markets
        + expired_history
        + expired_resolutions
        + expired_caps
        + expired_cooldowns
        + expired_rate_limit_buckets
    )
    if total_purged > 0:
        logger.info(
            "[CLEANUP] purged %d stale cache/state entries "
            "(market=%d history=%d resolution=%d "
            "mcap=%d cooldown=%d rate_limit=%d)",
            total_purged,
            expired_markets,
            expired_history,
            expired_resolutions,
            expired_caps,
            expired_cooldowns,
            expired_rate_limit_buckets,
        )
def _schedule_cache_cleanup() -> None:
    """
    Run one cleanup cycle and schedule the next cycle.
    A failure in one cleanup cycle must never permanently stop
    periodic cleanup.
    """
    try:
        _periodic_cache_cleanup()
    except Exception as exc:
        logger.exception(
            "[CLEANUP] periodic cache cleanup failed: %s",
            exc,
        )
    finally:
        try:
            interval = max(
                1,
                int(
                    CLEANUP_INTERVAL_SECONDS
                ),
            )
            timer = Timer(
                interval,
                _schedule_cache_cleanup,
            )
            timer.daemon = True
            timer.start()
        except Exception as exc:
            logger.exception(
                "[CLEANUP] failed to schedule next cleanup: %s",
                exc,
            )
def _mask_secret(
    value: str,
) -> str:
    """Return a masked, log-safe representation of a secret."""
    if not value:
        return "(not set)"
    value = str(value)
    if len(value) <= 8:
        return f"***({len(value)} chars)"
    return (
        f"{value[:4]}…{value[-4:]} "
        f"({len(value)} chars)"
    )
def _provider_is_cooling(
    name: str,
) -> bool:
    """Return True when a provider is currently on cooldown."""
    now = time.time()
    with _provider_cooldown_lock:
        entry = _provider_cooldown.get(
            name
        )
        if isinstance(entry, dict):
            until = numeric(
                entry.get(
                    "until",
                    0,
                ),
                default=0,
            )
            if now < until:
                logger.info(
                    "[MARKET] %s on cooldown (%s), skipping",
                    name,
                    entry.get(
                        "reason",
                        "cooldown",
                    ),
                )
                return True
            _provider_cooldown.pop(
                name,
                None,
            )
            _provider_failure_counts.pop(
                name,
                None,
            )
        elif entry is not None:
            _provider_cooldown.pop(
                name,
                None,
            )
            _provider_failure_counts.pop(
                name,
                None,
            )
        return False
def _mark_provider_failure(
    name: str,
    status_code,
    reason: str,
) -> None:
    """Record a provider failure and start an appropriate cooldown."""
    normalized_status = optional_numeric(
        status_code
    )
    if (
        normalized_status is not None
        and normalized_status.is_integer()
    ):
        normalized_status = int(
            normalized_status
        )
    if normalized_status == 429:
        retry_after = None
        match = re.search(
            r"retry_after=([0-9]+(?:\.[0-9]+)?)",
            str(reason or ""),
        )
        if match:
            try:
                retry_after = float(
                    match.group(1)
                )
            except (
                TypeError,
                ValueError,
            ):
                retry_after = None
        now = time.time()
        with _provider_cooldown_lock:
            previous = _provider_cooldown.get(
                name
            )
            previous_until = (
                numeric(
                    previous.get(
                        "until",
                        0,
                    ),
                    default=0,
                )
                if isinstance(
                    previous,
                    dict,
                )
                else 0
            )
            if (
                previous is None
                or now >= previous_until
            ):
                _provider_failure_counts.pop(
                    name,
                    None,
                )
            failures = (
                _provider_failure_counts.get(
                    name,
                    0,
                )
                + 1
            )
            _provider_failure_counts[name] = failures
        backoff = min(
            120,
            PROVIDER_COOLDOWN_429
            * (
                2 ** min(
                    failures - 1,
                    4,
                )
            ),
        )
        retry_after_seconds = max(
            0,
            retry_after or 0,
        )
        seconds = max(
            backoff,
            math.ceil(
                retry_after_seconds
            ),
        )
    elif normalized_status in (
        403,
        451,
    ):
        seconds = PROVIDER_COOLDOWN_FORBIDDEN
    elif (
        normalized_status is not None
        and normalized_status >= 500
    ):
        seconds = PROVIDER_COOLDOWN_DEFAULT
    else:
        seconds = PROVIDER_COOLDOWN_DEFAULT
    seconds = max(
        1,
        int(
            numeric(
                seconds,
                default=1,
            )
        ),
    )
    with _provider_cooldown_lock:
        _provider_cooldown[name] = {
            "until": time.time() + seconds,
            "reason": str(
                reason or "provider failure"
            ),
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
    """Clear provider cooldown and failure state after success."""
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
        _provider_failure_counts.pop(
            name,
            None,
        )
def _get_symbol_fetch_lock(
    symbol: str,
) -> Lock:
    """Return a per-symbol lock used to deduplicate concurrent fetches."""
    with _symbol_fetch_locks_guard:
        lock = _symbol_fetch_locks.get(
            symbol
        )
        if lock is None:
            lock = Lock()
            _symbol_fetch_locks[symbol] = lock
        return lock
def utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(
        timezone.utc
    ).isoformat()
def numeric(
    value: Any,
    default: float = 0.0,
) -> float:
    """
    Convert a scalar value to a finite float.
    Invalid, missing, NaN and infinite values return the supplied
    finite fallback.
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
            result = float(value)
        elif isinstance(
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
        elif isinstance(
            value,
            bytes,
        ):
            text = value.decode().strip()
            if not text:
                raise ValueError(
                    "Empty numeric string"
                )
            result = float(
                text.replace(
                    ",",
                    "",
                )
            )
        elif isinstance(
            value,
            str,
        ):
            text = value.strip()
            if not text:
                raise ValueError(
                    "Empty numeric string"
                )
            result = float(
                text.replace(
                    ",",
                    "",
                )
            )
        else:
            result = float(value)
        if math.isfinite(result):
            return result
    except (
        TypeError,
        ValueError,
        ArithmeticError,
        OverflowError,
        UnicodeError,
    ):
        pass
    try:
        fallback = float(default)
        if math.isfinite(fallback):
            return fallback
    except (
        TypeError,
        ValueError,
        ArithmeticError,
        OverflowError,
    ):
        pass
    return 0.0
def optional_numeric(
    value: Any,
) -> Optional[float]:
    """
    Convert a scalar value to a finite float.
    Unlike numeric(), invalid or missing values remain None.
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
            bytes,
        ):
            text = value.decode().strip()
            if not text:
                return None
            result = float(
                text.replace(
                    ",",
                    "",
                )
            )
        elif isinstance(
            value,
            str,
        ):
            text = value.strip()
            if not text:
                return None
            result = float(
                text.replace(
                    ",",
                    "",
                )
            )
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
        UnicodeError,
    ):
        return None
def clamp(
    value: Any,
    minimum: float,
    maximum: float,
) -> float:
    """
    Clamp a numeric value to an inclusive range.
    If the supplied bounds are reversed, they are normalized first.
    """
    minimum = numeric(
        minimum,
        default=0.0,
    )
    maximum = numeric(
        maximum,
        default=0.0,
    )
    if minimum > maximum:
        minimum, maximum = maximum, minimum
    value = numeric(
        value,
        default=minimum,
    )
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
    """Safely divide two numeric values without zero-division errors."""
    denominator_value = optional_numeric(
        denominator
    )
    if (
        denominator_value is None
        or denominator_value == 0
    ):
        return numeric(
            default,
            default=0.0,
        )
    numerator_value = optional_numeric(
        numerator
    )
    if numerator_value is None:
        return numeric(
            default,
            default=0.0,
        )
    return numeric(
        numerator_value / denominator_value,
        default=default,
    )
def percentage_change(
    current: Any,
    previous: Any,
) -> Optional[float]:
    """Calculate percentage change from previous to current."""
    current_value = optional_numeric(
        current
    )
    previous_value = optional_numeric(
        previous
    )
    if (
        current_value is None
        or previous_value is None
    ):
        return None
    if previous_value == 0:
        return None
    result = (
        (
            current_value - previous_value
        )
        / abs(previous_value)
    ) * 100.0
    if not math.isfinite(result):
        return None
    return result
def clean_text(
    value: Any,
    default: str = "",
    max_length: int = 2000,
) -> str:
    """Normalize text and enforce a maximum length."""
    if value is None:
        return default
    try:
        max_length = max(
            0,
            int(max_length),
        )
    except (
        TypeError,
        ValueError,
    ):
        max_length = 2000
    text = str(value).strip()
    if not text:
        return default
    return text[:max_length]
def normalize_symbol(
    symbol: Any,
) -> str:
    """Normalize a token symbol to uppercase alphanumeric characters."""
    if symbol is None:
        return ""
    try:
        normalized = str(
            symbol
        ).strip().upper()
    except Exception:
        return ""
    normalized = re.sub(
        r"[^A-Z0-9]",
        "",
        normalized,
    )
    return normalized[
        :MAX_TOKEN_SYMBOL_LENGTH
    ]
def is_valid_symbol(
    symbol: Any,
) -> bool:
    """Return True when a normalized symbol matches the allowed format."""
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
    """
    Recursively convert values into JSON-safe primitives.
    NaN and Infinity become None.
    Decimal values become finite floats.
    Date/time values become ISO strings.
    """
    if value is None:
        return None
    if isinstance(
        value,
        bool,
    ):
        return value
    if isinstance(
        value,
        int,
    ):
        return value
    if isinstance(
        value,
        str,
    ):
        return value
    if isinstance(
        value,
        float,
    ):
        return (
            value
            if math.isfinite(value)
            else None
        )
    if isinstance(
        value,
        Decimal,
    ):
        try:
            number = float(value)
            return (
                number
                if math.isfinite(number)
                else None
            )
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
            items = list(
                value.items()
            )
        except Exception:
            return None
        safe_dict = {}
        for key, item in items:
            try:
                safe_key = str(key)
            except Exception:
                continue
            safe_dict[safe_key] = json_safe(
                item
            )
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
    """Return a consistent unavailable-market payload."""
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
        "unavailable_reason": (
            "CoinGecko did not return a usable market snapshot."
        ),
        "timestamp": utc_now_iso(),
        "available": False,
    }
def first_defined(*values):
    """
    Return the first value that is not None.
    False, zero and empty strings are intentionally preserved.
    """
    for value in values:
        if value is not None:
            return value
    return None
def format_number(
    value,
    decimals=2,
):
    """Safely format a numeric value for human-readable output."""
    if value is None:
        return "N/A"
    try:
        decimals = max(
            0,
            int(decimals),
        )
    except (
        TypeError,
        ValueError,
    ):
        decimals = 2
    try:
        number = float(value)
        if not math.isfinite(number):
            return "N/A"
        return f"{number:,.{decimals}f}"
    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        return "N/A"
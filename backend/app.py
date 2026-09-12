# ============================================================
# CryptoRisk AI — Backend v3

# Architecture:
#   Market Data
#       ↓
#   Normalization
#       ↓
#   Quantitative Engine
#       ↓
#   Risk Engine
#       ↓
#   Security / Stress Testing
#       ↓
#   Evidence Pack
#       ↓
#   Gemini AI Interpretation
#       ↓
#   Structured Report
#       ↓
#   PostgreSQL Persistence
#
# ============================================================
import jwt as pyjwt
import atexit
import json
import logging
import math
import os
import re
import traceback
import time
import uuid
from math import ceil

from concurrent.futures import (
    ThreadPoolExecutor,
    TimeoutError as FuturesTimeoutError,
)

from datetime import date, datetime, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
from functools import wraps
from statistics import mean
from threading import Lock
from typing import Any, Optional
from urllib.parse import quote

from dotenv import load_dotenv
from flask_cors import CORS

import psycopg2
import requests

from werkzeug.middleware.proxy_fix import ProxyFix

from authlib.integrations.flask_client import OAuth

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
    g,
)

from flask_bcrypt import Bcrypt

from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    get_jwt_identity,
    jwt_required,
)

from google import genai

try:
    from google.genai import types as genai_types
except ImportError:
    genai_types = None


# ============================================================
# LOAD ENVIRONMENT VARIABLES
# ============================================================

load_dotenv()


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("cryptorisk-ai")


# ============================================================
# APPLICATION CONFIGURATION
# ============================================================
# All configuration values are loaded from environment variables
# with sensible defaults for development. Production deployments
# MUST set all sensitive values via .env or deployment platform.
#
# Required for production:
#   - SECRET_KEY: Flask session encryption key
#   - JWT_SECRET_KEY: JWT token signing key
#   - DATABASE_URL: PostgreSQL connection string
#   - GEMINI_API_KEY: Google Gemini AI API key
#   - GOOGLE_CLIENT_ID/SECRET: OAuth 2.0 credentials
#   - FRONTEND_URL: Allowed CORS origin
# ============================================================

# Application metadata
APP_NAME = "CryptoRisk AI"
APP_VERSION = "3.0"
REPORT_SCHEMA_VERSION = "3.0"

# Environment detection (production/development)
FLASK_ENV = os.getenv(
    "FLASK_ENV",
    "production",
).strip().lower()

IS_PRODUCTION = FLASK_ENV == "production"

# Flask secret key for session encryption
# WARNING: Must be set to a secure random value in production
SECRET_KEY = os.getenv(
    "SECRET_KEY"
) or os.getenv(
    "FLASK_SECRET_KEY",
    "dev-secret-change-me",
)

# PostgreSQL database connection string
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "",
).strip()

# Google Gemini AI API configuration
GEMINI_API_KEY = os.getenv(
    "GEMINI_API_KEY",
    "",
).strip()

# Google OAuth 2.0 credentials for authentication
GOOGLE_CLIENT_ID = os.getenv(
    "GOOGLE_CLIENT_ID",
    "",
).strip()

GOOGLE_CLIENT_SECRET = os.getenv(
    "GOOGLE_CLIENT_SECRET",
    "",
).strip()

# JWT signing key (falls back to SECRET_KEY if not set)
JWT_SECRET_KEY = os.getenv(
    "JWT_SECRET_KEY",
    SECRET_KEY,
).strip()

# Frontend URL for CORS configuration
FRONTEND_URL = os.getenv(
    "FRONTEND_URL",
    "",
).strip().rstrip("/")


# ============================================================
# GEMINI CONFIG
# ============================================================

GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-2.5-flash",
).strip()

GEMINI_TIMEOUT_MS = min(
    15000,
    max(
        5000,
        int(
            os.getenv(
                "GEMINI_TIMEOUT_MS",
                "12000",
            )
        ),
    ),
)

GEMINI_TIMEOUT_SECONDS = (
    GEMINI_TIMEOUT_MS / 1000.0
)

GEMINI_MAX_RETRIES = min(
    2,
    max(
        0,
        int(
            os.getenv(
                "GEMINI_MAX_RETRIES",
                "0",
            )
        ),
    ),
)

# ============================================================
# NETWORK CONFIG
# ============================================================

MARKET_TIMEOUT = max(3, int(os.getenv("MARKET_TIMEOUT", "10")))
HISTORY_CACHE_TTL = max(15, int(os.getenv("HISTORY_CACHE_TTL", "60")))
MARKET_CACHE_TTL = max(5, int(os.getenv("MARKET_CACHE_TTL", "60")))
MARKET_CAP_CACHE_TTL = max(
    600,
    int(os.getenv("MARKET_CAP_CACHE_TTL", "900")),
)
# How long a resolved CoinGecko coin id (from TOKEN_MAP or a
# dynamic /search lookup) stays cached. Negative ("no match")
# results are cached for a shorter window so recently-listed
# tokens can be picked up without a restart.
COIN_RESOLUTION_CACHE_TTL = max(
    300,
    int(os.getenv("COIN_RESOLUTION_CACHE_TTL", "86400")),
)
COIN_RESOLUTION_MISS_TTL = max(
    60,
    int(os.getenv("COIN_RESOLUTION_MISS_TTL", "600")),
)

# ============================================================
# JOB CONFIG
# ============================================================

JOB_TTL_SECONDS = max(300, int(os.getenv("JOB_TTL_SECONDS", "1800")))
ANALYSIS_JOB_TIMEOUT_SECONDS = max(
    60,
    int(os.getenv("ANALYSIS_JOB_TIMEOUT_SECONDS", "150")),
)
MAX_HISTORY_ROWS = 50
MAX_TOKEN_SYMBOL_LENGTH = 15  # Frontend regex enforces {2,15}; backend normalize_symbol truncates to this length
SUPPORTED_HISTORY_DAYS = 30

# ============================================================
# FLASK APP
# ============================================================

app = Flask(
    __name__,
    static_folder="static",
    template_folder="templates",
)

app.config["SECRET_KEY"] = SECRET_KEY
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1,
    x_port=1,
    x_prefix=1,
)

# ============================================================
# JWT AND SESSION CONFIGURATION
# ============================================================

app.config["JWT_SECRET_KEY"] = JWT_SECRET_KEY
app.config["JWT_TOKEN_LOCATION"] = ["headers"]
app.config["JWT_HEADER_NAME"] = "Authorization"
app.config["JWT_HEADER_TYPE"] = "Bearer"
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = IS_PRODUCTION

jwt = JWTManager(app)
bcrypt = Bcrypt(app)

# ============================================================
# CORS
# ============================================================

cors_origins = [FRONTEND_URL] if FRONTEND_URL else ["*"]
CORS(
    app,
    resources={
        r"/api/*": {
            "origins": cors_origins,
            "supports_credentials": cors_origins != ["*"],
        }
    },
)

# ============================================================
# GEMINI CLIENT
# ============================================================

gemini_client = None

if GEMINI_API_KEY:
    try:
        if genai_types is not None:
            try:
                gemini_client = genai.Client(
                    api_key=GEMINI_API_KEY,
                    http_options=genai_types.HttpOptions(
                        timeout=GEMINI_TIMEOUT_MS,
                    ),
                )
            except TypeError:
                gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        else:
            gemini_client = genai.Client(api_key=GEMINI_API_KEY)

        logger.info(
            "Gemini client initialized: %s",
            GEMINI_MODEL,
        )
    except Exception as exc:
        logger.exception(
            "Failed to initialize Gemini client: %s",
            exc,
        )
        gemini_client = None
else:
    logger.warning(
        "GEMINI_API_KEY is not configured. "
        "Deterministic fallback will be used."
    )


# ============================================================
# EXECUTORS
# ============================================================

# FIX: a duplicate GEMINI_EXECUTOR used to be created here AND
# again in Part 2 (with a configurable worker count). The first
# one was immediately orphaned (leaked, never shut down) since
# the name got overwritten. Removed — the real one is defined
# once, in Part 2, right before it's first used.

# Part 3 uses the analysis executor for persistent jobs.
#
# IMPORTANT:
# Part 3 references ANALYSIS_EXECUTOR_WORKERS,
# so this value must be defined separately.
#
# FIX (Bug 4): default raised from 2 to 5. With only 2 workers,
# concurrent users beyond 2 sat in "queued" status until a worker
# freed up. DB_POOL_MAX_CONN (default 20) comfortably covers
# ANALYSIS_EXECUTOR_WORKERS + GEMINI_EXECUTOR_WORKERS concurrent
# DB usage; a startup warning below guards against a mismatched
# deployment config.
ANALYSIS_EXECUTOR_WORKERS = max(
    1,
    int(
        os.getenv(
            "ANALYSIS_WORKERS",
            "5",
        )
    ),
)

ANALYSIS_EXECUTOR = ThreadPoolExecutor(
    max_workers=ANALYSIS_EXECUTOR_WORKERS,
    thread_name_prefix="analysis",
)


# ============================================================
# OAUTH
# ============================================================

oauth = OAuth(app)

if (
    GOOGLE_CLIENT_ID
    and GOOGLE_CLIENT_SECRET
):

    oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        access_token_url="https://oauth2.googleapis.com/token",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        api_base_url="https://www.googleapis.com/oauth2/v2/",
        client_kwargs={"scope": "openid email profile"},
        jwks_uri="https://www.googleapis.com/oauth2/v3/certs",
    )

else:

    logger.warning(
        "Google OAuth credentials are not configured."
    )


# ============================================================
# EXTERNAL API CONFIGURATION
# ============================================================
# Base URLs for third-party data providers.
# All API calls include timeout and error handling.
# ============================================================

# CoinGecko — Secondary market-data provider (market cap/history)
COINGECKO_API_URL = (
    "https://api.coingecko.com/api/v3"
)

# Binance public spot ticker; no API key is required.
BINANCE_API_URL = "https://api.binance.com/api/v3"
BINANCE_DATA_API_URL = "https://data-api.binance.vision/api/v3"

COINGECKO_API_KEY = (
    os.getenv(
        "COINGECKO_API_KEY",
        "",
    ).strip()
)

# Provider cooldown durations (seconds).
# 429 (rate-limit) gets the longest cooldown so the backend
# backs off and lets the rate limit window reset before retrying.
PROVIDER_COOLDOWN_429 = max(
    10,
    int(
        os.getenv(
            "PROVIDER_COOLDOWN_429",
            "30",
        )
    ),
)

# 403 / 451 (auth / geo-block) cooldown — these are unlikely
# to resolve quickly, so skip the provider for a while.
PROVIDER_COOLDOWN_FORBIDDEN = max(
    10,
    int(
        os.getenv(
            "PROVIDER_COOLDOWN_FORBIDDEN",
            "60",
        )
    ),
)

# Generic / 5xx cooldown — short, providers may recover quickly.
PROVIDER_COOLDOWN_DEFAULT = max(
    5,
    int(
        os.getenv(
            "PROVIDER_COOLDOWN_DEFAULT",
            "15",
        )
    ),
)

# GoPlus — Token security and contract risk data
GOPLUS_API_URL = (
    "https://api.gopluslabs.io/api/v1/token_security"
)


# ============================================================
# TOKEN SYMBOL MAPPING
# ============================================================
# Maps user-input symbols to CoinGecko coin IDs.
# Used by fetch_coingecko_market() to resolve tickers.
# ============================================================

TOKEN_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "AVAX": "avalanche-2",
    "DOT": "polkadot",
    "MATIC": "matic-network",
    "POL": "matic-network",
    "LINK": "chainlink",
    "LTC": "litecoin",
    "BCH": "bitcoin-cash",
    "ATOM": "cosmos",
    "UNI": "uniswap",
    "XLM": "stellar",
    "TRX": "tron",
    "SHIB": "shiba-inu",
    "TON": "the-open-network",
    # ------------------------------------------------------------
    # FIX (Bug 5): expanded the allowlist with more common tickers.
    # Symbols not listed here are no longer a hard failure — they
    # are resolved dynamically via CoinGecko's /search endpoint
    # (see resolve_coin_id) and cached in _coin_resolution_cache.
    # ------------------------------------------------------------
    "USDT": "tether",
    "USDC": "usd-coin",
    "DAI": "dai",
    "XMR": "monero",
    "ETC": "ethereum-classic",
    "FIL": "filecoin",
    "APT": "aptos",
    "ARB": "arbitrum",
    "OP": "optimism",
    "NEAR": "near",
    "ICP": "internet-computer",
    "PEPE": "pepe",
    "ALGO": "algorand",
    "VET": "vechain",
    "FTM": "fantom",
    "SAND": "the-sandbox",
    "MANA": "decentraland",
    "AXS": "axie-infinity",
    "AAVE": "aave",
    "MKR": "maker",
    "GRT": "the-graph",
    "CRV": "curve-dao-token",
    "SUSHI": "sushi",
    "COMP": "compound-governance-token",
    "SNX": "havven",
    "BAT": "basic-attention-token",
    "ZEC": "zcash",
    "DASH": "dash",
    "EGLD": "elrond-erd-2",
    "FLOW": "flow",
    "HBAR": "hedera-hashgraph",
    "XDC": "xdce-crowd-sale",
    "KAVA": "kava",
    "CAKE": "pancakeswap-token",
    "LDO": "lido-dao",
    "STETH": "staked-ether",
}

SUPPORTED_ASSETS = frozenset(TOKEN_MAP)


# ============================================================
# Native blockchain assets (not ERC-20 tokens)
# Derived from TOKEN_MAP via an explicit allowlist. When adding
# a new native L1 to TOKEN_MAP, also add it here so it's excluded
# from GoPlus contract-security checks.
NATIVE_ASSETS = frozenset(
    sym
    for sym in (
        "BTC",
        "ETH",
        "SOL",
        "BNB",
        "XRP",
        "ADA",
        "DOGE",
        "AVAX",
        "DOT",
        "LTC",
        "BCH",
        "ATOM",
        "XLM",
        "TRX",
        "TON",
    )
    if sym in TOKEN_MAP
)


# ============================================================
# IN-MEMORY CACHE
# ============================================================
# Thread-safe caches for market data, price history, and
# coin resolution. TTL values configured via environment.
# ============================================================

_market_cache = {}
_market_cap_cache = {}
_history_cache = {}
_coin_resolution_cache = {}

_cache_lock = Lock()


# ============================================================
# PROVIDER COOLDOWN + IN-FLIGHT DEDUPLICATION
# ============================================================
# When a provider returns 429/403/451/5xx it is placed on a
# cooldown so subsequent requests skip it immediately and fall
# through to the next provider.
#
# Per-symbol fetch locks prevent concurrent requests for the
# same symbol from triggering duplicate upstream calls.
# ============================================================

_provider_cooldown = {}
_provider_cooldown_lock = Lock()
_provider_failure_counts = {}

_symbol_fetch_locks = {}
_symbol_fetch_locks_guard = Lock()


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
            300,
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


# ============================================================
# ANALYSIS PIPELINE STAGES
# ============================================================
# Progress percentages for each stage of the analysis pipeline.
# Used by the frontend progress bar during report generation.
# ============================================================

ANALYSIS_STAGES = {
    "market": 12,      # Fetch market data
    "history": 25,     # Fetch price history
    "quant": 40,       # Run quantitative engine
    "risk": 55,        # Build risk profile
    "security": 65,    # Security scan
    "stress": 74,      # Stress test scenarios
    "evidence": 82,    # Compile evidence pack
    "ai": 92,          # Gemini AI interpretation
    "save": 97,        # Persist to database
    "complete": 100,   # Report ready
}


# ============================================================
# GENERIC JOB CALLBACK
# ============================================================

def analysis_progress_callback(
    job_id: str,
    stage: str,
    overall_percent: int,
    title: str,
    message: str,
) -> None:
    """
    Compatibility helper.

    Part 3 owns persistent job storage.
    This function intentionally attempts to update the
    persistent job manager when available.
    """

    try:

        update_analysis_job(
            job_id,
            progress=int(
                clamp(
                    overall_percent,
                    0,
                    100,
                )
            ),
            stage=stage,
            stage_title=title,
            message=message,
            status="running",
        )

    except NameError:

        # Part 3 has not yet defined its DB-backed helper.
        logger.debug(
            "Persistent job updater unavailable during callback."
        )

    except Exception as exc:

        # Log at warning level with full traceback for operational
        # visibility. If DB connection pool is exhausted or other
        # persistent failures occur, the job could appear frozen
        # in the UI — the traceback helps diagnose this quickly.
        logger.warning(
            "Could not update analysis progress for job %s: %s",
            job_id,
            exc,
            exc_info=True,
        )

        # Best-effort fallback: surface the failure state on the
        # job record itself, so a frozen-looking job shows why.
        try:
            update_analysis_job(
                job_id,
                status="running",
                message=f"Progress update failed: {exc}",
            )
        except Exception:
            # Nested attempt is best-effort only; never let it raise.
            pass


def set_analysis_stage(
    job_id: str,
    stage: str,
    title: str,
    message: str,
) -> None:
    """
    Convenience wrapper for persistent progress updates.
    """

    percent = ANALYSIS_STAGES.get(
        stage,
        0,
    )

    analysis_progress_callback(
        job_id,
        stage,
        percent,
        title,
        message,
    )


# ============================================================
# TIME HELPERS
# ============================================================

def utc_now_iso() -> str:

    return datetime.now(
        timezone.utc
    ).isoformat()


# ============================================================
# NUMERIC HELPERS
# ============================================================

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


def mean_or_zero(
    values: list,
) -> float:

    cleaned = [
        numeric(value)
        for value in values
        if optional_numeric(value)
        is not None
    ]

    if not cleaned:
        return 0.0

    return numeric(
        mean(cleaned),
        default=0.0,
    )


# ============================================================
# STATISTICAL HELPERS
# ============================================================

def standard_deviation(
    values: list,
    sample: bool = False,
) -> float:
    """
    Standard deviation of a value list.

    sample=False (default): population std dev (divide by N).
    sample=True: sample std dev (divide by N-1) — the correct
    unbiased estimator for return series, which typically have
    very few observations (e.g. 7 daily returns from 8 candles).
    Population std dev understates volatility by ~sqrt((N-1)/N),
    which matters at these small sample sizes (~6.5% low).
    """

    if not isinstance(
        values,
        list,
    ):
        return 0.0

    cleaned = [
        numeric(value)
        for value in values
        if optional_numeric(value)
        is not None
    ]

    min_points = 3 if sample else 2

    if len(cleaned) < min_points:
        return 0.0

    avg = mean(cleaned)

    divisor = (
        (len(cleaned) - 1)
        if sample
        else len(cleaned)
    )

    variance_value = (
        sum(
            (
                value - avg
            ) ** 2
            for value in cleaned
        )
        / divisor
    )

    return math.sqrt(
        max(
            variance_value,
            0.0,
        )
    )


def covariance(
    values_a: list,
    values_b: list,
) -> float:

    if (
        not isinstance(
            values_a,
            list,
        )
        or not isinstance(
            values_b,
            list,
        )
    ):
        return 0.0

    pairs = [
        (
            numeric(a),
            numeric(b),
        )
        for a, b in zip(
            values_a,
            values_b,
        )
        if optional_numeric(a)
        is not None
        and optional_numeric(b)
        is not None
    ]

    if len(pairs) < 2:
        return 0.0

    a_values = [
        pair[0]
        for pair in pairs
    ]

    b_values = [
        pair[1]
        for pair in pairs
    ]

    mean_a = mean(a_values)
    mean_b = mean(b_values)

    return mean(
        [
            (
                (a - mean_a)
                * (b - mean_b)
            )
            for a, b in pairs
        ]
    )


def variance(
    values: list,
) -> float:

    if not isinstance(
        values,
        list,
    ):
        return 0.0

    cleaned = [
        numeric(value)
        for value in values
        if optional_numeric(value)
        is not None
    ]

    if len(cleaned) < 2:
        return 0.0

    avg = mean(cleaned)

    return mean(
        [
            (
                value - avg
            ) ** 2
            for value in cleaned
        ]
    )


def calculate_returns(
    prices: list,
) -> list:

    if not isinstance(
        prices,
        list,
    ):
        return []

    cleaned = [
        optional_numeric(price)
        for price in prices
    ]

    cleaned = [
        price
        for price in cleaned
        if (
            price is not None
            and price > 0
        )
    ]

    if len(cleaned) < 2:
        return []

    returns = []

    for previous, current in zip(
        cleaned,
        cleaned[1:],
    ):

        if previous <= 0:
            continue

        returns.append(
            (
                current - previous
            )
            / previous
        )

    return returns


def max_drawdown(
    prices: list,
) -> float:
    """
    Calculate maximum drawdown from a price series.

    Methodology:
        Track running peak; compute drawdown at each point as
        (price - peak) / peak * 100. Return the absolute value
        of the largest observed decline.

    This measures the worst peak-to-tail decline an investor
    would have experienced holding the asset over the period.

    Returns:
        float: Maximum drawdown as a positive percentage
    """

    cleaned = [
        optional_numeric(price)
        for price in prices
    ]

    cleaned = [
        price
        for price in cleaned
        if (
            price is not None
            and price > 0
        )
    ]

    if not cleaned:
        return 0.0

    peak = cleaned[0]
    maximum_drawdown = 0.0

    for price in cleaned:

        if price > peak:
            peak = price

        if peak <= 0:
            continue

        # Drawdown from peak as percentage (negative value)
        drawdown = (
            (
                price - peak
            )
            / peak
        ) * 100.0

        maximum_drawdown = min(
            maximum_drawdown,
            drawdown,
        )

    return abs(
        numeric(
            maximum_drawdown
        )
    )


# ============================================================
# CLASSIFICATION HELPERS
# ============================================================

def classify_risk(
    score: Any,
) -> str:

    score = clamp(
        score,
        0,
        100,
    )

    if score >= 80:
        return "Critical"

    if score >= 65:
        return "High"

    if score >= 40:
        return "Moderate"

    if score >= 20:
        return "Low"

    return "Very Low"


def classify_change(
    value: Any,
) -> str:

    value = optional_numeric(
        value
    )

    if value is None:
        return "Unknown"

    if value >= 10:
        return "Strong Increase"

    if value >= 3:
        return "Increase"

    if value > -3:
        return "Stable"

    if value > -10:
        return "Decrease"

    return "Strong Decrease"


# ============================================================
# TEXT HELPERS
# ============================================================

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


def clean_string_list(
    values: Any,
    max_items: int = 10,
    max_item_length: int = 500,
) -> list:

    if not isinstance(
        values,
        list,
    ):
        return []

    result = []

    for value in values:

        text = clean_text(
            value,
            default="",
            max_length=max_item_length,
        )

        if not text:
            continue

        result.append(text)

        if len(result) >= max_items:
            break

    return result


# ============================================================
# SYMBOL HELPERS
# ============================================================

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


# ============================================================
# JSON SAFETY
# ============================================================

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


# ============================================================
# MARKET DATA
# ============================================================

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
        "unavailable_reason": "No market data provider returned a usable snapshot.",
        "timestamp": utc_now_iso(),
        "available": False,
    }


class MarketDataUnavailableError(RuntimeError):
    """Raised when CoinGecko cannot provide a usable market snapshot."""


class UnsupportedAssetError(ValueError):
    """Raised when a ticker has no verified CoinGecko asset ID."""


# ============================================================
# HTTP HELPER
# ============================================================

def http_get(
    url: str,
    params: Optional[dict] = None,
    timeout: Optional[int] = None,
) -> Optional[requests.Response]:

    try:

        headers = {
            "User-Agent": "CryptoRisk-AI/3.0",
        }

        if COINGECKO_API_KEY and "api.coingecko.com" in url:
            headers["x-cg-demo-api-key"] = COINGECKO_API_KEY

        response = requests.get(
            url,
            params=params,
            timeout=(
                timeout
                or MARKET_TIMEOUT
            ),
            headers=headers,
        )

        response.raise_for_status()

        return response

    except requests.RequestException as exc:

        logger.warning(
            "HTTP GET failed: %s | %s",
            url,
            exc,
        )

        return None

    except Exception as exc:

        logger.exception(
            "Unexpected HTTP error: %s",
            exc,
        )

        return None


def _http_get_market(
    url: str,
    params: Optional[dict] = None,
    timeout: Optional[int] = None,
):
    """
    HTTP GET for market data providers.

    Unlike http_get(), this returns the HTTP status code and a
    human-readable error reason alongside the response so callers
    can apply provider cooldown/backoff logic.

    Returns:
        tuple: (response, status_code, error_reason)
            response: requests.Response or None
            status_code: int HTTP status code or None
            error_reason: str failure reason or None on success
    """
    try:
        headers = {
            "User-Agent": "CryptoRisk-AI/3.0",
        }

        if COINGECKO_API_KEY and "api.coingecko.com" in url:
            headers["x-cg-demo-api-key"] = COINGECKO_API_KEY

        response = requests.get(
            url,
            params=params,
            timeout=(
                timeout
                or MARKET_TIMEOUT
            ),
            headers=headers,
        )

        if response.ok:
            return response, response.status_code, None

        retry_after = response.headers.get("Retry-After")

        if retry_after:
            try:
                retry_after = str(max(0, float(retry_after)))
            except (TypeError, ValueError):
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)
                    retry_after = str(
                        max(0, (retry_at - datetime.now(timezone.utc)).total_seconds())
                    )
                except (TypeError, ValueError, OverflowError):
                    retry_after = None
        retry_suffix = (
            f"; retry_after={retry_after}"
            if retry_after
            else ""
        )

        # Return the response and status so callers can apply backoff.
        return response, response.status_code, (
            f"HTTP {response.status_code}{retry_suffix}"
        )

    except requests.exceptions.Timeout:
        return None, None, "timeout"

    except requests.exceptions.ConnectionError:
        return None, None, "connection_error"

    except requests.RequestException as exc:
        return None, None, str(exc)

    except Exception as exc:
        return None, None, str(exc)


# ============================================================
# COINGECKO RESOLUTION
# ============================================================

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


# ============================================================
# COINGECKO MARKET
# ============================================================
# MARKET DATA INGESTION — CoinGecko Provider
# ============================================================
# Fetches live market data from CoinGecko /coins/markets endpoint.
# Returns: price, 24h_volume, market_cap, high_24h, low_24h,
#          price_change_7d_pct, and other market structure data.
#
# Rate-limited with an explicit error when CoinGecko fails.
# ============================================================

def fetch_coingecko_market(
    symbol: str,
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

    # Skip if currently on cooldown
    if _provider_is_cooling("CoinGecko"):
        market = empty_market_data(symbol)
        market["unavailable_reason"] = "CoinGecko is temporarily cooling down after a provider failure."
        return market

    coin_id = resolve_coin_id(symbol)

    if not coin_id:
        market = empty_market_data(symbol)
        market["unavailable_reason"] = f"CoinGecko could not resolve symbol {symbol}."
        return market

    logger.info("[MARKET] %s trying CoinGecko", symbol)

    # IMPORTANT: The /simple/price endpoint does NOT return
    # high_24h / low_24h / 7d change. We use /coins/markets
    # which returns all of those in a single call so the
    # dashboard snapshot cards always populate.
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

    if response is None:
        _mark_provider_failure(
            "CoinGecko",
            status_code,
            error_reason or "no_response",
        )
        market = empty_market_data(symbol)
        market["unavailable_reason"] = (
            f"CoinGecko request failed: {error_reason or 'no response'}."
        )
        return market

    if status_code is not None and status_code >= 400:
        _mark_provider_failure(
            "CoinGecko",
            status_code,
            error_reason or f"HTTP {status_code}",
        )
        market = empty_market_data(symbol)
        market["unavailable_reason"] = (
            f"CoinGecko returned {error_reason or f'HTTP {status_code}'}."
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


# ============================================================
# BINANCE LIVE MARKET PRICE
# ============================================================

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
        return value
    except Exception as exc:
        field_errors[key] = f"{source} {key} parsing failed: {exc}."
        logger.exception("[MARKET] %s field %s failed", source, key)
        return None

def get_binance_price(
    symbol: str,
) -> dict:
    """Fetch the Binance 24-hour USDT ticker used by live market reports."""

    symbol = normalize_symbol(symbol)

    if not symbol:
        return empty_market_data(symbol)

    pair = f"{symbol}USDT"

    errors = []

    for base_url in (
        BINANCE_API_URL,
        BINANCE_DATA_API_URL,
    ):
        try:
            response, status_code, error_reason = _http_get_market(
                f"{base_url}/ticker/24hr",
                params={"symbol": pair},
                timeout=MARKET_TIMEOUT,
            )

            if response is None:
                errors.append(error_reason or "no response")
                continue

            if status_code == 404:
                errors.append(f"HTTP 404 from {base_url}")
                continue

            if status_code is not None and status_code >= 400:
                errors.append(error_reason or f"HTTP {status_code}")
                continue

            payload = response.json()
            if not isinstance(payload, dict):
                errors.append("response was not an object")
                continue

            price_errors = {}
            price = _read_market_number(
                payload,
                "lastPrice",
                "Binance",
                price_errors,
            )

            if price is None:
                errors.append("no usable price")
                continue

            # Track field errors separately — only include non-empty
            # error dicts so the data quality module can properly
            # surface which fields had issues.
            field_errors = {}
            market = {
                "symbol": symbol,
                "price": price,
                "price_change_24h_pct": _read_market_number(
                    payload, "priceChangePercent", "Binance", field_errors
                ),
                "price_change_7d_pct": None,
                "volume_24h": _read_market_number(
                    payload, "quoteVolume", "Binance", field_errors
                ),
                "market_cap": None,
                "high_24h": _read_market_number(
                    payload, "highPrice", "Binance", field_errors
                ),
                "low_24h": _read_market_number(
                    payload, "lowPrice", "Binance", field_errors
                ),
                "source": "Binance",
                "timestamp": utc_now_iso(),
                "source_timestamps": {
                    "Binance": utc_now_iso(),
                },
                "available": True,
                # Only include field_errors if there are actual errors
                "field_errors": field_errors if field_errors else {},
            }

            return json_safe(market)

        except (ValueError, TypeError, AttributeError, KeyError) as exc:
            errors.append(f"response parsing failed: {exc}")
        except Exception as exc:
            logger.exception(
                "Binance price lookup failed for %s via %s: %s",
                symbol,
                base_url,
                exc,
            )
            errors.append(str(exc))

    market = empty_market_data(symbol)
    market["unavailable_reason"] = (
        f"Binance endpoints unavailable for {pair}: {'; '.join(errors)}."
    )
    logger.warning("[MARKET] %s Binance unavailable: %s", symbol, market["unavailable_reason"])
    return market



# ============================================================
# LEGACY MARKET HELPERS
# ============================================================

def fetch_binance_market(
    symbol: str,
) -> dict:
    """
    Compatibility wrapper for the live Binance ticker.

    Delegates to get_binance_price() which handles normalization,
    provider cooldown, and error handling. The legacy implementation
    has been removed to avoid dead code.
    """

    return get_binance_price(symbol)


# ============================================================
# UNIFIED MARKET FETCH
# ============================================================
# MARKET DATA ORCHESTRATOR — CoinGecko primary, Binance fallback
# ============================================================
# CoinGecko (with API key) returns the complete snapshot in one
# call: price, volume, market cap, high/low. When CoinGecko is
# rate-limited or cooling down, Binance (keyless, unlimited
# public ticker via data-api.binance.vision) supplies live
# price/volume, and market cap is back-filled from the CoinGecko
# cache (including stale values past the TTL).
# Cache: 60s TTL. Per-symbol lock prevents duplicate upstream calls.
# ============================================================

_MARKET_PROVIDERS = [
    fetch_coingecko_market,
    get_binance_price,
]


def fetch_market_data(
    symbol: str,
    force_refresh: bool = False,
) -> dict:
    """Unified market fetcher with multi-provider fallback + cache."""

    try:

        symbol = normalize_symbol(symbol)

        if not symbol:
            return empty_market_data(symbol)

        now = time.time()
        stale_cached = None

        # Check cache first
        if not force_refresh:
            try:
                with _cache_lock:
                    cached = _market_cache.get(symbol)

                if isinstance(cached, dict) and cached:
                    if cached.get("available"):
                        stale_cached = dict(cached)

                    cached_at = numeric(
                        cached.get("_cached_at", 0),
                        default=0,
                    )

                    if (
                        cached.get("available")
                        and (now - cached_at) < MARKET_CACHE_TTL
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
            if not force_refresh:
                try:
                    with _cache_lock:
                        cached = _market_cache.get(symbol)

                    if isinstance(cached, dict) and cached:
                        if cached.get("available"):
                            stale_cached = dict(cached)

                        cached_at = numeric(
                            cached.get("_cached_at", 0),
                            default=0,
                        )

                        if (
                            cached.get("available")
                            and (now - cached_at) < MARKET_CACHE_TTL
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

            logger.info("[MARKET] %s cache MISS — trying providers", symbol)

            market = empty_market_data(symbol)

            # =====================================================
            # PRIMARY: CoinGecko — returns the complete snapshot
            # (price, volume, market cap, high/low, 7d change) in a
            # single call. If CoinGecko is on cooldown we skip it
            # immediately and go to Binance so the dashboard never
            # waits for a predictable 429 failure.
            # =====================================================
            coingecko_primary_skipped = _provider_is_cooling("CoinGecko")

            if coingecko_primary_skipped:
                logger.info(
                    "[MARKET] %s CoinGecko primary skipped (cooling down); using Binance",
                    symbol,
                )
            else:
                try:
                    market = fetch_coingecko_market(symbol)

                    # CoinGecko's snapshot includes market cap for
                    # free. Cache it here so later Binance fallback
                    # paths never need a second CoinGecko call
                    # (reduces 429 exposure).
                    primary_cap = (
                        optional_numeric(market.get("market_cap"))
                        if isinstance(market, dict)
                        else None
                    )

                    if (
                        isinstance(market, dict)
                        and market.get("available")
                        and primary_cap is not None
                    ):
                        with _cache_lock:
                            _market_cap_cache[symbol] = {
                                "value": primary_cap,
                                "timestamp": market.get(
                                    "timestamp",
                                    utc_now_iso(),
                                ),
                                "cached_at": time.time(),
                            }

                except Exception as exc:
                    logger.exception(
                        "[MARKET] CoinGecko primary failed for %s: %s",
                        symbol,
                        exc,
                    )
                    market = empty_market_data(symbol)
                    market["unavailable_reason"] = (
                        f"CoinGecko primary request failed unexpectedly: {exc}."
                    )

            # =====================================================
            # FALLBACK: Binance — unlimited public ticker via the
            # data-api.binance.vision mirror. Binance does not
            # return market cap, so enrich from the CoinGecko
            # market-cap cache (serving stale values past the TTL
            # when CoinGecko is rate-limited).
            # =====================================================
            if not market.get("available"):
                try:
                    market = get_binance_price(symbol)
                except Exception as exc:
                    logger.exception(
                        "[MARKET] Binance fallback failed for %s: %s",
                        symbol,
                        exc,
                    )
                    market = empty_market_data(symbol)
                    market["unavailable_reason"] = (
                        f"Binance fallback failed unexpectedly: {exc}."
                    )

            # Binance does not provide circulating supply or market cap.
            # Enrich the live Binance ticker with CoinGecko market cap,
            # without allowing a CoinGecko failure to discard live fields.
            #
            # FIX (Bug 1 — double CoinGecko call): this path used to
            # call fetch_coingecko_market(symbol) again just to backfill
            # market cap, so a single /api/analyze request could burn
            # TWO CoinGecko quota units (primary call + backfill) and
            # trigger the 429 cooldown far too early. It now uses ONLY
            # the existing _market_cap_cache — fresh values within
            # MARKET_CAP_CACHE_TTL, stale values as a last resort. If
            # there is no cached value at all, market_cap stays None
            # and the missing signal is recorded; the next scheduled
            # successful CoinGecko primary call repopulates the cache.
            if market.get("available") and market.get("source") == "Binance":
                market_cap_entry = None

                with _cache_lock:
                    cached_market_cap = _market_cap_cache.get(symbol)

                if isinstance(cached_market_cap, dict):
                    cached_cap_at = numeric(
                        cached_market_cap.get("cached_at"),
                        default=0,
                    )
                    if now - cached_cap_at < MARKET_CAP_CACHE_TTL:
                        market_cap_entry = dict(cached_market_cap)

                # No fresh entry — fall back to ANY cached value (even
                # stale) rather than forcing a second live CoinGecko
                # call from inside the Binance fallback path.
                if market_cap_entry is None:
                    with _cache_lock:
                        stale_cap = _market_cap_cache.get(symbol)

                    if (
                        isinstance(stale_cap, dict)
                        and stale_cap.get("value") is not None
                    ):
                        market_cap_entry = stale_cap
                        market["market_cap_stale"] = True

                if market_cap_entry is None:
                    # Nothing cached at all: record the missing signal
                    # and leave market_cap as None. A dedicated
                    # background refresh (or the next scheduled
                    # successful CoinGecko primary call) will populate
                    # the cache instead.
                    market.setdefault("field_errors", {})[
                        "market_cap"
                    ] = (
                        "Market cap unavailable — no cached CoinGecko "
                        "snapshot; it will be backfilled on the next "
                        "scheduled CoinGecko refresh."
                    )

                if market_cap_entry is not None:
                    market["market_cap"] = market_cap_entry["value"]
                    market["market_cap_source"] = "CoinGecko"
                    market.setdefault("source_timestamps", {})[
                        "CoinGecko"
                    ] = market_cap_entry.get(
                        "timestamp",
                        utc_now_iso(),
                    )

            if not market.get("available"):
                logger.warning(
                    "[MARKET] %s both providers unavailable: %s",
                    symbol,
                    market.get("unavailable_reason", "unknown"),
                )

                if stale_cached:
                    market = dict(stale_cached)
                    market["stale"] = True
                    market["stale_reason"] = (
                        "Live providers are temporarily rate-limited; "
                        "serving the last known snapshot."
                    )

            market.setdefault("source_timestamps", {})
            if market.get("source") and market.get("timestamp"):
                market["source_timestamps"].setdefault(
                    market["source"],
                    market["timestamp"],
                )

            # Enrich with 7d change from history if needed
            if not market.get("stale"):
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
) -> dict:
    """
    Populate ``price_change_7d_pct`` on a market payload when
    the provider itself did not supply it.

    Uses the already-cached (or freshly fetched) daily price
    series so the dashboard's "7D CHANGE" card never renders
    an empty dash while history data is available.
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

        history = fetch_price_history(
            symbol,
            days=8,
        )

        change_7d, actual_lookback = _price_series_change(
            history,
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


# ============================================================
# PRICE HISTORY — COINGECKO
# ============================================================

def fetch_coingecko_history(
    symbol: str,
    days: int = SUPPORTED_HISTORY_DAYS,
) -> list:

    symbol = normalize_symbol(
        symbol
    )

    coin_id = resolve_coin_id(
        symbol
    )

    if not coin_id:
        return []

    response = http_get(
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

    if response is None:
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

            price = optional_numeric(
                item[1]
            )

            if (
                price is None
                or price <= 0
            ):
                continue

            result.append(price)

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


# ============================================================
# PRICE HISTORY — BINANCE
# ============================================================

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


def fetch_binance_history(
    symbol: str,
    days: int = SUPPORTED_HISTORY_DAYS,
) -> list:

    symbol = normalize_symbol(
        symbol
    )

    pair = f"{symbol}USDT"

    limit = min(
        1000,
        max(
            2,
            _safe_lookback(
                days,
                default=SUPPORTED_HISTORY_DAYS,
            ) + 1,
        ),
    )

    # Try both Binance base URLs. api.binance.com may return 451
    # (geo-block) for klines from certain IPs, while data-api.binance.vision
    # remains accessible. This mirrors the fallback in get_binance_price().
    for base_url in (BINANCE_API_URL, BINANCE_DATA_API_URL):
        response = http_get(
            f"{base_url}/klines",
            params={
                "symbol": pair,
                "interval": "1d",
                "limit": limit,
            },
            timeout=MARKET_TIMEOUT,
        )

        if response is None:
            continue

        try:

            payload = response.json()

            if not isinstance(
                payload,
                list,
            ):
                continue

            result = []

            for candle in payload:

                if (
                    not isinstance(
                        candle,
                        list,
                    )
                    or len(candle) < 5
                ):
                    continue

                close_price = optional_numeric(
                    candle[4]
                )

                if (
                    close_price is None
                    or close_price <= 0
                ):
                    continue

                result.append(
                    close_price
                )

            if result:
                logger.info(
                    "[HISTORY] Binance (%s) symbol=%s returned %d candles",
                    base_url,
                    symbol,
                    len(result),
                )
                return result

        except (
            ValueError,
            TypeError,
            AttributeError,
            KeyError,
        ) as exc:

            logger.warning(
                "Binance history parsing failed for %s: %s",
                base_url,
                exc,
            )

    logger.warning(
        "[HISTORY] Binance symbol=%s returned 0 candles from all endpoints",
        symbol,
    )
    return []


# ============================================================
# PRICE HISTORY — YAHOO FINANCE FALLBACK
# ============================================================
# Free, keyless REST chart API. Returns daily OHLCV series for
# symbols quoted as {SYMBOL}-USD (e.g. BTC-USD, ETH-USD, SOL-USD).
# Supplies the closing-price series for the quantitative engine.
# ============================================================

def fetch_yahoo_history(
    symbol: str,
    days: int = SUPPORTED_HISTORY_DAYS,
) -> list:
    """
    Fetch historical daily closing prices from Yahoo Finance.

    Fallback for when CoinGecko and Binance history endpoints are
    unavailable (e.g. rate-limited or blocked on Render).

    Returns a chronologically ordered list of positive daily closing
    prices, or [] on any failure.
    """

    symbol = normalize_symbol(symbol)

    if not symbol:
        return []

    lookback = _safe_lookback(
        days,
        default=SUPPORTED_HISTORY_DAYS,
    )

    response = http_get(
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{quote(f'{symbol}-USD', safe='')}",
        params={
            "range": f"{lookback}d",
            "interval": "1d",
        },
        timeout=MARKET_TIMEOUT,
    )

    if response is None:
        logger.info(
            "Yahoo Finance history unavailable for %s",
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

        chart = payload.get(
            "chart",
            {},
        )

        if not isinstance(
            chart,
            dict,
        ):
            return []

        results = chart.get(
            "result",
            [],
        )

        if (
            not isinstance(
                results,
                list,
            )
            or not results
        ):
            return []

        result = results[0]

        if not isinstance(
            result,
            dict,
        ):
            return []

        indicators = result.get(
            "indicators",
            {},
        )

        if not isinstance(
            indicators,
            dict,
        ):
            return []

        quotes = indicators.get(
            "quote",
            [],
        )

        if (
            not isinstance(
                quotes,
                list,
            )
            or not quotes
        ):
            return []

        closes = quotes[0].get(
            "close",
            [],
        )

        if not isinstance(
            closes,
            list,
        ):
            return []

        prices = []

        for value in closes:

            price = optional_numeric(
                value
            )

            if (
                price is None
                or price <= 0
            ):
                continue

            prices.append(price)

        return prices

    except (
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
    ) as exc:

        logger.warning(
            "Yahoo Finance history parsing failed for %s: %s",
            symbol,
            exc,
        )

        return []

    except Exception as exc:

        logger.warning(
            "Yahoo Finance history failed unexpectedly for %s: %s",
            symbol,
            exc,
        )

        return []



            


# ============================================================
# UNIFIED PRICE HISTORY
# ============================================================

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

        try:

            with _cache_lock:

                cached = _history_cache.get(
                    cache_key
                )

            if isinstance(
                cached,
                dict,
            ) and cached:

                cached_at = numeric(
                    cached.get(
                        "_cached_at",
                        0,
                    ),
                    default=0,
                )

                if (
                    now - cached_at
                    < HISTORY_CACHE_TTL
                ):

                    cached_prices = cached.get(
                        "prices",
                        [],
                    )

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

        # Binance supplies the historical candles used by volatility,
        # beta, and 7d change without consuming CoinGecko quota.
        prices = fetch_binance_history(
            symbol,
            days,
        )

        history_source = "Binance"

        if (
            not isinstance(
                prices,
                list,
            )
            or len(prices) < 2
        ):
            prices = fetch_coingecko_history(
                symbol,
                days,
            )
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

        # Only cache NON-EMPTY results. Caching an empty list would
        # freeze "0 candles" for the full TTL when both providers
        # fail temporarily (e.g., 451/429), causing volatility, beta
        # and 7d change to stay missing even after providers recover.
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


# ============================================================
# QUANTITATIVE ENGINE
# ============================================================

def realized_volatility(
    prices: list,
) -> dict:
    """
    Compute realized volatility from a daily price series.

    Methodology:
        1. Calculate log returns: ln(current / previous)
        2. Compute SAMPLE standard deviation of returns
           (divide by N-1 — the unbiased estimator; with only
           ~7 daily returns the population estimator understates
           volatility by ~6.5%)
        3. Annualize: daily_std * sqrt(365) * 100
           (365 because crypto trades 24/7)

    Returns:
        dict: daily_volatility_pct, annualized_volatility_pct, observations
    """

    try:

        if not isinstance(
            prices,
            list,
        ):
            prices = []

        # Log returns: ln(current / previous).
        # More precise than simple returns for volatile series —
        # a +15% day contributes ln(1.15) ≈ 13.98%, not 15%,
        # so volatility is not overstated by asymmetric moves.
        cleaned = [
            optional_numeric(price)
            for price in prices
        ]

        cleaned = [
            price
            for price in cleaned
            if (
                price is not None
                and price > 0
            )
        ]

        returns = []

        for previous, current in zip(
            cleaned,
            cleaned[1:],
        ):

            if previous <= 0 or current <= 0:
                continue

            returns.append(
                math.log(
                    current / previous
                )
            )

        if len(returns) < 2:

            return json_safe({
                "daily_volatility_pct": None,
                "annualized_volatility_pct": None,
                "observations": len(
                    returns
                ),
            })

        daily_std = standard_deviation(
            returns,
            sample=True,
        )

        daily_std = numeric(
            daily_std,
            default=0.0,
        )

        # Annualization factor: sqrt(365) for daily data
        annualized = (
            daily_std
            * math.sqrt(365)
            * 100.0
        )

        return json_safe({
            "daily_volatility_pct": numeric(
                daily_std * 100.0
            ),
            "annualized_volatility_pct": numeric(
                annualized
            ),
            "observations": len(
                returns
            ),
        })

    except Exception as exc:

        logger.debug(
            "realized_volatility failed: %s",
            exc,
        )

        return {
            "daily_volatility_pct": None,
            "annualized_volatility_pct": None,
            "observations": 0,
        }


def calculate_beta(
    asset_prices: list,
    btc_prices: list,
) -> dict:
    """
    Calculate BTC beta (market sensitivity) for an asset.

    Methodology:
        Beta = Cov(asset_returns, btc_returns) / Var(btc_returns)

    A beta of 1.0 indicates the asset moves in line with BTC.
    Beta > 1.0 indicates amplified sensitivity to BTC movements.

    Returns:
        dict: beta coefficient and observation count
    """

    try:

        asset_returns = calculate_returns(
            asset_prices
        )

        btc_returns = calculate_returns(
            btc_prices
        )

        if not isinstance(
            asset_returns,
            list,
        ):
            asset_returns = []

        if not isinstance(
            btc_returns,
            list,
        ):
            btc_returns = []

        # Align series to the shorter length for valid comparison
        length = min(
            len(asset_returns),
            len(btc_returns),
        )

        if length < 2:

            return json_safe({
                "beta": None,
                "observations": int(length),
            })

        asset_returns = asset_returns[
            -length:
        ]

        btc_returns = btc_returns[
            -length:
        ]

        btc_variance = variance(
            btc_returns
        )

        btc_variance = optional_numeric(
            btc_variance
        )

        if (
            btc_variance is None
            or btc_variance <= 0
        ):

            return json_safe({
                "beta": None,
                "observations": int(length),
            })

        covariance_value = optional_numeric(
            covariance(
                asset_returns,
                btc_returns,
            )
        )

        if covariance_value is None:

            return json_safe({
                "beta": None,
                "observations": int(length),
            })

        # Beta = Cov(asset, BTC) / Var(BTC)
        beta = safe_divide(
            covariance_value,
            btc_variance,
            default=0.0,
        )

        beta_value = optional_numeric(beta)

        return json_safe({
            "beta": beta_value,
            "observations": int(length),
        })

    except Exception as exc:

        logger.debug(
            "calculate_beta failed: %s",
            exc,
        )

        return {
            "beta": None,
            "observations": 0,
        }


def calculate_liquidity_metrics(
    market: dict,
) -> dict:
    """
    Estimate liquidity risk from market structure.

    Methodology:
        Turnover ratio = (24h_volume / market_cap) * 100

    Higher turnover indicates deeper markets and lower exit risk.
    This ratio is used by score_liquidity() to generate a 0-100 risk score.

    Returns:
        dict: volume_24h, market_cap, turnover_pct
    """

    try:

        if not isinstance(
            market,
            dict,
        ):
            market = {}

        volume = optional_numeric(
            market.get(
                "volume_24h"
            )
        )

        market_cap = optional_numeric(
            market.get(
                "market_cap"
            )
        )

        turnover = None

        if (
            volume is not None
            and market_cap is not None
            and market_cap > 0
            and volume >= 0
        ):

            try:

                # Turnover as percentage: higher = more liquid
                turnover_value = (
                    volume
                    / market_cap
                ) * 100.0

                turnover = optional_numeric(
                    turnover_value
                )

            except (
                ZeroDivisionError,
                ArithmeticError,
                TypeError,
                ValueError,
                OverflowError,
            ) as exc:

                logger.debug(
                    "Liquidity turnover failed: %s",
                    exc,
                )

                turnover = None

        return json_safe({
            "volume_24h": volume,
            "market_cap": market_cap,
            "turnover_pct": turnover,
        })

    except Exception as exc:

        logger.debug(
            "calculate_liquidity_metrics failed: %s",
            exc,
        )

        return {
            "volume_24h": None,
            "market_cap": None,
            "turnover_pct": None,
        }


def calculate_quant_metrics(
    symbol: str,
    market: dict,
    history: list,
    btc_history: list,
) -> dict:

    try:

        symbol = normalize_symbol(
            symbol
        )

        if not isinstance(
            market,
            dict,
        ):
            market = {}

        if not isinstance(
            history,
            list,
        ):
            history = []

        if not isinstance(
            btc_history,
            list,
        ):
            btc_history = []

        volatility = realized_volatility(
            history
        )

        beta = calculate_beta(
            history,
            btc_history,
        )

        liquidity = calculate_liquidity_metrics(
            market
        )

        drawdown = max_drawdown(
            history
        )

        returns = calculate_returns(
            history
        )

        current_price = optional_numeric(
            market.get("price")
        )

        historical_price = (
            history[-1]
            if history
            else None
        )

        price_change_from_history = (
            percentage_change(
                current_price,
                historical_price,
            )
            if (
                current_price is not None
                and historical_price is not None
            )
            else None
        )

        return json_safe({
            "symbol": symbol,

            "volatility": volatility,

            "beta": beta,

            "liquidity": liquidity,

            "max_drawdown_pct": drawdown,

            "return_observations": len(
                returns
            ),

            "price_change_from_history_pct": (
                price_change_from_history
            ),

            "history_observations": len(
                history
            ),

            "btc_history_observations": len(
                btc_history
            ),
        })

    except Exception as exc:

        logger.warning(
            "quant metrics failed; returning safe defaults: %s",
            exc,
        )

        return json_safe({
            "symbol": normalize_symbol(
                symbol
            ),
            "volatility": {
                "daily_volatility_pct": None,
                "annualized_volatility_pct": None,
                "observations": 0,
            },
            "beta": {
                "beta": None,
                "observations": 0,
            },
            "liquidity": {
                "volume_24h": None,
                "market_cap": None,
                "turnover_pct": None,
            },
            "max_drawdown_pct": 0.0,
            "return_observations": 0,
            "price_change_from_history_pct": None,
            "history_observations": 0,
            "btc_history_observations": 0,
        })


# ============================================================
# SHUTDOWN
# ============================================================

def shutdown_executors() -> None:

    for executor_name in (
        "ANALYSIS_EXECUTOR",
        "GEMINI_EXECUTOR",
    ):

        executor = globals().get(
            executor_name
        )

        if executor is None:
            continue

        try:

            executor.shutdown(
                wait=False,
                cancel_futures=False,
            )

        except Exception as exc:

            logger.debug(
                "Executor shutdown failed: %s",
                exc,
            )


atexit.register(
    shutdown_executors
)


# ============================================================
# END OF PART 1
# ============================================================

# ============================================================
# CryptoRisk AI — Backend v3


# PART 2 / 3
#
# Continues after PART 1
#
# Contains:
#   Risk Engine
#   Security Analysis
#   Stress Testing
#   Risk Drivers
#   Evidence Pack
#   Gemini AI Analysis
#   AI Validation / Fallback
#   Structured Report
#   Analysis Pipeline
#
# ============================================================


# ============================================================
# GENERAL REPORT HELPERS
# ============================================================

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


def extract_volatility_value(
    quant,
    market=None,
):
    """
    Extract the scalar annualized volatility used by the
    risk engine.

    PART 1 stores volatility as a nested dictionary.
    """

    quant = quant or {}
    market = market or {}

    volatility = quant.get(
        "volatility"
    )

    if isinstance(volatility, dict):
        volatility = first_defined(
            volatility.get(
                "annualized_volatility_pct"
            ),
            volatility.get(
                "annualized_pct"
            ),
        )

    if volatility is None:
        volatility = market.get(
            "volatility"
        )

    return optional_numeric(
        volatility
    )


def extract_beta_value(
    quant,
):
    """
    Extract scalar BTC beta from the nested beta structure
    produced by PART 1.
    """

    quant = quant or {}

    beta = quant.get(
        "beta"
    )

    if isinstance(beta, dict):
        beta = beta.get(
            "beta"
        )

    return optional_numeric(
        beta
    )


# ============================================================
# RISK ENGINE
# ============================================================

# ============================================================
# RISK WEIGHTS — Composite Risk Factor Allocation
# ============================================================
# Volatility (35%) and Liquidity (30%) dominate the composite
# score as they are the most actionable risk vectors for
# cryptocurrency assets. Market sensitivity (20%) captures
# systematic BTC-correlated risk. Structural (15%) accounts
# for smart contract and security findings.
# ============================================================

RISK_WEIGHTS = {
    "volatility": 0.35,
    "liquidity": 0.30,
    "market_sensitivity": 0.20,
    "structural": 0.15,
}


def score_volatility(
    volatility,
):
    """
    Convert annualized volatility into a 0–100 risk score.

    Scoring bands (annualized volatility %):
        ≤20%  → 15 (Low risk)
        ≤40%  → 30 (Moderate)
        ≤60%  → 50 (Elevated)
        ≤80%  → 70 (High)
        ≤120% → 85 (Very high)
        >120% → 95 (Extreme)

    Higher volatility = higher risk.
    """

    if volatility is None:
        return None

    volatility = optional_numeric(
        volatility
    )

    if volatility is None:
        return None

    if volatility <= 20:
        return 15

    if volatility <= 40:
        return 30

    if volatility <= 60:
        return 50

    if volatility <= 80:
        return 70

    if volatility <= 120:
        return 85

    return 95


def score_liquidity(
    volume_24h,
    market_cap,
):
    """
    Estimate liquidity risk using 24h volume / market cap.

    Higher turnover generally means lower liquidity risk.
    """

    volume_24h = optional_numeric(
        volume_24h
    )

    market_cap = optional_numeric(
        market_cap
    )

    if volume_24h is None:
        return None

    if market_cap is None or market_cap <= 0:
        # Degraded but useful fallback when CoinGecko market cap is
        # unavailable: score observable 24h quote volume directly.
        if volume_24h >= 1_000_000_000:
            return 20
        if volume_24h >= 100_000_000:
            return 35
        if volume_24h >= 10_000_000:
            return 50
        if volume_24h >= 1_000_000:
            return 65
        if volume_24h >= 100_000:
            return 80
        return 90

    turnover = (
        volume_24h / market_cap
    )

    if turnover >= 0.50:
        return 10

    if turnover >= 0.25:
        return 20

    if turnover >= 0.10:
        return 35

    if turnover >= 0.05:
        return 50

    if turnover >= 0.02:
        return 65

    if turnover >= 0.01:
        return 80

    return 90


def score_beta(
    beta,
):
    """
    Convert BTC beta into market-sensitivity risk.
    """

    beta = optional_numeric(
        beta
    )

    if beta is None:
        return None

    if beta <= 0.50:
        return 20

    if beta <= 0.80:
        return 35

    if beta <= 1.00:
        return 50

    if beta <= 1.25:
        return 65

    if beta <= 1.50:
        return 80

    return 95


def score_structural_risk(
    security,
):
    """
    Convert contract/security findings into a 0–100 risk score.

    Missing security data is NOT automatically treated as
    dangerous.
    """

    if not security:
        return None

    if security.get("not_applicable"):
        return None

    status = str(
        security.get(
            "status",
            "",
        )
    ).strip().lower()

    if status in {
        "unavailable",
        "not available",
        "unknown",
    }:
        return None

    flags = security.get(
        "flags"
    ) or []

    if not isinstance(
        flags,
        list,
    ):
        flags = []

    score = 10

    for flag in flags:

        text = str(
            flag
        ).lower()

        if "honeypot" in text:
            score += 45

        elif "blacklist" in text:
            score += 30

        elif "ownership" in text:
            score += 25

        elif "tax" in text:
            score += 20

        elif "source" in text:
            score += 10

        else:
            score += 8

    return clamp(
        score,
        0,
        100,
    )


def risk_label(
    score,
):
    """
    Convert composite score into a human-readable label.
    """

    if score is None:
        return "Unavailable"

    score = optional_numeric(
        score
    )

    if score is None:
        return "Unavailable"

    if score >= 80:
        return "Critical"

    if score >= 65:
        return "High"

    if score >= 50:
        return "Elevated"

    if score >= 35:
        return "Moderate"

    return "Low"


def calculate_composite_risk(
    volatility_score,
    liquidity_score,
    sensitivity_score,
    structural_score,
):
    """
    Calculate weighted composite risk score (0-100).

    Methodology:
        Only available (non-None) signals participate in the
        weighted average. This ensures the composite score
        remains meaningful even when some data sources are
        unavailable.

        composite = Σ(score_i × weight_i) / Σ(weight_i)

    Confidence is derived from total weight participation:
        - Full participation (all 4 signals) → ~95% confidence
        - Partial participation → scaled proportionally
        - Minimum floor of 10% confidence

    Returns:
        tuple: (composite_score, confidence_percentage)
    """

    values = {
        "volatility": volatility_score,
        "liquidity": liquidity_score,
        "market_sensitivity": sensitivity_score,
        "structural": structural_score,
    }

    weighted_sum = 0.0
    weight_sum = 0.0

    for key, value in values.items():

        if value is None:
            continue

        # Clamp each score to valid 0-100 range
        value = clamp(
            numeric(
                value,
                default=0,
            ),
            0,
            100,
        )

        weight = RISK_WEIGHTS[
            key
        ]

        weighted_sum += (
            value * weight
        )

        weight_sum += weight

    if weight_sum <= 0:
        return None, 0

    # Weighted average of available signals
    composite = (
        weighted_sum / weight_sum
    )

    # Confidence scales with data availability (10% floor, 95% ceiling)
    confidence = clamp(
        10 + int(
            weight_sum * 90
        ),
        10,
        95,
    )

    return (
        round(
            composite,
            1,
        ),
        confidence,
    )


def build_risk_profile(
    market,
    quant,
    security=None,
):
    """
    Build the complete quantitative risk profile.

    Pipeline:
        1. Extract scalar values from nested quant structure
        2. Apply scoring functions to convert raw metrics → 0-100 scores
        3. Compute weighted composite score via calculate_composite_risk()
        4. Assemble pillar breakdown with labels, weights, and detail text

    Returns:
        dict: risk_profile with composite_score, label, confidence, pillars
    """

    market = market or {}
    quant = quant or {}

    volatility = extract_volatility_value(
        quant,
        market,
    )

    beta = extract_beta_value(
        quant
    )

    # NOTE: the market dict produced anywhere in this pipeline
    # (empty_market_data / fetch_coingecko_market)
    # only ever sets "volume_24h" and "market_cap" — there is no
    # "_usd"-suffixed variant. A dead first-lookup for "volume_24h_usd"
    # / "market_cap_usd" used to sit here; it always missed and fell
    # through to the correct key below, so behavior is unchanged —
    # this just removes the misleading dead branch.
    volume = optional_numeric(
        market.get(
            "volume_24h"
        )
    )

    market_cap = optional_numeric(
        market.get(
            "market_cap"
        )
    )

    volatility_score = score_volatility(
        volatility
    )

    liquidity_score = score_liquidity(
        volume,
        market_cap,
    )

    sensitivity_score = score_beta(
        beta
    )

    structural_score = score_structural_risk(
        security
    )

    if security and security.get("not_applicable"):
        structural_detail = "Not applicable."
    elif security and security.get("available"):
        structural_detail = security.get(
            "status",
            "Security assessment available.",
        )
    else:
        structural_detail = "Contract security assessment unavailable."

    composite, confidence = (
        calculate_composite_risk(
            volatility_score,
            liquidity_score,
            sensitivity_score,
            structural_score,
        )
    )

    pillars = {
        "volatility": {
            "score": volatility_score,
            "label": risk_label(
                volatility_score
            ),
            "weight": RISK_WEIGHTS[
                "volatility"
            ],
            "detail": (
                f"Annualized realized volatility: "
                f"{format_number(volatility, 1)}%"
                if volatility is not None
                else
                "Volatility data unavailable."
            ),
        },

        "liquidity": {
            "score": liquidity_score,
            "label": risk_label(
                liquidity_score
            ),
            "weight": RISK_WEIGHTS[
                "liquidity"
            ],
            "detail": (
                "Liquidity estimated from 24h "
                "volume-to-market-cap turnover."
                if liquidity_score is not None
                else
                (
                    "Liquidity signal unavailable: Binance volume was not returned."
                    if volume is None
                    else
                    "Liquidity estimated from 24h volume only; market cap is unavailable."
                )
            ),
        },

        "market_sensitivity": {
            "score": sensitivity_score,
            "label": risk_label(
                sensitivity_score
            ),
            "weight": RISK_WEIGHTS[
                "market_sensitivity"
            ],
            "detail": (
                f"BTC beta: "
                f"{format_number(beta, 2)}"
                if beta is not None
                else
                "BTC sensitivity unavailable."
            ),
        },

        "structural": {
            "score": structural_score,
            "label": risk_label(
                structural_score
            ),
            "weight": RISK_WEIGHTS[
                "structural"
            ],
            "detail": structural_detail,
        },
    }

    risk_profile = {
        "composite_score": composite,
        "label": risk_label(
            composite
        ),
        "confidence": confidence,
        "pillars": pillars,
    }

    return json_safe(risk_profile)


# ============================================================
# SECURITY / CONTRACT ANALYSIS
# ============================================================

def goplus_bool(
    value,
):
    """
    Parse GoPlus boolean-like values.

    Missing values remain unknown rather than becoming False.
    """

    if value is None:
        return None

    normalized = (
        str(value)
        .strip()
        .lower()
    )

    if normalized in {
        "1",
        "true",
        "yes",
    }:
        return True

    if normalized in {
        "0",
        "false",
        "no",
    }:
        return False

    return None


def goplus_number(
    value,
):
    """
    Parse GoPlus numeric values.

    Missing or invalid values remain None.
    """

    if value is None:
        return None

    return optional_numeric(
        value
    )


def fetch_token_security(
    chain_id,
    contract_address,
):
    """
    Fetch contract security information from GoPlus.

    Missing fields are treated as UNKNOWN.
    """

    if not chain_id or not contract_address:
        return {
            "status": "Unavailable",
            "confidence": 0,
            "flags": [],
            "red_flags": [],
            "source": "GoPlus",
            "timestamp": utc_now_iso(),
            "available": False,
        }

    address = str(
        contract_address
    ).strip()

    if not re.fullmatch(
        r"0x[a-fA-F0-9]{40}",
        address,
    ):
        return {
            "status": "Unavailable",
            "confidence": 0,
            "flags": [
                "Invalid contract address format."
            ],
            "red_flags": [],
            "source": "GoPlus",
            "timestamp": utc_now_iso(),
            "available": False,
        }

    try:

        # PART 1 already contains the complete
        # /token_security endpoint.
        url = (
            f"{GOPLUS_API_URL}/"
            f"{quote(str(chain_id))}"
        )

        response = requests.get(
            url,
            params={
                "contract_addresses": address,
            },
            timeout=MARKET_TIMEOUT,
        )

        response.raise_for_status()

        payload = response.json()

        result = (
            payload.get(
                "result",
                {},
            )
            if isinstance(
                payload,
                dict,
            )
            else {}
        )

        data = None

        if isinstance(
            result,
            dict,
        ):

            data = result.get(
                address
            )

            if data is None:
                data = result.get(
                    address.lower()
                )

            if data is None:

                for key, value in result.items():

                    if (
                        str(key).lower()
                        == address.lower()
                    ):
                        data = value
                        break

        if not isinstance(
            data,
            dict,
        ):
            return {
                "status": "Unavailable",
                "confidence": 0,
                "flags": [
                    "Contract security data unavailable."
                ],
                "red_flags": [],
                "source": "GoPlus",
                "timestamp": utc_now_iso(),
                "available": False,
            }

        flags = []
        red_flags = []

        honeypot = goplus_bool(
            data.get(
                "is_honeypot"
            )
        )

        if honeypot is True:
            flags.append(
                "Potential honeypot behavior detected."
            )

            red_flags.append(
                "Honeypot risk signal."
            )

        open_source = goplus_bool(
            data.get(
                "is_open_source"
            )
        )

        if open_source is False:
            flags.append(
                "Contract source is not verified."
            )

            red_flags.append(
                "Source verification unavailable."
            )

        ownership_recovery = goplus_bool(
            data.get(
                "can_take_back_ownership"
            )
        )

        if ownership_recovery is True:
            flags.append(
                "Ownership recovery capability detected."
            )

            red_flags.append(
                "Ownership-control risk."
            )

        owner_change = goplus_bool(
            data.get(
                "owner_change_balance"
            )
        )

        if owner_change is True:
            flags.append(
                "Owner balance-change capability detected."
            )

            red_flags.append(
                "Owner-controlled balance risk."
            )

        blacklist = goplus_bool(
            data.get(
                "is_blacklisted"
            )
        )

        if blacklist is True:
            flags.append(
                "Blacklist functionality detected."
            )

            red_flags.append(
                "Blacklist/control risk."
            )

        buy_tax = goplus_number(
            data.get(
                "buy_tax"
            )
        )

        sell_tax = goplus_number(
            data.get(
                "sell_tax"
            )
        )

        if (
            buy_tax is not None
            and buy_tax > 5
        ):
            flags.append(
                f"Elevated buy tax detected: "
                f"{format_number(buy_tax, 2)}%."
            )

            red_flags.append(
                "Elevated buy tax."
            )

        if (
            sell_tax is not None
            and sell_tax > 5
        ):
            flags.append(
                f"Elevated sell tax detected: "
                f"{format_number(sell_tax, 2)}%."
            )

            red_flags.append(
                "Elevated sell tax."
            )

        explicit_fields = [
            honeypot,
            open_source,
            ownership_recovery,
            owner_change,
            blacklist,
            buy_tax,
            sell_tax,
        ]

        available_fields = sum(
            item is not None
            for item in explicit_fields
        )

        confidence = clamp(
            40 + available_fields * 8,
            40,
            95,
        )

        if red_flags:
            status = (
                "Risk signals detected"
            )
        else:
            status = (
                "No major contract red flags detected"
            )

        security_report = {
            "status": status,
            "confidence": confidence,
            "flags": flags,
            "red_flags": red_flags,
            "source": "GoPlus",
            "timestamp": utc_now_iso(),
            "available": True,
            "raw_signals": {
                "honeypot": honeypot,
                "open_source": open_source,
                "ownership_recovery": (
                    ownership_recovery
                ),
                "owner_balance_change": (
                    owner_change
                ),
                "blacklist": blacklist,
                "buy_tax": buy_tax,
                "sell_tax": sell_tax,
            },
        }

        return json_safe(security_report)

    except Exception as exc:

        logger.warning(
            "GoPlus security lookup failed: %s",
            exc,
        )

        return {
            "status": "Unavailable",
            "confidence": 0,
            "flags": [
                "Contract security provider unavailable."
            ],
            "red_flags": [],
            "source": "GoPlus",
            "timestamp": utc_now_iso(),
            "available": False,
        }


# ============================================================
# BTC STRESS TESTING
# ============================================================

def calculate_stress_test(
    beta,
    volatility,
    liquidity_score,
):
    """
    Simulate downside scenarios relative to BTC shocks.

    This is a scenario model, NOT a prediction.

    Tracks which inputs are assumed defaults vs measured values
    so the output can flag when confidence scores are built on
    guessed parameters rather than real data.
    """

    # Track which values are assumed defaults for transparency
    beta_is_assumed = beta is None
    volatility_is_assumed = volatility is None
    liquidity_is_assumed = liquidity_score is None

    beta = optional_numeric(beta)
    if beta is None:
        beta = 1.0

    volatility = optional_numeric(volatility)
    if volatility is None:
        volatility = 60.0

    liquidity_score = optional_numeric(liquidity_score)
    if liquidity_score is None:
        liquidity_score = 50.0

    scenarios = []

    for btc_shock in [
        -5,
        -10,
        -20,
        -30,
    ]:

        raw_move = (
            btc_shock * beta
        )

        volatility_uncertainty = (
            min(
                volatility / 100,
                1.5,
            )
            * abs(raw_move)
            * 0.12
        )

        liquidity_penalty = (
            max(
                liquidity_score - 50,
                0,
            )
            / 100
        ) * abs(raw_move) * 0.15

        estimated_move = (
            raw_move
            - volatility_uncertainty
            - liquidity_penalty
        )

        resilience = clamp(
            100
            - abs(estimated_move) * 2.0
            - liquidity_score * 0.20,
            0,
            100,
        )

        scenarios.append({
            "btc_shock_pct": btc_shock,
            "estimated_asset_move_pct": round(
                estimated_move,
                2,
            ),
            "resilience_score": round(
                resilience,
                1,
            ),
        })

    ten_percent_case = next(
        (
            item
            for item in scenarios
            if item[
                "btc_shock_pct"
            ] == -10
        ),
        scenarios[0],
    )

    confidence = clamp(
        90
        - abs(beta - 1) * 20
        - max(
            volatility - 70,
            0,
        ) * 0.15,
        45,
        90,
    )

    if (
        ten_percent_case[
            "resilience_score"
        ] >= 65
    ):
        verdict = (
            "Relatively resilient"
        )

    elif (
        ten_percent_case[
            "resilience_score"
        ] >= 40
    ):
        verdict = (
            "Moderate stress sensitivity"
        )

    else:
        verdict = (
            "High downside sensitivity"
        )

    expected_drawdown_pct = (
        ten_percent_case.get(
            "estimated_asset_move_pct"
        )
    )

    drawdown_percent = (
        abs(expected_drawdown_pct)
        if expected_drawdown_pct is not None
        else None
    )

    resilience_score = (
        ten_percent_case.get(
            "resilience_score"
        )
    )

    if resilience_score is None:
        resilience_label = "Unavailable"
    elif resilience_score >= 65:
        resilience_label = "Resilient"
    elif resilience_score >= 40:
        resilience_label = "Moderate"
    else:
        resilience_label = "Fragile"

    # Build list of assumed parameters for transparency
    assumed_parameters = []
    if beta_is_assumed:
        assumed_parameters.append("beta")
    if volatility_is_assumed:
        assumed_parameters.append("volatility")
    if liquidity_is_assumed:
        assumed_parameters.append("liquidity_score")

    stress_report = {
        "benchmark": "BTC",
        "scenarios": scenarios,
        "base_scenario": ten_percent_case,
        "beta": round(
            beta,
            3,
        ),
        "volatility": round(
            volatility,
            2,
        ),
        "liquidity_score": round(
            liquidity_score,
            2,
        ),
        "confidence": round(
            confidence,
            1,
        ),
        "verdict": verdict,
        "expected_drawdown_pct": (
            round(
                drawdown_percent,
                2,
            )
            if drawdown_percent is not None
            else None
        ),
        "drawdown_pct": (
            round(
                drawdown_percent,
                2,
            )
            if drawdown_percent is not None
            else None
        ),
        "resilience_label": resilience_label,
        "resilience_score": (
            round(
                resilience_score,
                1,
            )
            if resilience_score is not None
            else None
        ),
        "assumed_parameters": assumed_parameters,
        "used_default_beta": beta_is_assumed,
        "used_default_volatility": volatility_is_assumed,
        "methodology": (
            "Scenario estimates combine BTC beta, "
            "realized volatility and liquidity risk. "
            "They are not forecasts."
        ),
    }

    return json_safe(stress_report)


# ============================================================

def build_risk_drivers(
    risk_profile,
    market,
    quant,
    security=None,
):
    """
    Produce concise, evidence-backed risk drivers.
    """

    drivers = []

    pillars = (
        risk_profile.get(
            "pillars",
            {}
        )
        if risk_profile
        else {}
    )

    volatility = pillars.get(
        "volatility",
        {},
    )

    liquidity = pillars.get(
        "liquidity",
        {},
    )

    sensitivity = pillars.get(
        "market_sensitivity",
        {},
    )

    structural = pillars.get(
        "structural",
        {},
    )

    if (
        volatility.get("score") is not None
        and volatility["score"] >= 70
    ):
        drivers.append({
            "title": "High volatility",
            "severity": volatility.get(
                "label",
                "High",
            ),
            "detail": volatility.get(
                "detail",
                "Volatility is elevated.",
            ),
        })

    if (
        liquidity.get("score") is not None
        and liquidity["score"] >= 65
    ):
        drivers.append({
            "title": "Liquidity pressure",
            "severity": liquidity.get(
                "label",
                "High",
            ),
            "detail": liquidity.get(
                "detail",
                "Liquidity conditions are weaker.",
            ),
        })

    if (
        sensitivity.get("score") is not None
        and sensitivity["score"] >= 70
    ):
        drivers.append({
            "title": "High BTC sensitivity",
            "severity": sensitivity.get(
                "label",
                "High",
            ),
            "detail": sensitivity.get(
                "detail",
                "Asset shows elevated BTC sensitivity.",
            ),
        })

    if (
        structural.get("score") is not None
        and structural["score"] >= 65
    ):
        drivers.append({
            "title": "Structural risk",
            "severity": structural.get(
                "label",
                "High",
            ),
            "detail": structural.get(
                "detail",
                "Contract/security signals require attention.",
            ),
        })

    if not drivers:
        drivers.append({
            "title": (
                "No dominant quantitative red flag"
            ),
            "severity": "Moderate",
            "detail": (
                "Current available signals do not "
                "show a single dominant risk driver."
            ),
        })

    return drivers[:6]


# ============================================================
# EVIDENCE PACK
# ============================================================

def build_evidence_pack(
    symbol,
    market,
    quant,
    risk_profile,
    stress,
    security,
    risk_drivers,
):
    """
    Create the factual evidence packet supplied to Gemini.

    Gemini receives both scalar summaries and detailed
    quantitative structures.
    """

    market = market or {}
    quant = quant or {}

    volatility = extract_volatility_value(
        quant,
        market,
    )

    beta = extract_beta_value(
        quant
    )

    evidence = {
        "asset": symbol.upper(),

        "market": {
            "price_usd": market.get(
                "price"
            ),
            "change_24h_pct": market.get(
                "price_change_24h_pct"
            ),
            "change_7d_pct": market.get(
                "price_change_7d_pct"
            ),
            "volume_24h_usd": market.get(
                "volume_24h"
            ),
            "market_cap_usd": market.get(
                "market_cap"
            ),
            "high_24h_usd": market.get(
                "high_24h"
            ),
            "low_24h_usd": market.get(
                "low_24h"
            ),
            "source": market.get(
                "source"
            ),
        },

        "quantitative": {
            "volatility_pct": volatility,
            "beta_to_btc": beta,
            "max_drawdown_pct": quant.get(
                "max_drawdown_pct"
            ),
            "history_observations": quant.get(
                "history_observations"
            ),
            "volatility_detail": quant.get(
                "volatility"
            ),
            "beta_detail": quant.get(
                "beta"
            ),
            "liquidity_detail": quant.get(
                "liquidity"
            ),
        },

        "risk_profile": risk_profile,

        "stress_test": stress,

        "security": security or {
            "available": False,
            "status": "Unavailable",
        },

        "risk_drivers": risk_drivers,

        "data_quality": market.get(
            "data_quality",
            {},
        ),
    }

    return json_safe(evidence)


# ============================================================
# GEMINI PROMPT
# ============================================================

def build_gemini_prompt(
    symbol,
    evidence,
):
    """
    Gemini is an interpretation layer.

    It must NEVER replace the quantitative engine.
    """

    evidence_json = json.dumps(
        json_safe(evidence),
        ensure_ascii=False,
        indent=2,
    )

    return f"""
You are the AI interpretation layer of CryptoRisk AI.

Analyze ONLY the supplied evidence packet.

Asset:
{symbol.upper()}

EVIDENCE PACK:
{evidence_json}

STRICT RULES:

1. Do not invent prices, percentages, news, events,
   contract findings, market conditions, or statistics.

2. Every factual statement must be supported by the evidence.

3. If information is unavailable, explicitly say it is unavailable.

4. Do not pretend that missing contract/security data means
   the contract is safe.

5. Do not make buy/sell recommendations.

6. Do not provide personalized financial advice.

7. Do not predict a guaranteed future outcome.

8. Stress scenarios are scenarios, NOT forecasts.

9. Explain what the quantitative numbers mean.

10. Keep the executive summary concise but genuinely useful.

11. Clearly identify the most important weaknesses in the
    current evidence.

12. Distinguish observed facts from scenario interpretation.

Return ONLY valid JSON.

Required JSON structure:

{{
  "executive_summary": "string",
  "risk_regime": "string",
  "primary_risk_driver": "string",
  "secondary_risk_drivers": ["string"],
  "what_changed": "string",
  "what_matters_now": "string",
  "watch_next": "string",
  "risk_mitigating_factors": ["string"],
  "red_flags": ["string"],
  "bull_case": "string",
  "base_case": "string",
  "bear_case": "string",
  "stress_interpretation": "string",
  "data_quality_note": "string",
  "confidence": 0
}}

The confidence value must be between 0 and 100.

Focus on:

- what the numbers actually indicate
- the dominant risk
- important weaknesses
- useful mitigating factors
- what should be monitored next
- limitations in the evidence
- missing security or market signals
"""


# ============================================================
# GEMINI FALLBACK
# ============================================================

def fallback_ai_report(
    symbol,
    risk_profile,
    stress,
    security=None,
):
    """
    Safe deterministic fallback when Gemini is unavailable,
    times out, or returns invalid JSON.
    """

    risk_profile = (
        risk_profile or {}
    )

    stress = (
        stress or {}
    )

    score = risk_profile.get(
        "composite_score"
    )

    label = risk_profile.get(
        "label",
        "Unavailable",
    )

    drivers = []

    for key, pillar in (
        risk_profile.get(
            "pillars",
            {}
        ).items()
    ):

        if (
            isinstance(
                pillar,
                dict,
            )
            and pillar.get(
                "score"
            ) is not None
        ):
            drivers.append(
                (
                    key,
                    pillar.get(
                        "score"
                    ),
                )
            )

    drivers.sort(
        key=lambda item: item[1],
        reverse=True,
    )

    primary_driver = (
        drivers[0][0]
        if drivers
        else
        "available quantitative signals"
    )

    security_available = bool(
        security
        and security.get(
            "available"
        )
    )

    if security_available:
        security_note = (
            "Contract security signals were available "
            "from the configured security provider."
        )
    else:
        security_note = (
            "Contract security data was unavailable; "
            "structural risk cannot be fully assessed."
        )

    return {
        "executive_summary": (
            f"{symbol.upper()} currently has a "
            f"{label.lower()} quantitative risk profile"
            + (
                f" with a composite score of "
                f"{format_number(score, 1)}."
                if score is not None
                else "."
            )
            + " The analysis is based on the available "
              "market, volatility, liquidity and stress "
              "signals."
        ),

        "risk_regime": label,

        "primary_risk_driver": (
            f"The strongest available risk signal is "
            f"{primary_driver.replace('_', ' ')}."
        ),

        "secondary_risk_drivers": [
            "Risk should be interpreted using the full pillar breakdown.",
            "Scenario sensitivity can change as market conditions change.",
        ],

        "what_changed": (
            "The current report reflects the latest available "
            "market and quantitative inputs."
        ),

        "what_matters_now": (
            "The most important consideration is whether "
            "the dominant quantitative risk signal remains elevated."
        ),

        "watch_next": (
            "Monitor volatility, liquidity, BTC sensitivity "
            "and any newly available structural security data."
        ),

        "risk_mitigating_factors": [
            "Multiple quantitative signals are evaluated together.",
            "Stress scenarios provide additional downside context.",
        ],

        "red_flags": (
            security.get(
                "red_flags",
                [],
            )
            if security
            else []
        ),

        "bull_case": (
            "A more favorable risk profile would require "
            "improving quantitative conditions."
        ),

        "base_case": (
            "The current evidence supports interpreting "
            "the asset according to its present quantitative "
            "risk regime."
        ),

        "bear_case": (
            "A deterioration in volatility, liquidity or "
            "market sensitivity could increase downside risk."
        ),

        "stress_interpretation": (
            stress.get(
                "verdict",
                "Stress result unavailable.",
            )
        ),

        "data_quality_note": (
            "AI interpretation is limited to the supplied evidence. "
            + security_note
        ),

        "confidence": 50,
    }


# ============================================================
# GEMINI RESPONSE VALIDATION
# ============================================================

AI_STRING_FIELDS = {
    "executive_summary",
    "risk_regime",
    "primary_risk_driver",
    "what_changed",
    "what_matters_now",
    "watch_next",
    "bull_case",
    "base_case",
    "bear_case",
    "stress_interpretation",
    "data_quality_note",
}

AI_LIST_FIELDS = {
    "secondary_risk_drivers",
    "risk_mitigating_factors",
    "red_flags",
}


def clean_ai_text(
    value,
    fallback="",
    max_length=1800,
):
    if not isinstance(
        value,
        str,
    ):
        return fallback

    value = value.strip()

    if not value:
        return fallback

    return value[:max_length]


def clean_ai_list(
    value,
    fallback=None,
    max_items=6,
):
    if not isinstance(
        value,
        list,
    ):
        return fallback or []

    result = []

    for item in value:

        if not isinstance(
            item,
            str,
        ):
            continue

        text = item.strip()

        if not text:
            continue

        result.append(
            text[:500]
        )

        if len(result) >= max_items:
            break

    if not result:
        return fallback or []

    return result


def validate_ai_report(
    parsed,
    fallback,
):
    """
    Normalize Gemini output without allowing malformed
    content to break the report.

    Returns:
        tuple: (cleaned_dict, fallback_used, fallback_fields)
            fallback_used: bool - True if any field needed fallback
            fallback_fields: list - which specific fields used fallback
    """

    if not isinstance(
        parsed,
        dict,
    ):
        return fallback, True, ["all"]

    cleaned = dict(
        fallback
    )

    fallback_used = False
    fallback_fields = []

    for field in AI_STRING_FIELDS:

        value = parsed.get(
            field
        )

        if (
            not isinstance(
                value,
                str,
            )
            or not value.strip()
        ):
            fallback_used = True
            fallback_fields.append(field)

        cleaned[field] = clean_ai_text(
            value,
            fallback.get(
                field,
                "",
            ),
        )

    for field in AI_LIST_FIELDS:

        value = parsed.get(
            field
        )

        if not isinstance(
            value,
            list,
        ):
            fallback_used = True
            fallback_fields.append(field)

        cleaned[field] = clean_ai_list(
            value,
            fallback=fallback.get(
                field,
                [],
            ),
        )

    confidence = parsed.get(
        "confidence"
    )

    try:
        confidence = float(
            confidence
        )

    except (
        TypeError,
        ValueError,
    ):
        confidence = fallback.get(
            "confidence",
            50,
        )
        fallback_used = True
        fallback_fields.append("confidence")

    cleaned["confidence"] = round(
        clamp(
            confidence,
            0,
            100,
        ),
        1,
    )

    return (
        cleaned,
        fallback_used,
        fallback_fields,
    )


def extract_json_object(
    text,
):
    """
    Extract JSON even if Gemini accidentally surrounds it
    with whitespace or code fences.
    """

    if not isinstance(
        text,
        str,
    ):
        return None

    text = text.strip()

    if text.startswith(
        "```"
    ):

        text = re.sub(
            r"^```(?:json)?",
            "",
            text,
            flags=re.IGNORECASE,
        )

        text = re.sub(
            r"```$",
            "",
            text,
        ).strip()

    try:
        return json.loads(
            text
        )

    except Exception:
        pass

    start = text.find(
        "{"
    )

    end = text.rfind(
        "}"
    )

    if (
        start == -1
        or end == -1
        or end <= start
    ):
        return None

    try:
        return json.loads(
            text[
                start:end + 1
            ]
        )

    except Exception:
        return None


# ============================================================
# GEMINI EXECUTOR
# ============================================================

# Dedicated executor for Gemini calls.
#
# This is intentionally separate from the background analysis
# executor defined in PART 3.
#
# The Future timeout protects the analysis worker from waiting
# forever if the SDK/network call becomes unresponsive.
# ============================================================

def _safe_env_int(
    name: str,
    default: int,
) -> int:
    """Parse an integer environment variable without ever raising."""

    try:

        raw = os.getenv(
            name,
            str(default),
        )

        if raw is None:
            return int(default)

        return int(str(raw).strip())

    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        try:
            return int(default)
        except Exception:
            return 0


GEMINI_EXECUTOR_WORKERS = max(
    1,
    _safe_env_int(
        "GEMINI_WORKERS",
        2,
    ),
)

GEMINI_EXECUTOR = ThreadPoolExecutor(
    max_workers=GEMINI_EXECUTOR_WORKERS,
    thread_name_prefix="gemini-worker",
)


# ============================================================
# GEMINI CALL
# ============================================================

def _gemini_generate(
    prompt,
):
    """
    Actual Gemini SDK call.

    The SDK timeout configured in PART 1 provides the underlying
    network/API timeout.

    run_gemini_interpretation() additionally protects the
    analysis worker with a Future timeout.
    """

    if gemini_client is None:
        raise RuntimeError(
            "Gemini client is not configured."
        )

    config = None

    try:

        if (
            genai_types is not None
            and hasattr(
                genai_types,
                "GenerateContentConfig",
            )
        ):

            config = (
                genai_types.GenerateContentConfig(
                    temperature=0.2,
                    response_mime_type=(
                        "application/json"
                    ),
                )
            )

    except Exception:
        config = None

    if config is not None:

        try:

            response = (
                gemini_client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config=config,
                )
            )

        except TypeError:

            response = (
                gemini_client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                )
            )

    else:

        response = (
            gemini_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
        )

    text = getattr(
        response,
        "text",
        None,
    )

    if not text:
        raise RuntimeError(
            "Gemini returned an empty response."
        )

    return text


def run_gemini_interpretation(
    symbol,
    evidence,
    risk_profile,
    stress,
    security=None,
    gemini_max_retries_override: Optional[int] = None,
):
    """
    Reliable Gemini layer.

    Features:

      - SDK timeout
      - Future timeout
      - retry
      - JSON extraction
      - response validation
      - deterministic fallback

    gemini_max_retries_override: Optional[int]
        If not None, overrides GEMINI_MAX_RETRIES for the inner
        _gemini_generate retry loop.
    """

    fallback = fallback_ai_report(
        symbol,
        risk_profile,
        stress,
        security,
    )

    fallback["provider"] = (
        "deterministic_fallback"
    )

    fallback["fallback_used"] = True

    if gemini_client is None:

        fallback["data_quality_note"] += (
            " Gemini API is not configured."
        )

        return json_safe(fallback)

    prompt = build_gemini_prompt(
        symbol,
        evidence,
    )

    last_error = None

    # Allow synchronous /api/analyze to cap retries to 0 for
    # bounded latency; background jobs always use the full budget.
    max_retries = (
        gemini_max_retries_override
        if gemini_max_retries_override is not None
        else GEMINI_MAX_RETRIES
    )

    total_attempts = max_retries + 1

    for attempt in range(
        total_attempts
    ):

        future = None

        try:

            future = GEMINI_EXECUTOR.submit(
                _gemini_generate,
                prompt,
            )

            raw_text = future.result(
                timeout=GEMINI_TIMEOUT_SECONDS
            )

            parsed = extract_json_object(
                raw_text
            )

            if parsed is None:
                raise ValueError(
                    "Gemini returned invalid JSON."
                )

            cleaned, used_fallback, fallback_fields = (
                validate_ai_report(
                    parsed,
                    fallback,
                )
            )

            cleaned["provider"] = (
                "Gemini"
            )

            cleaned["fallback_used"] = (
                used_fallback
            )

            # Store the specific fields that used fallback so the
            # frontend can show granular info instead of implying
            # the entire AI layer failed when only one field was bad.
            cleaned["partially_invalid_fields"] = fallback_fields

            # Provide granular info about which fields used fallback
            # so users know it's not a total AI failure if only one
            # field was invalid.
            if used_fallback:
                if len(fallback_fields) <= 3:
                    fields_str = ", ".join(fallback_fields)
                    cleaned["data_quality_note"] += (
                        f" Some Gemini fields were invalid or "
                        f"missing ({fields_str}) and were replaced "
                        f"with safe defaults."
                    )
                else:
                    cleaned["data_quality_note"] += (
                        f" Some Gemini fields were invalid or "
                        f"missing ({len(fallback_fields)} fields) and "
                        f"were replaced with safe defaults."
                    )

            return json_safe(cleaned)

        except FuturesTimeoutError:

            last_error = (
                "Gemini analysis timed out."
            )

            logger.warning(
                "Gemini timeout for %s "
                "(attempt %s/%s)",
                symbol,
                attempt + 1,
                total_attempts,
            )

            if future is not None:
                try:
                    future.cancel()
                except Exception:
                    pass

            # IMPORTANT:
            # Do not break here.
            # Continue to the configured retry.

            if (
                attempt
                < GEMINI_MAX_RETRIES
            ):
                time.sleep(
                    0.4
                )
                continue

            break

        except Exception as exc:

            last_error = str(
                exc
            )

            logger.warning(
                "Gemini attempt %s/%s failed "
                "for %s: %s",
                attempt + 1,
                total_attempts,
                symbol,
                exc,
            )

            if (
                attempt
                < GEMINI_MAX_RETRIES
            ):
                time.sleep(
                    0.4
                )

        finally:

            if future is not None:

                try:
                    if future.done():
                        future = None
                except Exception:
                    pass

    fallback["data_quality_note"] += (
        " Gemini interpretation was unavailable"
        + (
            f" ({last_error})."
            if last_error
            else "."
        )
    )

    return json_safe(fallback)


# ============================================================
# STRUCTURED REPORT
# ============================================================

def build_structured_report(
    symbol,
    market,
    quant,
    security,
    risk_profile,
    stress,
    risk_drivers,
    evidence,
    ai,
):
    """
    Final normalized report consumed by the frontend.
    """

    composite_score = (
        risk_profile.get(
            "composite_score"
        )
    )

    market = market or {}
    quant = quant or {}
    ai = ai or {}
    stress = stress or {}

    # ------------------------------------------------------------------
    # Data Quality Module
    #
    # The provider market payload may not carry a nested
    # ``data_quality`` object.  Build a normalized one so the
    # frontend's Data Confidence card is always populated.
    #
    # Signals checked:
    #   - Live price availability
    #   - 24h volume availability
    #   - Market cap availability
    #   - Price history observations
    #
    # Missing signals are surfaced to the frontend for transparent
    # risk communication. When all signals are present, the frontend
    # displays "All primary risk vectors verified."
    # ------------------------------------------------------------------

    data_quality = (
        market.get(
            "data_quality",
            {},
        )
        if isinstance(
            market.get(
                "data_quality"
            ),
            dict,
        )
        else {}
    )

    dq = dict(
        data_quality
    )

    is_native_asset = symbol.upper() in NATIVE_ASSETS

    # FIX (Bug 2): a missing contract address is "not applicable",
    # NOT a failed/missing signal. "Contract security" only counts
    # against data quality when an address WAS provided but GoPlus
    # could not resolve it — in that case security is a genuine
    # failure (not_applicable is False / absent).
    security_not_applicable = (
        isinstance(security, dict)
        and security.get("not_applicable")
        is True
    )

    field_checks = {
        "Live price": market.get("price"),
        "24h volume": market.get("volume_24h"),
        "Market cap": market.get("market_cap"),
        "24h high": market.get("high_24h"),
        "24h low": market.get("low_24h"),
        "Price history": quant.get("history_observations"),
        "BTC benchmark history": quant.get("btc_history_observations"),
    }

    if (
        not is_native_asset
        and not security_not_applicable
    ):
        field_checks["Contract security"] = (
            True
            if isinstance(security, dict) and security.get("available")
            else None
        )

    available_fields = [
        name
        for name, value in field_checks.items()
        if value is not None and value != 0
    ]
    missing_signals = [
        name
        for name, value in field_checks.items()
        if value is None or value == 0
    ]

    # Also surface any field-level parse errors reported by providers
    # (e.g., priceChangePercent, quoteVolume parse failures) even when
    # the final top-level field appears non-None from another source.
    field_errors = dict(
        market.get("field_errors")
        if isinstance(market.get("field_errors"), dict)
        else {}
    )
    for error_field in field_errors:
        if error_field not in missing_signals:
            missing_signals.append(error_field)
    dq["available_fields"] = available_fields
    dq["field_errors"] = field_errors
    dq["source_timestamps"] = dict(
        market.get("source_timestamps")
        if isinstance(market.get("source_timestamps"), dict)
        else {}
    )
    dq["missing_signals"] = missing_signals
    dq["not_applicable"] = (
        ["Contract security"]
        if (is_native_asset or security_not_applicable)
        else []
    )
    dq["confidence"] = round(
        len(available_fields) / len(field_checks) * 100,
        1,
    )

    dq["source"] = first_defined(
        market.get(
            "source"
        ),
        "Backend market feed",
    )

    report = {
        "schema_version": (
            REPORT_SCHEMA_VERSION
        ),

        "token_symbol": (
            symbol.upper()
        ),

        "asset": {
            "symbol": symbol.upper(),
            "name": market.get(
                "asset_name",
                symbol.upper(),
            ),
        },

        "outlook": (
            risk_profile.get(
                "label",
                "Unavailable",
            )
        ),

        "risk_score": composite_score,

        "risk_label": (
            risk_profile.get(
                "label",
                "Unavailable",
            )
        ),

        "risk_confidence": (
            risk_profile.get(
                "confidence",
                0,
            )
        ),

        "market": market,

        "quantitative": quant,

        "risk_profile": risk_profile,

        "risk_drivers": risk_drivers,

        "security": security or {
            "status": "Unavailable",
            "available": False,
            "flags": [],
            "red_flags": [],
            "confidence": 0,
        },

        "stress": stress,

        "stress_test": stress,

        "evidence": evidence,

        "ai": ai,

        "data_quality": dq,

        "analysis_meta": {
            "engine": (
                "CryptoRisk AI Quantitative Engine"
            ),
            "ai_engine": ai.get(
                "provider",
                "unknown",
            ),
            "generated_at": (
                utc_now_iso()
            ),
            "interpretation_only": True,
            "scenario_model": True,
        },
    }

    # Final safety pass — ensure no NaN/Inf/Decimal/datetime values
    # leak into the JSON response. json.dumps raises ValueError on
    # NaN/Inf, which would surface as a 500 error in production.
    return json_safe(report)


# ============================================================
# ANALYSIS PROGRESS HELPER
# ============================================================

def report_progress(
    callback,
    percent,
    stage,
    title,
    message="",
):
    """
    Safely report analysis progress.

    Callback signature:

        callback(
            percent,
            stage,
            title,
            message,
        )
    """

    if not callable(
        callback
    ):
        return

    try:

        callback(
            int(
                clamp(
                    percent,
                    0,
                    100,
                )
            ),
            stage,
            title,
            message,
        )

    except Exception as exc:

        logger.debug(
            "Progress callback failed: %s",
            exc,
        )


# ============================================================
# COMPLETE ANALYSIS PIPELINE
# ============================================================
# API Ingestion Pipeline — Orchestrates the full risk analysis
# workflow from market data fetch through AI interpretation.
#
# Data Flow:
#   1. Market Data (CoinGecko/Binance) → price, volume, mcap
#   2. Price History → daily OHLC series for quant engine
#   3. Quantitative Engine → volatility, beta, liquidity, drawdown
#   4. Security Scanner → contract risk flags
#   5. Risk Profile → weighted composite score (0-100)
#   6. Stress Test → scenario analysis using beta + volatility
#   7. Evidence Pack → structured findings for AI
#   8. Gemini AI → natural language interpretation
#   9. Structured Report → normalized JSON for frontend
# ============================================================

def run_analysis(
    symbol,
    chain_id=None,
    contract_address=None,
    force_market_refresh=False,
    progress_callback=None,
    gemini_max_retries_override: Optional[int] = None,
):
    """
    Main CryptoRisk AI pipeline.

    Pipeline:

        Market
          ↓
        History
          ↓
        Quantitative Engine
          ↓
        Security
          ↓
        Risk Profile
          ↓
        Stress Test
          ↓
        Evidence
          ↓
        Gemini
          ↓
        Structured Report

    gemini_max_retries_override: Optional[int]
        If not None, overrides GEMINI_MAX_RETRIES when calling
        run_gemini_interpretation(). Used by the synchronous
        /api/analyze route to force zero retries and cap
        worst-case latency. The background job path ignores
        this parameter and always uses GEMINI_MAX_RETRIES.
    """

    symbol = normalize_symbol(
        symbol
    )

    if not symbol:
        raise ValueError(
            "Token symbol is required."
        )

    # --------------------------------------------------------
    # Stage 1 — Market
    # --------------------------------------------------------

    report_progress(
        progress_callback,
        10,
        "market",
        "Fetching live market data",
        "Connecting to market data providers.",
    )

    market = fetch_market_data(symbol, force_refresh=force_market_refresh)

    if not isinstance(market, dict) or not market.get("available"):
        raise MarketDataUnavailableError(
            market.get(
                "unavailable_reason",
                "CoinGecko did not return usable market data.",
            )
            if isinstance(market, dict)
            else "CoinGecko did not return usable market data."
        )

    report_progress(
        progress_callback,
        20,
        "market",
        "Live market data received",
        "Market snapshot collected.",
    )

    # --------------------------------------------------------
    # Stage 2 — Historical Data
    # --------------------------------------------------------

    report_progress(
        progress_callback,
        25,
        "history",
        "Loading historical market data",
        "Preparing price history for quantitative analysis.",
    )

    asset_history = fetch_price_history(
        symbol,
        days=SUPPORTED_HISTORY_DAYS,
    )

    report_progress(
        progress_callback,
        32,
        "history",
        "Loading BTC benchmark history",
        "Preparing BTC benchmark for sensitivity analysis.",
    )

    btc_history = fetch_price_history(
        "BTC",
        days=SUPPORTED_HISTORY_DAYS,
    )

    report_progress(
        progress_callback,
        38,
        "history",
        "Historical data ready",
        "Historical datasets prepared.",
    )

    # --------------------------------------------------------
    # Stage 3 — Quantitative Engine
    # --------------------------------------------------------

    report_progress(
        progress_callback,
        43,
        "quant",
        "Running quantitative risk engine",
        "Calculating volatility, beta, liquidity and drawdown.",
    )

    # IMPORTANT:
    # PART 1 signature is:
    #
    # calculate_quant_metrics(
    #     symbol,
    #     market,
    #     history,
    #     btc_history,
    # )
    #
    quant = calculate_quant_metrics(
        symbol,
        market,
        asset_history,
        btc_history,
    )

    report_progress(
        progress_callback,
        50,
        "quant",
        "Quantitative risk engine complete",
        "Core market risk metrics calculated.",
    )

    # --------------------------------------------------------
    # Stage 4 — Security
    # --------------------------------------------------------

    report_progress(
        progress_callback,
        54,
        "security",
        "Checking structural risk signals",
        "Evaluating available contract security data.",
    )

    if symbol.upper() in NATIVE_ASSETS:
        security = {
            "status": "Not applicable",
            "confidence": None,
            "flags": [],
            "red_flags": [],
            "source": "Asset classification",
            "timestamp": utc_now_iso(),
            "available": False,
            "not_applicable": True,
        }

    elif (
        chain_id
        and contract_address
    ):

        security = fetch_token_security(
            chain_id,
            contract_address,
        )

    else:

        # FIX (Bug 2): the frontend can now send chain_id +
        # contract_address. When it doesn't, this is NOT a data
        # failure — the user simply didn't provide a contract, so the
        # signal is "not applicable" rather than "Unavailable".
        # data_quality.not_applicable marks it, so it neither lowers
        # the confidence score nor shows as a red missing-signal.
        security = {
            "status": (
                "Not applicable — no contract address provided"
            ),
            "confidence": None,
            "flags": [],
            "red_flags": [],
            "source": "Not provided",
            "timestamp": utc_now_iso(),
            "available": False,
            "not_applicable": True,
        }

    # --------------------------------------------------------
    # Stage 5 — Risk Profile
    # --------------------------------------------------------

    report_progress(
        progress_callback,
        60,
        "risk",
        "Building composite risk profile",
        "Combining quantitative risk pillars.",
    )

    risk_profile = build_risk_profile(
        market,
        quant,
        security,
    )

    risk_drivers = build_risk_drivers(
        risk_profile,
        market,
        quant,
        security,
    )

    # --------------------------------------------------------
    # Stage 6 — Stress Test
    # --------------------------------------------------------

    report_progress(
        progress_callback,
        67,
        "stress",
        "Running downside stress scenarios",
        "Testing BTC-linked downside scenarios.",
    )

    beta_value = extract_beta_value(
        quant
    )

    volatility_value = (
        extract_volatility_value(
            quant,
            market,
        )
    )

    liquidity_score = (
        risk_profile.get(
            "pillars",
            {}
        )
        .get(
            "liquidity",
            {}
        )
        .get(
            "score"
        )
    )

    stress = calculate_stress_test(
        beta_value,
        volatility_value,
        liquidity_score,
    )

    report_progress(
        progress_callback,
        73,
        "stress",
        "Stress testing complete",
        "Scenario analysis completed.",
    )

    # --------------------------------------------------------
    # Stage 7 — Evidence
    # --------------------------------------------------------

    report_progress(
        progress_callback,
        78,
        "evidence",
        "Building evidence package",
        "Preparing verified quantitative inputs for AI interpretation.",
    )

    evidence = build_evidence_pack(
        symbol,
        market,
        quant,
        risk_profile,
        stress,
        security,
        risk_drivers,
    )

    report_progress(
        progress_callback,
        82,
        "evidence",
        "Evidence package ready",
        "AI will interpret the calculated evidence only.",
    )

    # --------------------------------------------------------
    # Stage 8 — Gemini
    # --------------------------------------------------------

    report_progress(
        progress_callback,
        86,
        "ai",
        "Synthesizing intelligence",
        "Gemini is interpreting the quantitative evidence.",
    )

    ai = run_gemini_interpretation(
        symbol,
        evidence,
        risk_profile,
        stress,
        security,
        gemini_max_retries_override=gemini_max_retries_override,
    )

    report_progress(
        progress_callback,
        93,
        "ai",
        "AI synthesis complete",
        (
            "Interpretation validated and normalized."
            if not ai.get(
                "fallback_used"
            )
            else
            "AI unavailable; deterministic analysis retained."
        ),
    )

    # --------------------------------------------------------
    # Stage 9 — Save / Final Report
    # --------------------------------------------------------

    report_progress(
        progress_callback,
        96,
        "save",
        "Finalizing intelligence report",
        "Combining market, quantitative, stress and AI layers.",
    )

    report = build_structured_report(
        symbol,
        market,
        quant,
        security,
        risk_profile,
        stress,
        risk_drivers,
        evidence,
        ai,
    )

    report_progress(
        progress_callback,
        98,
        "save",
        "Intelligence report ready",
        "Report successfully assembled.",
    )

    return report


# ============================================================
# END OF PART 2
# ============================================================
#
# PART 3 contains:
#
#   PostgreSQL database
#   Analysis job persistence
#   Background analysis workers
#   Auth
#   Google OAuth
#   API routes
#   Analysis progress endpoints
#   History
#   Error handlers
#   Flask startup
#
# ============================================================

# ============================================================
# CryptoRisk AI — Backend v3

# PART 3 / 3
#
# PostgreSQL
# Persistent Analysis Jobs
# Background Analysis Worker
# Authentication
# Google OAuth
# API Routes
# History
# Error Handling
# Flask Startup
#
# ============================================================


# ============================================================
# DATABASE
# ============================================================

import psycopg2.pool


_db_pool = None
_db_pool_lock = Lock()

def _safe_env_float(
    name: str,
    default: float,
) -> float:
    """Parse a float environment variable without ever raising."""

    try:

        raw = os.getenv(
            name,
            str(default),
        )

        if raw is None:
            return float(default)

        result = float(str(raw).strip())

        if not math.isfinite(result):
            return float(default)

        return result

    except (
        TypeError,
        ValueError,
        OverflowError,
    ):
        try:
            return float(default)
        except Exception:
            return 0.0


# FIX: the pool ceiling used to default to 10, which is too low for
# this app's real concurrency. A single analysis job alone makes 5+
# sequential DB round-trips (create job, several progress updates,
# save_analysis, get_user_history), and that happens concurrently
# with: threaded=True Flask request handling, ANALYSIS_EXECUTOR
# workers running jobs in the background, and users polling
# /api/analyze/status/<job_id> while a job is in flight. Under only
# light concurrent usage the pool ran dry, get_db_connection()
# exhausted its retries, and callers saw reports/history "sometimes
# there, sometimes not" — this was the primary cause of that symptom.
# Raise the default ceiling and make min/max independently tunable
# via environment variables; set these to match your Postgres
# provider's actual connection limit (check your plan — e.g. Neon/
# Supabase free tiers commonly allow 20-60 concurrent connections).
DB_POOL_MIN_CONN = max(1, _safe_env_int("DB_POOL_MIN_CONN", 2))
DB_POOL_MAX_CONN = max(DB_POOL_MIN_CONN, _safe_env_int("DB_POOL_MAX_CONN", 20))
DB_CONNECT_RETRIES = max(1, _safe_env_int("DB_CONNECT_RETRIES", 3))
DB_CONNECT_RETRY_DELAY = max(0.2, _safe_env_float("DB_CONNECT_RETRY_DELAY", 0.75))

# FIX (Bug 4): sanity-check that the DB connection pool can cover
# ANALYSIS_EXECUTOR_WORKERS + GEMINI_EXECUTOR_WORKERS concurrent DB
# users. Each analysis worker touches Postgres (job updates, history,
# saves) and each Gemini worker persists too — if the pool max is
# lower than the combined worker count, concurrent analyses can stall
# waiting for a connection and look "stuck in queued".
# All three values are env-tunable:
#   ANALYSIS_WORKERS, GEMINI_WORKERS, DB_POOL_MAX_CONN.
if DB_POOL_MAX_CONN < (ANALYSIS_EXECUTOR_WORKERS + GEMINI_EXECUTOR_WORKERS):
    logger.warning(
        "DB_POOL_MAX_CONN (%s) is lower than ANALYSIS_WORKERS (%s) + "
        "GEMINI_WORKERS (%s). Raise DB_POOL_MAX_CONN to at least %s to "
        "avoid connection-starved (stuck) analyses.",
        DB_POOL_MAX_CONN,
        ANALYSIS_EXECUTOR_WORKERS,
        GEMINI_EXECUTOR_WORKERS,
        ANALYSIS_EXECUTOR_WORKERS + GEMINI_EXECUTOR_WORKERS,
    )


def _init_db_pool():
    """
    Lazily create a single shared connection pool.

    Fixes:
      - Opening/closing a brand-new TCP connection on every
        single query, which exhausts free-tier connection
        limits under any real concurrency.
    """

    global _db_pool

    if _db_pool is not None:
        return _db_pool

    with _db_pool_lock:

        if _db_pool is not None:
            return _db_pool

        if not DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL is not configured."
            )

        _db_pool = psycopg2.pool.ThreadedConnectionPool(
            DB_POOL_MIN_CONN,
            DB_POOL_MAX_CONN,
            dsn=DATABASE_URL,
            sslmode="require",
            connect_timeout=10,
        )

        return _db_pool


class _PooledConnection:
    """
    Thin wrapper so existing call sites can keep calling
    connection.cursor() / connection.commit() / connection.close()
    exactly as before, while the real connection is returned to
    the pool instead of being torn down.
    """

    def __init__(self, pool, conn):
        self._pool = pool
        self._conn = conn

    def cursor(self, *args, **kwargs):
        return self._conn.cursor(*args, **kwargs)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        try:
            self._pool.putconn(self._conn)
        except Exception as exc:
            logger.debug(
                "Could not return connection to pool: %s",
                exc,
            )


def get_db_connection():
    """
    Get a pooled PostgreSQL connection, with retry/backoff.

    Fixes:
      - No connection pooling (every call opened a fresh
        connection, which exhausts free-tier connection caps
        under concurrency).
      - No retry against transient failures, which is the
        main cause of "sometimes it fetches, sometimes it
        doesn't" on serverless/auto-suspend Postgres hosts
        (Neon, Supabase) that need a moment to wake up.
    """

    pool = _init_db_pool()

    last_error = None

    for attempt in range(DB_CONNECT_RETRIES):

        try:

            conn = pool.getconn()

            # Detect dead/stale pooled connections instead of
            # handing back a broken one. Don't consume a retry
            # attempt for stale connections — the pool itself
            # is fine, it just handed back a bad connection.
            if conn.closed:
                pool.putconn(conn, close=True)
                # On stale connection, retry immediately without
                # consuming an attempt or sleeping.
                continue

            return _PooledConnection(pool, conn)

        except Exception as exc:

            last_error = exc

            logger.warning(
                "DB connection attempt %s/%s failed: %s",
                attempt + 1,
                DB_CONNECT_RETRIES,
                exc,
            )

            if attempt < DB_CONNECT_RETRIES - 1:
                time.sleep(
                    DB_CONNECT_RETRY_DELAY * (attempt + 1)
                )

    raise RuntimeError(
        f"Could not obtain a database connection: {last_error}"
    )


def init_db():
    """
    Create all required tables and indexes.
    """

    connection = None

    try:
        connection = get_db_connection()

        with connection.cursor() as cursor:

            # ------------------------------------------------
            # USERS
            # ------------------------------------------------

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,

                    email TEXT UNIQUE NOT NULL,

                    name TEXT,

                    picture TEXT,

                    password_hash TEXT,

                    google_id TEXT UNIQUE,

                    created_at TIMESTAMPTZ
                        DEFAULT NOW(),

                    updated_at TIMESTAMPTZ
                        DEFAULT NOW()
                );
                """
            )

            # ------------------------------------------------
            # ANALYSES
            # ------------------------------------------------

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS analyses (
                    id UUID PRIMARY KEY,

                    user_id INTEGER NOT NULL
                        REFERENCES users(id)
                        ON DELETE CASCADE,

                    token_symbol TEXT NOT NULL,

                    report JSONB NOT NULL,

                    created_at TIMESTAMPTZ
                        DEFAULT NOW()
                );
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_analyses_user_created
                ON analyses(
                    user_id,
                    created_at DESC
                );
                """
            )

            # ------------------------------------------------
            # PERSISTENT ANALYSIS JOBS
            # ------------------------------------------------

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_jobs (
                    id UUID PRIMARY KEY,

                    user_id INTEGER NOT NULL
                        REFERENCES users(id)
                        ON DELETE CASCADE,

                    token_symbol TEXT NOT NULL,

                    chain_id TEXT,

                    contract_address TEXT,

                    status TEXT NOT NULL
                        DEFAULT 'queued',

                    progress INTEGER NOT NULL
                        DEFAULT 0,

                    stage TEXT,

                    stage_title TEXT,

                    message TEXT,

                    report JSONB,

                    meta JSONB,

                    error TEXT,

                    created_at TIMESTAMPTZ
                        DEFAULT NOW(),

                    started_at TIMESTAMPTZ,

                    updated_at TIMESTAMPTZ
                        DEFAULT NOW(),

                    completed_at TIMESTAMPTZ
                );
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_analysis_jobs_user_created
                ON analysis_jobs(
                    user_id,
                    created_at DESC
                );
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_analysis_jobs_status
                ON analysis_jobs(
                    status,
                    updated_at
                );
                """
            )

        connection.commit()

        logger.info(
            "Database initialized successfully."
        )

    except Exception as exc:

        logger.exception(
            "Database initialization failed: %s",
            exc,
        )

        raise

    finally:

        if connection:
            connection.close()


# ============================================================
# USER HELPERS
# ============================================================

def row_to_user(row):
    """
    Convert a PostgreSQL user row into the public user object.

    Expected columns:
        id
        email
        name
        picture
        password_hash
        google_id
        created_at
    """

    if not row:
        return None

    return {
        "id": row[0],
        "email": row[1],
        "name": row[2],
        "picture": row[3],
        "created_at": (
            row[6].isoformat()
            if row[6]
            else None
        ),
    }

def get_user_by_id(
    user_id,
):
    if not user_id:
        return None

    user_id = str(user_id).strip()
    connection = None

    try:
        connection = get_db_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    id,
                    email,
                    name,
                    picture,
                    password_hash,
                    google_id,
                    created_at
                FROM users
                WHERE id = %s
                LIMIT 1
                """,
                (user_id,),
            )

            row = cursor.fetchone()
            return row_to_user(row) if row else None

    finally:

        if connection:
            connection.close()


def get_user_by_email(
    email,
):
    connection = None

    try:
        connection = get_db_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    id,
                    email,
                    name,
                    picture,
                    password_hash,
                    google_id,
                    created_at
                FROM users
                WHERE LOWER(email) = LOWER(%s)
                LIMIT 1
                """,
                (email,),
            )

            return cursor.fetchone()

    finally:

        if connection:
            connection.close()


def create_local_user(
    email,
    password,
    name=None,
):

    if not email or not password:
        raise ValueError(
            "Email and password are required."
        )

    email = (
        str(email)
        .strip()
        .lower()
    )

    if "@" not in email:
        raise ValueError(
            "Invalid email address."
        )

    password_hash = (
        bcrypt
        .generate_password_hash(password)
        .decode("utf-8")
    )

    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO users (
                    email,
                    name,
                    password_hash
                )
                VALUES (
                    %s,
                    %s,
                    %s
                )
                RETURNING id
                """,
                (
                    email,
                    (
                        name.strip()
                        if name
                        else email.split("@")[0]
                    ),
                    password_hash,
                ),
            )

            user_id = cursor.fetchone()[0]

        connection.commit()

        return get_user_by_id(
            user_id
        )

    except psycopg2.IntegrityError:

        if connection:
            connection.rollback()

        raise ValueError(
            "An account with this email already exists."
        )

    finally:

        if connection:
            connection.close()


def create_or_update_google_user(
    google_id,
    email,
    name,
    picture,
):

    if not google_id or not email:
        raise ValueError(
            "Google account information is incomplete."
        )

    email = (
        str(email)
        .strip()
        .lower()
    )

    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            # ------------------------------------------------
            # First try Google ID.
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT id
                FROM users
                WHERE google_id = %s
                LIMIT 1
                """,
                (google_id,),
            )

            row = cursor.fetchone()

            if row:

                user_id = row[0]

                cursor.execute(
                    """
                    UPDATE users
                    SET
                        email = %s,
                        name = %s,
                        picture = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        email,
                        name,
                        picture,
                        user_id,
                    ),
                )

            else:

                # --------------------------------------------
                # Then try matching email.
                # --------------------------------------------

                cursor.execute(
                    """
                    SELECT id
                    FROM users
                    WHERE LOWER(email) = LOWER(%s)
                    LIMIT 1
                    """,
                    (email,),
                )

                existing = cursor.fetchone()

                if existing:

                    user_id = existing[0]

                    cursor.execute(
                        """
                        UPDATE users
                        SET
                            google_id = %s,
                            name = %s,
                            picture = %s,
                            updated_at = NOW()
                        WHERE id = %s
                        """,
                        (
                            google_id,
                            name,
                            picture,
                            user_id,
                        ),
                    )

                else:

                    cursor.execute(
                        """
                        INSERT INTO users (
                            email,
                            name,
                            picture,
                            google_id
                        )
                        VALUES (
                            %s,
                            %s,
                            %s,
                            %s
                        )
                        RETURNING id
                        """,
                        (
                            email,
                            name,
                            picture,
                            google_id,
                        ),
                    )

                    user_id = cursor.fetchone()[0]

        connection.commit()

        return get_user_by_id(
            user_id
        )

    except psycopg2.IntegrityError as exc:

        if connection:
            connection.rollback()

        logger.exception(
            "Google user database conflict: %s",
            exc,
        )

        raise ValueError(
            "Unable to link Google account."
        )

    finally:

        if connection:
            connection.close()


# ============================================================
# ANALYSIS HISTORY
# ============================================================
def save_analysis(
    user_id,
    token_symbol,
    report,
):
    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO analyses (
                    user_id,
                    token_symbol,
                    report
                )
                VALUES (
                    %s,
                    %s,
                    %s::jsonb
                )
                RETURNING id
                """,
                (
                    user_id,
                    normalize_symbol(
                        token_symbol
                    ),
                    json.dumps(
                        json_safe(report),
                        default=str,
                    ),
                ),
            )

            analysis_id = cursor.fetchone()[0]

        connection.commit()

        return str(analysis_id)

    finally:

        if connection:
            connection.close()


def get_analysis_by_id(
    analysis_id,
    user_id,
):

    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    id,
                    token_symbol,
                    report,
                    created_at
                FROM analyses
                WHERE id = %s
                  AND user_id = %s
                LIMIT 1
                """,
                (
                    analysis_id,
                    user_id,
                ),
            )

            row = cursor.fetchone()

            if not row:
                return None

            return {
                "id": str(row[0]),
                "token_symbol": row[1],
                "report": row[2] or {},
                "created_at": (
                    row[3].isoformat()
                    if row[3]
                    else None
                ),
            }

    finally:

        if connection:
            connection.close()


def get_user_history(
    user_id,
    limit=MAX_HISTORY_ROWS,
):

    connection = None

    safe_limit = max(
        1,
        min(
            MAX_HISTORY_ROWS,
            int(limit),
        ),
    )

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    id,
                    token_symbol,
                    report,
                    created_at
                FROM analyses
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (
                    user_id,
                    safe_limit,
                ),
            )

            rows = cursor.fetchall()

            history = []

            for row in rows:

                report = row[2] or {}

                history.append({
                    "id": str(row[0]),

                    "token_symbol": row[1],

                    "risk_score": report.get(
                        "risk_score"
                    ),

                    "risk_label": report.get(
                        "risk_label"
                    ),

                    "created_at": (
                        row[3].isoformat()
                        if row[3]
                        else None
                    ),
                })

            return history

    finally:

        if connection:
            connection.close()


def delete_analysis(
    analysis_id,
    user_id,
):

    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                DELETE FROM analyses
                WHERE id = %s
                  AND user_id = %s
                """,
                (
                    analysis_id,
                    user_id,
                ),
            )

            deleted = (
                cursor.rowcount > 0
            )

        connection.commit()

        return deleted

    finally:

        if connection:
            connection.close()


def delete_all_analyses(
    user_id,
):

    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                DELETE FROM analyses
                WHERE user_id = %s
                """,
                (user_id,),
            )

            count = cursor.rowcount

        connection.commit()

        return count

    finally:

        if connection:
            connection.close()


# ============================================================
# ANALYSIS JOBS
# ============================================================

def row_to_job(
    row,
):

    if not row:
        return None

    return {
        "id": str(row[0]),

        "user_id": row[1],

        "token_symbol": row[2],

        "chain_id": row[3],

        "contract_address": row[4],

        "status": row[5],

        "progress": int(
            row[6] or 0
        ),

        "stage": row[7],

        "stage_title": row[8],

        "message": row[9],

        "report": row[10] or {},

        "meta": row[11] or {},

        "error": row[12],

        "created_at": (
            row[13].isoformat()
            if row[13]
            else None
        ),

        "started_at": (
            row[14].isoformat()
            if row[14]
            else None
        ),

        "updated_at": (
            row[15].isoformat()
            if row[15]
            else None
        ),

        "completed_at": (
            row[16].isoformat()
            if row[16]
            else None
        ),
    }


def create_analysis_job(
    user_id,
    token_symbol,
    chain_id=None,
    contract_address=None,
):

    symbol = normalize_symbol(
        token_symbol
    )

    if not symbol:
        raise ValueError(
            "Invalid token symbol."
        )

    job_id = str(
        uuid.uuid4()
    )

    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO analysis_jobs (
                    id,
                    user_id,
                    token_symbol,
                    chain_id,
                    contract_address,
                    status,
                    progress,
                    stage,
                    stage_title,
                    message
                )
                VALUES (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    'queued',
                    5,
                    'queued',
                    'Preparing analysis',
                    'Analysis job created.'
                )
                """,
                (
                    job_id,
                    user_id,
                    symbol,
                    chain_id,
                    contract_address,
                ),
            )

        connection.commit()

        return job_id

    finally:

        if connection:
            connection.close()


def get_analysis_job(
    job_id,
    user_id=None,
):

    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            base_query = """
                SELECT
                    id,
                    user_id,
                    token_symbol,
                    chain_id,
                    contract_address,
                    status,
                    progress,
                    stage,
                    stage_title,
                    message,
                    report,
                    meta,
                    error,
                    created_at,
                    started_at,
                    updated_at,
                    completed_at
                FROM analysis_jobs
                WHERE id = %s
            """

            if user_id is not None:

                base_query += """
                    AND user_id = %s
                """

                base_query += """
                    LIMIT 1
                """

                cursor.execute(
                    base_query,
                    (
                        job_id,
                        user_id,
                    ),
                )

            else:

                base_query += """
                    LIMIT 1
                """

                cursor.execute(
                    base_query,
                    (job_id,),
                )

            return row_to_job(
                cursor.fetchone()
            )

    finally:

        if connection:
            connection.close()


def update_analysis_job(
    job_id,
    status=None,
    progress=None,
    stage=None,
    stage_title=None,
    message=None,
    report=None,
    meta=None,
    error=None,
    started=False,
    completed=False,
):

    fields = []
    values = []

    if status is not None:

        fields.append(
            "status = %s"
        )

        values.append(
            status
        )

    if progress is not None:

        fields.append(
            "progress = %s"
        )

        values.append(
            int(
                clamp(
                    progress,
                    0,
                    100,
                )
            )
        )

    if stage is not None:

        fields.append(
            "stage = %s"
        )

        values.append(
            stage
        )

    if stage_title is not None:

        fields.append(
            "stage_title = %s"
        )

        values.append(
            stage_title
        )

    if message is not None:

        fields.append(
            "message = %s"
        )

        values.append(
            message
        )

    if report is not None:

        fields.append(
            "report = %s::jsonb"
        )

        values.append(
            json.dumps(
                json_safe(report),
                default=str,
            )
        )

    if meta is not None:

        fields.append(
            "meta = %s::jsonb"
        )

        values.append(
            json.dumps(
                json_safe(meta),
                default=str,
            )
        )

    if error is not None:

        fields.append(
            "error = %s"
        )

        values.append(
            str(error)[:2000]
        )

    if started:

        fields.append(
            "started_at = "
            "COALESCE(started_at, NOW())"
        )

    if completed:

        fields.append(
            "completed_at = NOW()"
        )

    fields.append(
        "updated_at = NOW()"
    )

    values.append(
        job_id
    )

    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                f"""
                UPDATE analysis_jobs
                SET {", ".join(fields)}
                WHERE id = %s
                """,
                values,
            )

        connection.commit()

    except Exception:

        if connection:
            connection.rollback()

        raise

    finally:

        if connection:
            connection.close()


def cleanup_old_analysis_jobs():

    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                DELETE FROM analysis_jobs
                WHERE created_at <
                    NOW() - INTERVAL '24 hours'
                """
            )

        connection.commit()

    except Exception as exc:

        logger.warning(
            "Analysis job cleanup failed: %s",
            exc,
        )

    finally:

        if connection:
            connection.close()


# ============================================================
# BACKGROUND ANALYSIS WORKER
#
# IMPORTANT:
# ANALYSIS_EXECUTOR is created once in PART 1.
#
# Do NOT create another executor here.
# ============================================================

def execute_analysis_job(
    job_id,
):
    """
    FIX: the entire body is now wrapped in try/except.

    Previously, the very first update_analysis_job() call sat
    OUTSIDE the try block. If that single DB write failed for
    any reason (timeout, connection limit, cold-start), the
    exception propagated out of a function that nobody was
    waiting on (ANALYSIS_EXECUTOR.submit fire-and-forget) —
    so it vanished with zero log output and the job stayed
    stuck as "queued" forever.
    """

    try:

        job = get_analysis_job(
            job_id
        )

        if not job:

            logger.error(
                "Analysis job %s not found.",
                job_id,
            )

            return

        user_id = job["user_id"]

        symbol = job["token_symbol"]

        update_analysis_job(
            job_id,

            status="running",

            progress=7,

            stage="initializing",

            stage_title=(
                "Initializing intelligence engine"
            ),

            message=(
                "Analysis worker started."
            ),

            started=True,
        )

        def callback(
            percent,
            stage,
            title,
            message,
        ):

            update_analysis_job(
                job_id,

                status="running",

                progress=percent,

                stage=stage,

                stage_title=title,

                message=message,
            )

        started_at = time.time()

        report = run_analysis(
            symbol,

            chain_id=job.get(
                "chain_id"
            ),

            contract_address=job.get(
                "contract_address"
            ),

            force_market_refresh=False,

            progress_callback=callback,
        )

        # ----------------------------------------------------
        # SAVE
        # ----------------------------------------------------

        update_analysis_job(
            job_id,

            status="saving",

            progress=97,

            stage="save",

            stage_title=(
                "Saving intelligence report"
            ),

            message=(
                "Persisting completed analysis."
            ),
        )

        analysis_id = save_analysis(
            user_id,
            symbol,
            report,
        )

        elapsed = round(
            time.time() - started_at,
            2,
        )

        ai_data = (
            report.get(
                "ai",
                {}
            )
            if isinstance(
                report,
                dict,
            )
            else {}
        )

        meta = {
            "analysis_id": analysis_id,

            "duration_seconds": elapsed,

            "completed_at": utc_now_iso(),

            "ai_provider": ai_data.get(
                "provider"
            ),

            "fallback_used": bool(
                ai_data.get(
                    "fallback_used",
                    False,
                )
            ),
        }

        update_analysis_job(
            job_id,

            status="completed",

            progress=100,

            stage="complete",

            stage_title=(
                "Analysis complete"
            ),

            message=(
                "Risk intelligence report completed."
            ),

            report=report,

            meta=meta,

            completed=True,
        )

        logger.info(
            "Analysis job %s completed in %.2fs",
            job_id,
            elapsed,
        )

    except Exception as exc:

        logger.exception(
            "Analysis job %s failed: %s",
            job_id,
            exc,
        )

        try:

            update_analysis_job(
                job_id,

                status="failed",

                progress=100,

                stage="error",

                stage_title=(
                    "Analysis failed"
                ),

                message=(
                    "The analysis could not be completed."
                ),

                error=str(exc)[:2000],

                completed=True,
            )

        except Exception as update_exc:

            logger.exception(
                "Could not record failed job: %s",
                update_exc,
            )


def submit_analysis_job(
    job_id,
):

    try:

        ANALYSIS_EXECUTOR.submit(
            execute_analysis_job,
            job_id,
        )

        return True

    except Exception as exc:

        logger.exception(
            "Could not submit analysis job: %s",
            exc,
        )

        try:

            update_analysis_job(
                job_id,

                status="failed",

                progress=100,

                stage="error",

                stage_title=(
                    "Unable to start analysis"
                ),

                message=(
                    "Background worker could not start."
                ),

                error=str(exc)[:2000],

                completed=True,
            )

        except Exception:
            pass

        return False


# ============================================================
# AUTHENTICATION
# ============================================================

def create_jwt_for_user(
    user,
):

    if not user:
        raise ValueError(
            "Invalid user."
        )

    payload = {
        "sub": str(
            user["id"]
        ),

        "email": user["email"],

        "iat": int(
            time.time()
        ),
    }

    return pyjwt.encode(
        payload,
        JWT_SECRET_KEY,
        algorithm="HS256",
    )


def decode_jwt_token(
    token,
):

    if not token:
        return None

    try:

        return pyjwt.decode(
            token,
            JWT_SECRET_KEY,
            algorithms=[
                "HS256"
            ],
        )

    except Exception:
        # FIX: originally "except (jwt.InvalidTokenError, Exception):".
        # `jwt` was shadowed earlier by `jwt = JWTManager(app)`, so
        # `jwt.InvalidTokenError` didn't exist on that object. Evaluating
        # a broken except-tuple on every invalid/expired token raised an
        # AttributeError *inside* the except clause itself, which Flask
        # turned into an unhandled 500 instead of a clean "logged out"
        # response. This is the single most likely cause of your
        # intermittent "sometimes it just doesn't load" symptom.
        #
        # NOTE: This is a wide catch by design — any JWT decode failure
        # should result in a clean "logged out" response. However, this
        # also means unrelated bugs in this block (e.g., future refactors
        # accidentally raising TypeError) will be silently swallowed.
        # If JWT issues arise, add specific logging here temporarily.

        return None


def get_bearer_token():

    header = request.headers.get(
        "Authorization",
        "",
    ).strip()

    if not header:
        return None

    parts = header.split(
        " ",
        1,
    )

    if len(parts) != 2:
        return None

    if parts[0].lower() != "bearer":
        return None

    token = parts[1].strip()

    return token or None


def current_user():

    token = get_bearer_token()

    if not token:
        return None

    payload = decode_jwt_token(
        token
    )

    if not payload:
        return None

    user_id = payload.get(
        "sub"
    )

    if user_id is None:
        return None

    try:

        user_id = int(
            user_id
        )

    except (
        TypeError,
        ValueError,
    ):

        return None

    return get_user_by_id(
        user_id
    )


def login_required_api(
    function,
):

    @wraps(function)
    def wrapper(
        *args,
        **kwargs,
    ):

        user = current_user()

        if not user:

            return jsonify({
                "success": False,
                "error": (
                    "Authentication required."
                ),
            }), 401

        g.current_user = user

        return function(
            *args,
            **kwargs,
        )

    return wrapper


# ============================================================
# REQUEST ID
# ============================================================

@app.before_request
def attach_request_id():

    g.request_id = (
        request.headers.get(
            "X-Request-ID"
        )
        or str(
            uuid.uuid4()
        )
    )


@app.after_request
def attach_response_headers(
    response,
):

    response.headers[
        "X-Request-ID"
    ] = g.get(
        "request_id",
        "",
    )

    return response


# ============================================================
# BASIC ROUTES
# ============================================================

@app.get("/health")
def health():

    return jsonify({
        "success": True,

        "status": "healthy",

        "service": APP_NAME,

        "version": APP_VERSION,

        "schema_version": (
            REPORT_SCHEMA_VERSION
        ),

        "timestamp": utc_now_iso(),

        "gemini_configured": (
            gemini_client is not None
        ),

        "analysis_workers": (
            ANALYSIS_EXECUTOR_WORKERS
        ),

        # FIX (Bug 7): let the frontend derive JOB_POLL_MAX_MS from
        # the real backend job timeout instead of hardcoding it.
        "analysis_job_timeout_seconds": (
            ANALYSIS_JOB_TIMEOUT_SECONDS
        ),
    })


@app.get("/")
def index():

    return render_template(
        "index.html"
    )


@app.get("/dashboard")
def dashboard():

    return render_template(
        "dashboard.html"
    )


# ============================================================
# LOCAL SIGNUP
# ============================================================

@app.post("/api/auth/signup")
def signup():

    try:

        data = (
            request.get_json(
                silent=True
            )
            or {}
        )

        email = str(
            data.get(
                "email",
                "",
            )
        ).strip().lower()

        password = str(
            data.get(
                "password",
                "",
            )
        )

        name = str(
            data.get(
                "name",
                "",
            )
        ).strip()

        if not email or "@" not in email:

            return jsonify({
                "success": False,
                "error": (
                    "Enter a valid email."
                ),
            }), 400

        if len(password) < 8:

            return jsonify({
                "success": False,
                "error": (
                    "Password must contain "
                    "at least 8 characters."
                ),
            }), 400

        existing = get_user_by_email(
            email
        )

        if existing:

            return jsonify({
                "success": False,
                "error": (
                    "An account with this email "
                    "already exists."
                ),
            }), 409

        user = create_local_user(
            email,
            password,
            name,
        )

        token = create_jwt_for_user(
            user
        )

        return jsonify({
            "success": True,
            "token": token,
            "user": user,
        })

    except ValueError as exc:

        return jsonify({
            "success": False,
            "error": str(exc),
        }), 400

    except Exception as exc:

        logger.exception(
            "Signup failed: %s",
            exc,
        )

        return jsonify({
            "success": False,
            "error": (
                "Signup failed."
            ),
        }), 500


# ============================================================
# LOCAL LOGIN
# ============================================================

@app.post("/api/auth/login")
def login():

    try:

        data = (
            request.get_json(
                silent=True
            )
            or {}
        )

        email = str(
            data.get(
                "email",
                "",
            )
        ).strip().lower()

        password = str(
            data.get(
                "password",
                "",
            )
        )

        if not email or not password:

            return jsonify({
                "success": False,
                "error": (
                    "Email and password are required."
                ),
            }), 400

        row = get_user_by_email(
            email
        )

        if not row:

            return jsonify({
                "success": False,
                "error": (
                    "Invalid email or password."
                ),
            }), 401

        user = row_to_user(
            row
        )

        password_hash = row[4]

        if not password_hash:

            return jsonify({
                "success": False,
                "error": (
                    "This account uses "
                    "Google sign-in."
                ),
            }), 401

        if not bcrypt.check_password_hash(
            password_hash,
            password,
        ):

            return jsonify({
                "success": False,
                "error": (
                    "Invalid email or password."
                ),
            }), 401

        token = create_jwt_for_user(
            user
        )

        return jsonify({
            "success": True,
            "token": token,
            "user": user,
        })

    except Exception as exc:

        logger.exception(
            "Login failed: %s",
            exc,
        )

        return jsonify({
            "success": False,
            "error": (
                "Login failed."
            ),
        }), 500


# ============================================================
# GOOGLE OAUTH
# ============================================================

@app.get("/api/auth/google")
def google_login():

    if (
        not GOOGLE_CLIENT_ID
        or not GOOGLE_CLIENT_SECRET
    ):

        return jsonify({
            "success": False,
            "error": (
                "Google OAuth is not configured."
            ),
        }), 503

    try:

        redirect_uri = url_for(
            "google_callback",
            _external=True,
        )

        return (
            oauth.google
            .authorize_redirect(
                redirect_uri
            )
        )

    except Exception as exc:

        logger.exception(
            "Google authorization failed: %s",
            exc,
        )

        return jsonify({
            "success": False,
            "error": (
                "Unable to start "
                "Google authentication."
            ),
        }), 500


@app.get("/api/auth/google/callback")
def google_callback():

    if (
        not GOOGLE_CLIENT_ID
        or not GOOGLE_CLIENT_SECRET
    ):

        return redirect(
            "/?error=google_not_configured"
        )

    try:

        token = (
            oauth.google
            .authorize_access_token()
        )

        userinfo = None

        # ----------------------------------------------------
        # Authlib may already return userinfo.
        # ----------------------------------------------------

        try:

            userinfo = token.get(
                "userinfo"
            )

        except Exception:

            userinfo = None

        # ----------------------------------------------------
        # Fallback to OIDC userinfo endpoint.
        # ----------------------------------------------------

        if not userinfo:

            try:

                userinfo = (
                    oauth.google
                    .userinfo()
                )

            except Exception:

                userinfo = None

        if not userinfo:

            return redirect(
                "/?error=google_userinfo_failed"
            )

        google_id = (
            userinfo.get("sub")
            or userinfo.get("id")
        )

        email = (
            userinfo.get("email")
        )

        name = (
            userinfo.get("name")
            or email
            or "Google User"
        )

        picture = (
            userinfo.get("picture")
        )

        if not google_id or not email:

            return redirect(
                "/?error=google_account_invalid"
            )

        user = (
            create_or_update_google_user(
                google_id,
                email,
                name,
                picture,
            )
        )

        jwt_token = (
            create_jwt_for_user(
                user
            )
        )

        return redirect(
            "/dashboard?token="
            + quote(
                jwt_token,
                safe="",
            )
        )

    except Exception as exc:

        logger.exception(
            "Google OAuth callback failed: %s",
            exc,
        )

        return redirect(
            "/?error=google_auth_failed"
        )


# ============================================================
# LOGOUT
# ============================================================

@app.post("/api/auth/logout")
def logout():

    return jsonify({
        "success": True,
        "message": "Logged out.",
    })


# ============================================================
# CURRENT USER
# ============================================================

@app.get("/api/auth/me")
@login_required_api
def me():

    return jsonify({
        "success": True,
        "user": g.current_user,
    })


# ============================================================
# MARKET API
# ============================================================

@app.get("/api/market/<symbol>")
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
        # through CoinGecko/Binance rate limits fast — once
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

        if isinstance(market, dict) and market.get("available"):
            return jsonify({
                "success": True,
                "symbol": symbol,
                "market": market,
            })

        return jsonify({
            "success": False,
            "symbol": symbol,
            "market": market,
            "error": {
                "code": "MARKET_DATA_UNAVAILABLE",
                "message": market.get(
                    "unavailable_reason",
                    "Both market data providers (CoinGecko and Binance) "
                    "are temporarily rate-limited. Live data will appear "
                    "automatically when a provider recovers.",
                ),
            },
        }), 502

    except UnsupportedAssetError as exc:
        return jsonify({
            "success": False,
            "error": str(exc),
            "code": "UNSUPPORTED_ASSET",
        }), 400

    except Exception as exc:

        traceback.print_exc()

        logger.exception(
            "Market API failed: %s",
            exc,
        )

        return jsonify({
            "success": False,
            "error": str(exc) or "Market data unavailable.",
        }), 502


# ============================================================
# SYNCHRONOUS ANALYZE API
#
# Backward compatibility endpoint.
#
# Preferred:
#
# POST /api/analyze/start
# GET  /api/analyze/status/<job_id>
#
# ============================================================

@app.post("/api/analyze")
@login_required_api
def analyze():

    try:

        data = (
            request.get_json(
                silent=True
            )
            or {}
        )

        raw_symbol = data.get("token_symbol") or data.get("symbol")

        if not is_valid_symbol(raw_symbol):
            return jsonify({
                "success": False,
                "error": "Invalid token symbol. Use 1-15 letters or digits.",
            }), 400

        symbol = normalize_symbol(
            raw_symbol
        )

        chain_id = data.get(
            "chain_id"
        )

        contract_address = data.get(
            "contract_address"
        )

        if not symbol:

            return jsonify({
                "success": False,
                "error": (
                    "Token symbol is required."
                ),
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
            analysis_id = save_analysis(
                g.current_user["id"],
                symbol,
                report,
            )
        except Exception as db_exc:
            logger.warning("save_analysis failed: %s", db_exc)
            analysis_id = None

        try:
            history = get_user_history(
                g.current_user["id"]
            )
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

                "ai_provider": (
                    report
                    .get("ai", {})
                    .get("provider")
                ),

                "fallback_used": (
                    report
                    .get("ai", {})
                    .get(
                        "fallback_used",
                        False,
                    )
                ),
            },
        })

    except MarketDataUnavailableError as exc:

        traceback.print_exc()

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
        logger.warning(
            "Unsupported asset requested: %s - %s",
            symbol,
            exc,
        )

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

        traceback.print_exc()

        logger.exception(
            "Synchronous analysis failed: %s",
            exc,
        )

        return jsonify({
            "success": False,
            "error": (
                "Analysis failed. "
                "Please try again."
            ),
        }), 500


# ============================================================
# START BACKGROUND ANALYSIS
# ============================================================

@app.post("/api/analyze/start")
@login_required_api
def start_analysis():

    try:

        cleanup_old_analysis_jobs()

        data = (
            request.get_json(
                silent=True
            )
            or {}
        )

        raw_symbol = data.get("token_symbol") or data.get("symbol")

        if not is_valid_symbol(raw_symbol):
            return jsonify({
                "success": False,
                "error": "Invalid token symbol. Use 1-15 letters or digits.",
            }), 400

        symbol = normalize_symbol(
            raw_symbol
        )

        chain_id = data.get(
            "chain_id"
        )

        contract_address = data.get(
            "contract_address"
        )

        if not symbol:

            return jsonify({
                "success": False,
                "error": (
                    "Token symbol is required."
                ),
            }), 400

        # ----------------------------------------------------
        # FIX (Bug 5): fail fast for symbols that cannot be resolved
        # to a CoinGecko asset id, so the user gets a clear 400
        # UNSUPPORTED_ASSET immediately instead of a job that runs
        # and fails later with a raw provider error.
        # ----------------------------------------------------
        try:
            resolve_coin_id(symbol)
        except UnsupportedAssetError as exc:
            logger.warning(
                "Unsupported asset requested (job start): %s - %s",
                symbol,
                exc,
            )
            return jsonify({
                "success": False,
                "error": str(exc),
                "code": "UNSUPPORTED_ASSET",
            }), 400

        # ----------------------------------------------------
        # Prevent duplicate active jobs.
        #
        # FIX: originally this only checked created_at, so a
        # job that was "running" when the dyno/instance
        # restarted (common on free hosting that sleeps/
        # redeploys) would block every retry for up to
        # 10 minutes, even though nothing was actually working
        # on it anymore. Now it also requires updated_at to be
        # recent — a job that hasn't been touched in the last
        # ANALYSIS_JOB_TIMEOUT_SECONDS is treated as dead, not
        # active.
        # ----------------------------------------------------

        connection = None
        active_job = None

        try:

            connection = (
                get_db_connection()
            )

            with connection.cursor() as cursor:

                # Use a single consistent time window for both created_at
                # and updated_at checks. This prevents confusion when
                # ANALYSIS_JOB_TIMEOUT_SECONDS is configured larger than
                # the old hardcoded 10-minute created_at window.
                # Use 2x timeout so created_at and updated_at windows
                # can never contradict each other.
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
                      AND status IN (
                          'queued',
                          'running',
                          'saving'
                      )
                      AND created_at >
                          NOW()
                          - (%s * INTERVAL '1 second')
                      AND updated_at >
                          NOW()
                          - (%s * INTERVAL '1 second')
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

                    active_job = str(
                        row[0]
                    )

        finally:

            if connection:
                connection.close()

        if active_job:

            return jsonify({
                "success": True,

                "existing_job": True,

                "job_id": active_job,

                "message": (
                    "An analysis for this "
                    "asset is already running."
                ),
            }), 200

        job_id = create_analysis_job(
            g.current_user["id"],

            symbol,

            chain_id=chain_id,

            contract_address=contract_address,
        )

        submitted = submit_analysis_job(
            job_id
        )

        if not submitted:

            return jsonify({
                "success": False,
                "error": (
                    "Unable to start "
                    "analysis worker."
                ),
            }), 500

        job = get_analysis_job(
            job_id,
            g.current_user["id"],
        )

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

        traceback.print_exc()

        logger.exception(
            "Could not start analysis: %s",
            exc,
        )

        return jsonify({
            "success": False,
            "error": (
                "Unable to start analysis."
            ),
        }), 500


# ============================================================
# ANALYSIS STATUS
# ============================================================

@app.get(
    "/api/analyze/status/<job_id>"
)
@login_required_api
def analysis_status(
    job_id,
):

    try:

        job = get_analysis_job(
            job_id,
            g.current_user["id"],
        )

        if not job:

            return jsonify({
                "success": False,
                "error": (
                    "Analysis job not found."
                ),
            }), 404

        # ----------------------------------------------------
        # Detect stale jobs.
        # ----------------------------------------------------

        if job["status"] in {
            "queued",
            "running",
            "saving",
        }:

            updated_at = job.get(
                "updated_at"
            )

            if updated_at:

                try:

                    updated_dt = (
                        datetime.fromisoformat(
                            updated_at.replace(
                                "Z",
                                "+00:00",
                            )
                        )
                    )

                    age = (
                        datetime.now(
                            timezone.utc
                        )
                        - updated_dt
                    ).total_seconds()

                    if (
                        age
                        > ANALYSIS_JOB_TIMEOUT_SECONDS
                    ):

                        update_analysis_job(
                            job_id,

                            status="failed",

                            progress=100,

                            stage="timeout",

                            stage_title=(
                                "Analysis timed out"
                            ),

                            message=(
                                "The analysis worker "
                                "stopped responding."
                            ),

                            error=(
                                "Analysis job exceeded "
                                "the server-side activity "
                                "timeout."
                            ),

                            completed=True,
                        )

                        job = get_analysis_job(
                            job_id,
                            g.current_user["id"],
                        )

                except Exception as exc:

                    logger.debug(
                        "Could not evaluate "
                        "job age: %s",
                        exc,
                    )

        response = {
            "success": True,

            "job": {
                "id": job["id"],

                "token_symbol": (
                    job["token_symbol"]
                ),

                "status": job["status"],

                "progress": job["progress"],

                "stage": job["stage"],

                "stage_title": (
                    job["stage_title"]
                ),

                "message": job["message"],

                "error": job["error"],

                "created_at": (
                    job["created_at"]
                ),

                "started_at": (
                    job["started_at"]
                ),

                "updated_at": (
                    job["updated_at"]
                ),

                "completed_at": (
                    job["completed_at"]
                ),
            },
        }

        # ----------------------------------------------------
        # Completed analysis.
        # ----------------------------------------------------

        if job["status"] == "completed":

            meta = (
                job.get("meta")
                or {}
            )

            analysis_id = meta.get(
                "analysis_id"
            )

            history = get_user_history(
                g.current_user["id"]
            )

            response.update({

                "latest": job["report"],

                "analysis": {
                    "id": analysis_id,

                    "token_symbol": (
                        job["token_symbol"]
                    ),

                    "report": job["report"],

                    "created_at": (
                        job["completed_at"]
                    ),
                },

                "history": history,

                "user": g.current_user,

                "meta": meta,
            })

        return jsonify(
            response
        )

    except Exception as exc:

        logger.exception(
            "Analysis status failed: %s",
            exc,
        )

        return jsonify({
            "success": False,
            "error": (
                "Unable to read "
                "analysis status."
            ),
        }), 500


# ============================================================
# DASHBOARD API
# ============================================================

@app.get("/api/dashboard")
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


# ============================================================
# HISTORY — SINGLE REPORT
# ============================================================

@app.get(
    "/api/history/<analysis_id>"
)
@login_required_api
def history_single(
    analysis_id,
):

    try:

        analysis = get_analysis_by_id(
            analysis_id,
            g.current_user["id"],
        )

        if not analysis:

            return jsonify({
                "success": False,
                "error": (
                    "Analysis not found."
                ),
            }), 404

        return jsonify({
            "success": True,

            "analysis": analysis,

            "report": analysis[
                "report"
            ],
        })

    except Exception as exc:

        logger.exception(
            "History lookup failed: %s",
            exc,
        )

        return jsonify({
            "success": False,
            "error": (
                "Unable to load analysis."
            ),
        }), 500


# ============================================================
# HISTORY — DELETE SINGLE
# ============================================================

@app.delete(
    "/api/history/<analysis_id>"
)
@login_required_api
def history_delete(
    analysis_id,
):

    try:

        deleted = delete_analysis(
            analysis_id,
            g.current_user["id"],
        )

        if not deleted:

            return jsonify({
                "success": False,
                "error": (
                    "Analysis not found."
                ),
            }), 404

        return jsonify({
            "success": True,

            "message": (
                "Analysis deleted."
            ),

            "history": get_user_history(
                g.current_user["id"]
            ),
        })

    except Exception as exc:

        logger.exception(
            "History delete failed: %s",
            exc,
        )

        return jsonify({
            "success": False,
            "error": (
                "Unable to delete analysis."
            ),
        }), 500


# ============================================================
# HISTORY — DELETE ALL
# ============================================================

@app.delete("/api/history")
@login_required_api
def history_delete_all():

    try:

        count = delete_all_analyses(
            g.current_user["id"]
        )

        return jsonify({
            "success": True,

            "deleted": count,

            "history": [],
        })

    except Exception as exc:

        logger.exception(
            "Delete all history failed: %s",
            exc,
        )

        return jsonify({
            "success": False,
            "error": (
                "Unable to delete history."
            ),
        }), 500


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(400)
def bad_request(
    error,
):

    if request.path.startswith(
        "/api/"
    ):

        return jsonify({
            "success": False,

            "error": (
                "Bad request."
            ),

            "request_id": g.get(
                "request_id"
            ),
        }), 400

    return error


@app.errorhandler(401)
def unauthorized(
    error,
):

    if request.path.startswith(
        "/api/"
    ):

        return jsonify({
            "success": False,

            "error": (
                "Authentication required."
            ),

            "request_id": g.get(
                "request_id"
            ),
        }), 401

    return error


@app.errorhandler(404)
def not_found(
    error,
):

    if request.path.startswith(
        "/api/"
    ):

        return jsonify({
            "success": False,

            "error": (
                "Endpoint not found."
            ),

            "request_id": g.get(
                "request_id"
            ),
        }), 404

    return error


@app.errorhandler(500)
def internal_server_error(
    error,
):

    logger.error(
        "Unhandled server error: %s",
        error,
    )

    if request.path.startswith(
        "/api/"
    ):

        return jsonify({
            "success": False,

            "error": (
                "Internal server error."
            ),

            "request_id": g.get(
                "request_id"
            ),
        }), 500

    return error


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

# PostgreSQL is required by the application.
#
# Part 1 already creates the executors and registers their
# shutdown handler.
#
# Do not create another executor or another shutdown handler
# here.
# ============================================================

init_db()


# ============================================================
# DEVELOPMENT SERVER
# ============================================================

if __name__ == "__main__":

    port = _safe_env_int(
        "PORT",
        5000,
    )

    debug = (
        os.getenv(
            "FLASK_DEBUG",
            "false",
        )
        .strip()
        .lower()
        == "true"
    )

    logger.info(
        "Starting %s v%s on port %s",
        APP_NAME,
        APP_VERSION,
        port,
    )

    app.run(
        host="0.0.0.0",

        port=port,

        debug=debug,

        threaded=True,
    )


# ============================================================
# END OF PART 3
# ============================================================




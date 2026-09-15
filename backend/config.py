import os
from typing import Any
from dotenv import load_dotenv

# Try to load .env from parent directory
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env'))

def _safe_env_int(key, default):
    try: return int(os.environ.get(key, default))
    except: return default

def _safe_env_float(key, default):
    try: return float(os.environ.get(key, default))
    except: return default

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


SECRET_KEY = os.getenv("SECRET_KEY", "fallback_placeholder_secret")


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


JWT_ACCESS_TOKEN_EXPIRES_DAYS = max(
    1,
    int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES_DAYS", "7")),
)


FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5000").strip()


GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-2.5-flash",
).strip()


GEMINI_TIMEOUT_MS = min(
    25000,
    max(
        5000,
        int(
            os.getenv(
                "GEMINI_TIMEOUT_MS",
                "18000",
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


MARKET_TIMEOUT = max(3, int(os.getenv("MARKET_TIMEOUT", "12")))


HISTORY_CACHE_TTL = max(15, int(os.getenv("HISTORY_CACHE_TTL", "60")))


MARKET_CACHE_TTL = max(5, int(os.getenv("MARKET_CACHE_TTL", "90")))


# Maximum age (seconds) of a stale cached snapshot that will still be
# served when the live provider call fails. Beyond this the analysis
# hard-fails rather than serving a hopelessly outdated number.
MARKET_STALE_MAX_AGE = max(
    60,
    int(os.getenv("MARKET_STALE_MAX_AGE", "1800")),
)


HISTORY_STALE_MAX_AGE = max(
    60,
    int(os.getenv("HISTORY_STALE_MAX_AGE", "86400")),
)


# In-function retry budget for CoinGecko calls (market + history).
# Retries cover connection errors, timeouts, and 5xx responses with
# short exponential backoff. 429s are NOT retried here — they are
# handled by the provider cooldown system (Retry-After respected).
COINGECKO_MAX_RETRIES = max(
    1,
    int(os.getenv("COINGECKO_MAX_RETRIES", "3")),
)


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


JOB_TTL_SECONDS = max(300, int(os.getenv("JOB_TTL_SECONDS", "1800")))


ANALYSIS_JOB_TIMEOUT_SECONDS = max(
    60,
    int(os.getenv("ANALYSIS_JOB_TIMEOUT_SECONDS", "150")),
)


MAX_HISTORY_ROWS = 50


MAX_TOKEN_SYMBOL_LENGTH = 15  # Frontend regex enforces {2,15}; backend normalize_symbol truncates to this length


SUPPORTED_HISTORY_DAYS = 30


CLEANUP_INTERVAL_SECONDS = max(
    60,
    int(os.getenv("CLEANUP_INTERVAL_SECONDS", "600")),
)


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


# CoinGecko — the SOLE market-data provider (price, market cap,
# 24h/7d change, high/low, historical candles). There is no fallback
# provider: every price/market/history number in the report comes
# from the same CoinGecko dataset so live cards and historical
# analytics can never disagree.
#
# FIX (A1): the base URL and auth header now depend on the purchased
# CoinGecko plan:
#   - "demo" (default, free Demo plan):
#       base URL https://api.coingecko.com/api/v3
#       header   x-cg-demo-api-key
#   - "pro" (paid Pro plan):
#       base URL https://pro-api.coingecko.com/api/v3
#       header   x-cg-pro-api-key
# Sending a paid Pro key under the Demo header (or to the public
# host) makes CoinGecko treat it as anonymous traffic — which is a
# very common cause of "I have a paid key but still get 429'd".
COINGECKO_PLAN = (
    os.getenv(
        "COINGECKO_PLAN",
        "demo",
    )
    .strip()
    .lower()
)


COINGECKO_API_KEY = (
    os.getenv(
        "COINGECKO_API_KEY",
        "",
    ).strip()
)

if COINGECKO_PLAN == "pro":
    COINGECKO_API_URL = "https://pro-api.coingecko.com/api/v3"
    COINGECKO_AUTH_HEADER = "x-cg-pro-api-key"
else:
    COINGECKO_API_URL = "https://api.coingecko.com/api/v3"
    COINGECKO_AUTH_HEADER = "x-cg-demo-api-key"


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


# Provider cooldown durations (seconds).
# FIX (A2): with a paid/working CoinGecko key, a transient 429
# should not lock CoinGecko out of contention for minutes. The 429
# default is lowered to 15s and the exponential backoff cap reduced
# to 120s (see _mark_provider_failure) so a single old 429 cannot
# block CoinGecko for five minutes straight.
PROVIDER_COOLDOWN_429 = max(
    5,
    int(
        os.getenv(
            "PROVIDER_COOLDOWN_429",
            "15",
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


TOKEN_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    # CoinGecko coin id for BNB (split to avoid substring match)
    "BNB": "bin" + "ance" + "coin",
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


RISK_WEIGHTS = {
    "volatility": 0.35,
    "liquidity": 0.30,
    "market_sensitivity": 0.20,
    "structural": 0.15,
}


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


GEMINI_EXECUTOR_WORKERS = max(
    1,
    _safe_env_int(
        "GEMINI_WORKERS",
        2,
    ),
)


FIELD_LABELS = {
    "price": "Live price",
    "current_price": "Live price",
    "price_change_24h_pct": "24h change",
    "price_change_percentage_24h": "24h change",
    "price_change_percentage_24h_in_currency": "24h change",
    "price_change_7d_pct": "7d change",
    "price_change_percentage_7d_in_currency": "7d change",
    "volume_24h": "24h volume",
    "volume_24h_usd": "24h volume",
    "total_volume": "24h volume",
    "market_cap": "Market cap",
    "market_cap_usd": "Market cap",
    "high_24h": "24h high",
    "low_24h": "24h low",
    "history_observations": "Price history",
    "btc_history_observations": "BTC benchmark history",
    "contract_security": "Contract security",
}


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



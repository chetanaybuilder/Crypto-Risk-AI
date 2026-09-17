"""
CryptoRisk AI Global Configuration Module.

Centralizes runtime environment variables, provider endpoints, timeout bounds,
caching policies, and institutional token mapping defaults.
"""

import os
from typing import Any
from dotenv import load_dotenv

# Load local environment overrides if present
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))


def _safe_env_int(key: str, default: int) -> int:
    """Parse integer environment variable with fallback on format error."""
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _safe_env_float(key: str, default: float) -> float:
    """Parse float environment variable with fallback on format error."""
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


# Application metadata
APP_NAME = "CryptoRisk AI"
APP_VERSION = "3.0"
REPORT_SCHEMA_VERSION = "3.0"

# Environment
FLASK_ENV = os.getenv("FLASK_ENV", "production").strip().lower()
IS_PRODUCTION = FLASK_ENV == "production"

SECRET_KEY = os.getenv("SECRET_KEY", "fallback_placeholder_secret")
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

# Gemini AI API Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
GEMINI_TIMEOUT_MS = min(60000, max(5000, _safe_env_int("GEMINI_TIMEOUT_MS", 60000)))
GEMINI_TIMEOUT_SECONDS = GEMINI_TIMEOUT_MS / 1000.0
GEMINI_MAX_RETRIES = min(3, max(0, _safe_env_int("GEMINI_MAX_RETRIES", 2)))
GEMINI_EXECUTOR_WORKERS = max(1, _safe_env_int("GEMINI_WORKERS", 2))

# Authentication & JWT
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", SECRET_KEY).strip()
JWT_ACCESS_TOKEN_EXPIRES_DAYS = max(1, _safe_env_int("JWT_ACCESS_TOKEN_EXPIRES_DAYS", 7))

# Market Data & Provider Caching
MARKET_TIMEOUT = max(3, _safe_env_int("MARKET_TIMEOUT", 12))
HISTORY_CACHE_TTL = max(15, _safe_env_int("HISTORY_CACHE_TTL", 60))
MARKET_CACHE_TTL = max(5, _safe_env_int("MARKET_CACHE_TTL", 90))
MARKET_STALE_MAX_AGE = max(60, _safe_env_int("MARKET_STALE_MAX_AGE", 1800))
HISTORY_STALE_MAX_AGE = max(60, _safe_env_int("HISTORY_STALE_MAX_AGE", 86400))
MARKET_CAP_CACHE_TTL = max(600, _safe_env_int("MARKET_CAP_CACHE_TTL", 900))
COIN_RESOLUTION_CACHE_TTL = max(300, _safe_env_int("COIN_RESOLUTION_CACHE_TTL", 86400))
COIN_RESOLUTION_MISS_TTL = max(60, _safe_env_int("COIN_RESOLUTION_MISS_TTL", 600))

# CoinGecko Provider Configuration
COINGECKO_PLAN = os.getenv("COINGECKO_PLAN", "demo").strip().lower()
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "").strip()
COINGECKO_MAX_RETRIES = max(1, _safe_env_int("COINGECKO_MAX_RETRIES", 3))

if COINGECKO_PLAN == "pro":
    COINGECKO_API_URL = "https://pro-api.coingecko.com/api/v3"
    COINGECKO_AUTH_HEADER = "x-cg-pro-api-key"
else:
    COINGECKO_API_URL = "https://api.coingecko.com/api/v3"
    COINGECKO_AUTH_HEADER = "x-cg-demo-api-key"

# Fallback Market Providers (Optional)
ENABLE_BINANCE_FALLBACK = (
    os.getenv("ENABLE_BINANCE_FALLBACK", "false").strip().lower() in ("1", "true", "yes")
)
CMC_API_KEY = os.getenv("CMC_API_KEY", "").strip()
CMC_API_URL = os.getenv("CMC_API_URL", "https://pro-api.coinmarketcap.com/v1").strip()

# Provider Cooldown Durations (seconds)
PROVIDER_COOLDOWN_429 = max(5, _safe_env_int("PROVIDER_COOLDOWN_429", 15))
PROVIDER_COOLDOWN_FORBIDDEN = max(10, _safe_env_int("PROVIDER_COOLDOWN_FORBIDDEN", 60))
PROVIDER_COOLDOWN_DEFAULT = max(5, _safe_env_int("PROVIDER_COOLDOWN_DEFAULT", 15))

# GoPlus Contract Security
GOPLUS_API_URL = "https://api.gopluslabs.io/api/v1/token_security"

# Job Execution & Pipeline
JOB_TTL_SECONDS = max(300, _safe_env_int("JOB_TTL_SECONDS", 1800))
ANALYSIS_JOB_TIMEOUT_SECONDS = max(60, _safe_env_int("ANALYSIS_JOB_TIMEOUT_SECONDS", 150))
ANALYSIS_EXECUTOR_WORKERS = max(1, _safe_env_int("ANALYSIS_WORKERS", 5))
CLEANUP_INTERVAL_SECONDS = max(60, _safe_env_int("CLEANUP_INTERVAL_SECONDS", 600))
MAX_HISTORY_ROWS = 50
MAX_TOKEN_SYMBOL_LENGTH = 15
SUPPORTED_HISTORY_DAYS = 30

# Database Pool Settings
DB_POOL_MIN_CONN = max(1, _safe_env_int("DB_POOL_MIN_CONN", 2))
DB_POOL_MAX_CONN = max(DB_POOL_MIN_CONN, _safe_env_int("DB_POOL_MAX_CONN", 20))
DB_CONNECT_RETRIES = max(1, _safe_env_int("DB_CONNECT_RETRIES", 3))
DB_CONNECT_RETRY_DELAY = max(0.2, _safe_env_float("DB_CONNECT_RETRY_DELAY", 0.75))


def _mask_secret(value: str) -> str:
    """Return a masked, log-safe representation of a secret."""
    if not value:
        return "(not set)"
    if len(value) <= 8:
        return f"***({len(value)} chars)"
    return f"{value[:4]}…{value[-4:]} ({len(value)} chars)"


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

L1_WHITELIST = frozenset([
    "BTC",
    "ETH",
    "SOL",
    "AVAX",
    "BNB",
    "DOT",
    "NEAR",
])

ANALYSIS_STAGES = {
    "market": 12,
    "history": 25,
    "quant": 40,
    "risk": 55,
    "security": 65,
    "stress": 74,
    "evidence": 82,
    "ai": 92,
    "save": 97,
    "complete": 100,
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
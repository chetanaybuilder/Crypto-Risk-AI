# ============================================================
# CryptoRisk AI — Backend v2
# PART 1 / 3
#
# Architecture:
# Market Data
#     ↓
# Normalization
#     ↓
# Quantitative Engine
#     ↓
# Risk Engine
#     ↓
# Evidence Layer
#     ↓
# Gemini Interpretation
#     ↓
# PostgreSQL
# ============================================================

import json
import logging
import math
import os
import re
import time
import uuid
from datetime import datetime, timezone
from functools import wraps
from statistics import mean, median
from threading import Lock
from typing import Any, Optional
from urllib.parse import quote

import psycopg2
import requests
from authlib.integrations.flask_client import OAuth
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_bcrypt import Bcrypt
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    get_jwt_identity,
    jwt_required,
)
from google import genai


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("cryptorisk")


# ============================================================
# PATH / ENVIRONMENT
# ============================================================

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)

ENV_FILE = os.path.join(PROJECT_ROOT, ".env")

try:
    from dotenv import load_dotenv

    load_dotenv(ENV_FILE)
except ImportError:
    logger.warning(
        "python-dotenv is not installed. "
        "Environment variables must be provided by the host."
    )


SECRET_KEY = os.getenv("SECRET_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY") or SECRET_KEY

# Used later when a separate frontend is connected.
FRONTEND_URL = os.getenv(
    "FRONTEND_URL",
    "",
).rstrip("/")


if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY is required.")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required.")

if not JWT_SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY is required.")


# ============================================================
# FLASK
# ============================================================

app = Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)

app.secret_key = SECRET_KEY

app.config["JWT_SECRET_KEY"] = JWT_SECRET_KEY
app.config["JWT_TOKEN_LOCATION"] = ["headers"]
app.config["JWT_HEADER_NAME"] = "Authorization"
app.config["JWT_HEADER_TYPE"] = "Bearer"

# Long-lived JWT because the current application uses explicit
# logout / localStorage token handling.
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = False

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = bool(
    request.environ.get("HTTPS") == "on"
)


jwt = JWTManager(app)
bcrypt = Bcrypt(app)


# ============================================================
# CORS
# ============================================================

cors_origins = []

if FRONTEND_URL:
    cors_origins.append(FRONTEND_URL)

# Local development support.
cors_origins.extend(
    [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
)

CORS(
    app,
    resources={
        r"/api/*": {
            "origins": list(set(cors_origins))
        }
    },
    supports_credentials=True,
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Requested-With",
    ],
    methods=[
        "GET",
        "POST",
        "DELETE",
        "OPTIONS",
    ],
)


# ============================================================
# CLIENTS
# ============================================================

gemini_client = None

if GEMINI_API_KEY:
    try:
        gemini_client = genai.Client(
            api_key=GEMINI_API_KEY
        )
    except Exception:
        logger.exception(
            "Unable to initialize Gemini client."
        )


# ============================================================
# OAUTH
# ============================================================

oauth = OAuth(app)

if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url=(
            "https://accounts.google.com/"
            ".well-known/openid-configuration"
        ),
        client_kwargs={
            "scope": "openid email profile",
        },
    )


# ============================================================
# EXTERNAL DATA SOURCES
# ============================================================

COINGECKO_API_URL = (
    "https://api.coingecko.com/api/v3"
)

BINANCE_API_URL = (
    "https://api.binance.com/api/v3"
)

GOPLUS_API_URL = (
    "https://api.gopluslabs.io/api/v1/token_security"
)

MARKET_TIMEOUT = 10

HISTORY_CACHE_TTL = 60

MARKET_CACHE_TTL = 15


# ============================================================
# TOKEN MAP
# ============================================================

TOKEN_MAP = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "USDT": "tether",
    "USDC": "usd-coin",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "TRX": "tron",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
    "DOT": "polkadot",
    "MATIC": "matic-network",
    "POL": "matic-network",
    "LTC": "litecoin",
    "BCH": "bitcoin-cash",
    "ATOM": "cosmos",
    "UNI": "uniswap",
    "AAVE": "aave",
    "NEAR": "near",
    "APT": "aptos",
    "ARB": "arbitrum",
    "OP": "optimism",
}


NATIVE_ASSETS = {
    "BTC",
    "ETH",
    "SOL",
    "BNB",
    "XRP",
    "ADA",
    "DOGE",
    "LTC",
    "BCH",
    "TRX",
}


# ============================================================
# CACHE
# ============================================================

_market_cache = {}
_history_cache = {}

_cache_lock = Lock()


def _cache_get(cache, key, ttl):
    now = time.time()

    with _cache_lock:
        item = cache.get(key)

    if not item:
        return None

    timestamp, value = item

    if now - timestamp > ttl:
        return None

    return value


def _cache_set(cache, key, value):
    with _cache_lock:
        cache[key] = (time.time(), value)


# ============================================================
# GENERIC HELPERS
# ============================================================

def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def numeric(value, default=0.0):
    try:
        number = float(value)

        if not math.isfinite(number):
            return float(default)

        return number

    except (TypeError, ValueError):
        return float(default)


def clamp(value, low=0.0, high=100.0):
    return max(
        low,
        min(high, numeric(value)),
    )


def safe_divide(a, b, default=0.0):
    denominator = numeric(b)

    if denominator == 0:
        return default

    return numeric(a) / denominator


def percentage_change(current, previous):
    previous = numeric(previous)

    if previous == 0:
        return None

    return (
        (numeric(current) - previous)
        / abs(previous)
    ) * 100.0


def mean_or_zero(values):
    clean = [
        numeric(value)
        for value in values
        if value is not None
    ]

    return mean(clean) if clean else 0.0


def standard_deviation(values):
    clean = [
        numeric(value)
        for value in values
        if value is not None
    ]

    if len(clean) < 2:
        return 0.0

    avg = mean(clean)

    variance = sum(
        (value - avg) ** 2
        for value in clean
    ) / (len(clean) - 1)

    return math.sqrt(max(0.0, variance))


def covariance(x, y):
    if len(x) != len(y) or len(x) < 2:
        return 0.0

    avg_x = mean(x)
    avg_y = mean(y)

    return sum(
        (a - avg_x) * (b - avg_y)
        for a, b in zip(x, y)
    ) / (len(x) - 1)


def variance(values):
    if len(values) < 2:
        return 0.0

    avg = mean(values)

    return sum(
        (value - avg) ** 2
        for value in values
    ) / (len(values) - 1)


def calculate_returns(prices):
    prices = [
        numeric(price)
        for price in prices
        if numeric(price) > 0
    ]

    if len(prices) < 2:
        return []

    returns = []

    for previous, current in zip(
        prices,
        prices[1:],
    ):
        if previous <= 0:
            continue

        returns.append(
            math.log(current / previous)
        )

    return returns


def max_drawdown(prices):
    prices = [
        numeric(price)
        for price in prices
        if numeric(price) > 0
    ]

    if not prices:
        return 0.0

    peak = prices[0]
    worst = 0.0

    for price in prices:
        peak = max(peak, price)

        drawdown = (
            (price - peak)
            / peak
        ) * 100.0

        worst = min(
            worst,
            drawdown,
        )

    return worst


def classify_risk(score):
    score = clamp(score)

    if score >= 80:
        return "Critical"

    if score >= 65:
        return "High"

    if score >= 45:
        return "Moderate"

    if score >= 25:
        return "Low"

    return "Very Low"


def classify_change(delta):
    delta = numeric(delta)

    if delta >= 15:
        return "Major increase"

    if delta >= 5:
        return "Increasing"

    if delta <= -15:
        return "Major decrease"

    if delta <= -5:
        return "Decreasing"

    return "Stable"


# ============================================================
# MARKET DEFAULTS
# ============================================================

def empty_market_data(symbol):
    return {
        "ticker": symbol.upper(),
        "symbol": symbol.upper(),
        "asset_name": symbol.upper(),
        "coin_id": None,

        "current_price_usd": 0.0,
        "market_cap_usd": 0.0,
        "volume_24h_usd": 0.0,

        "price_change_1h_pct": 0.0,
        "price_change_24h_pct": 0.0,
        "price_change_7d_pct": 0.0,
        "price_change_30d_pct": 0.0,

        "high_24h_usd": 0.0,
        "low_24h_usd": 0.0,

        "market_data_available": False,

        "source": "unavailable",
        "timestamp": utc_now_iso(),

        "data_quality": {
            "status": "unavailable",
            "confidence": 0,
            "missing_fields": [
                "price",
                "volume",
                "market_cap",
                "history",
            ],
        },
    }


# ============================================================
# HTTP
# ============================================================

def http_get(url, params=None):
    response = requests.get(
        url,
        params=params,
        timeout=MARKET_TIMEOUT,
        headers={
            "Accept": "application/json",
            "User-Agent": "CryptoRiskAI/2.0",
        },
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# COINGECKO SEARCH
# ============================================================

def resolve_coin_id(symbol):
    symbol = symbol.upper().strip()

    if symbol in TOKEN_MAP:
        return TOKEN_MAP[symbol]

    try:
        data = http_get(
            f"{COINGECKO_API_URL}/search",
            params={
                "query": symbol,
            },
        )

        coins = data.get("coins", [])

        exact = [
            coin
            for coin in coins
            if str(
                coin.get("symbol", "")
            ).upper() == symbol
        ]

        if exact:
            return exact[0].get("id")

        if coins:
            return coins[0].get("id")

    except Exception:
        logger.exception(
            "CoinGecko symbol resolution failed for %s",
            symbol,
        )

    return None


# ============================================================
# COINGECKO MARKET DATA
# ============================================================

def fetch_coingecko_market(symbol):
    coin_id = resolve_coin_id(symbol)

    if not coin_id:
        return None

    data = http_get(
        f"{COINGECKO_API_URL}/coins/markets",
        params={
            "vs_currency": "usd",
            "ids": coin_id,
            "price_change_percentage": (
                "1h,24h,7d,30d"
            ),
        },
    )

    if not data:
        return None

    item = data[0]

    return {
        "ticker": symbol.upper(),
        "symbol": symbol.upper(),
        "asset_name": item.get(
            "name",
            symbol.upper(),
        ),
        "coin_id": coin_id,

        "current_price_usd": numeric(
            item.get("current_price")
        ),

        "market_cap_usd": numeric(
            item.get("market_cap")
        ),

        "volume_24h_usd": numeric(
            item.get("total_volume")
        ),

        "price_change_1h_pct": numeric(
            item.get(
                "price_change_percentage_1h_in_currency"
            )
        ),

        "price_change_24h_pct": numeric(
            item.get(
                "price_change_percentage_24h_in_currency"
            )
        ),

        "price_change_7d_pct": numeric(
            item.get(
                "price_change_percentage_7d_in_currency"
            )
        ),

        "price_change_30d_pct": numeric(
            item.get(
                "price_change_percentage_30d_in_currency"
            )
        ),

        "high_24h_usd": numeric(
            item.get("high_24h")
        ),

        "low_24h_usd": numeric(
            item.get("low_24h")
        ),

        "market_data_available": True,

        "source": "CoinGecko",
        "timestamp": utc_now_iso(),

        "data_quality": {
            "status": "live",
            "confidence": 92,
            "missing_fields": [],
        },
    }


# ============================================================
# BINANCE FALLBACK
# ============================================================

def fetch_binance_market(symbol):
    pair = f"{symbol.upper()}USDT"

    data = http_get(
        f"{BINANCE_API_URL}/ticker/24hr",
        params={
            "symbol": pair,
        },
    )

    return {
        "ticker": symbol.upper(),
        "symbol": symbol.upper(),
        "asset_name": symbol.upper(),
        "coin_id": None,

        "current_price_usd": numeric(
            data.get("lastPrice")
        ),

        "market_cap_usd": 0.0,

        "volume_24h_usd": numeric(
            data.get("quoteVolume")
        ),

        "price_change_1h_pct": 0.0,

        "price_change_24h_pct": numeric(
            data.get("priceChangePercent")
        ),

        # Deliberately NOT fabricated.
        "price_change_7d_pct": 0.0,
        "price_change_30d_pct": 0.0,

        "high_24h_usd": numeric(
            data.get("highPrice")
        ),

        "low_24h_usd": numeric(
            data.get("lowPrice")
        ),

        "market_data_available": True,

        "source": "Binance",
        "timestamp": utc_now_iso(),

        "data_quality": {
            "status": "partial",
            "confidence": 65,
            "missing_fields": [
                "market_cap",
                "1h_change",
                "7d_change",
                "30d_change",
            ],
        },
    }


# ============================================================
# MARKET DATA
# ============================================================

def fetch_market_data(symbol, force=False):
    symbol = symbol.upper().strip()

    cache_key = symbol

    if not force:
        cached = _cache_get(
            _market_cache,
            cache_key,
            MARKET_CACHE_TTL,
        )

        if cached:
            return cached

    market = None

    try:
        market = fetch_coingecko_market(symbol)

    except Exception as exc:
        logger.warning(
            "CoinGecko market request failed for %s: %s",
            symbol,
            exc,
        )

    if not market:
        try:
            market = fetch_binance_market(symbol)

        except Exception as exc:
            logger.warning(
                "Binance market request failed for %s: %s",
                symbol,
                exc,
            )

    if not market:
        market = empty_market_data(symbol)

    _cache_set(
        _market_cache,
        cache_key,
        market,
    )

    return market


# ============================================================
# HISTORICAL PRICE DATA
# ============================================================

def fetch_coingecko_history(symbol, days=30):
    coin_id = resolve_coin_id(symbol)

    if not coin_id:
        return []

    data = http_get(
        f"{COINGECKO_API_URL}/coins/{quote(coin_id)}"
        "/market_chart",
        params={
            "vs_currency": "usd",
            "days": days,
        },
    )

    prices = data.get("prices", [])

    return [
        {
            "timestamp": numeric(point[0]),
            "price": numeric(point[1]),
        }
        for point in prices
        if isinstance(point, list)
        and len(point) >= 2
        and numeric(point[1]) > 0
    ]


def fetch_binance_history(symbol, days=30):
    pair = f"{symbol.upper()}USDT"

    limit = min(
        1000,
        max(100, days * 24),
    )

    data = http_get(
        f"{BINANCE_API_URL}/klines",
        params={
            "symbol": pair,
            "interval": "1h",
            "limit": limit,
        },
    )

    return [
        {
            "timestamp": numeric(candle[0]),
            "price": numeric(candle[4]),
        }
        for candle in data
        if len(candle) >= 5
        and numeric(candle[4]) > 0
    ]


def fetch_price_history(symbol, days=30):
    symbol = symbol.upper().strip()

    cache_key = f"{symbol}:{days}"

    cached = _cache_get(
        _history_cache,
        cache_key,
        HISTORY_CACHE_TTL,
    )

    if cached:
        return cached

    history = []

    try:
        history = fetch_coingecko_history(
            symbol,
            days,
        )
    except Exception as exc:
        logger.warning(
            "CoinGecko history failed for %s: %s",
            symbol,
            exc,
        )

    if len(history) < 10:
        try:
            history = fetch_binance_history(
                symbol,
                days,
            )
        except Exception as exc:
            logger.warning(
                "Binance history failed for %s: %s",
                symbol,
                exc,
            )

    _cache_set(
        _history_cache,
        cache_key,
        history,
    )

    return history


# ============================================================
# QUANTITATIVE METRICS
# ============================================================

def realized_volatility(prices, annualization=365):
    returns = calculate_returns(prices)

    if len(returns) < 2:
        return {
            "daily_volatility_pct": None,
            "annualized_volatility_pct": None,
            "sample_size": len(returns),
        }

    daily = standard_deviation(returns) * 100

    annualized = (
        standard_deviation(returns)
        * math.sqrt(annualization)
        * 100
    )

    return {
        "daily_volatility_pct": daily,
        "annualized_volatility_pct": annualized,
        "sample_size": len(returns),
    }


def calculate_beta(asset_prices, btc_prices):
    asset_returns = calculate_returns(
        asset_prices
    )

    btc_returns = calculate_returns(
        btc_prices
    )

    length = min(
        len(asset_returns),
        len(btc_returns),
    )

    if length < 10:
        return {
            "beta": None,
            "correlation": None,
            "sample_size": length,
            "status": "insufficient_data",
        }

    asset_returns = asset_returns[-length:]
    btc_returns = btc_returns[-length:]

    btc_variance = variance(btc_returns)

    if btc_variance <= 0:
        return {
            "beta": None,
            "correlation": None,
            "sample_size": length,
            "status": "invalid_benchmark",
        }

    beta = covariance(
        asset_returns,
        btc_returns,
    ) / btc_variance

    asset_std = standard_deviation(
        asset_returns
    )

    btc_std = standard_deviation(
        btc_returns
    )

    if asset_std > 0 and btc_std > 0:
        correlation = covariance(
            asset_returns,
            btc_returns,
        ) / (
            asset_std * btc_std
        )
    else:
        correlation = None

    return {
        "beta": numeric(beta),
        "correlation": (
            numeric(correlation)
            if correlation is not None
            else None
        ),
        "sample_size": length,
        "status": "calculated",
    }


def calculate_liquidity_metrics(market):
    volume = numeric(
        market.get("volume_24h_usd")
    )

    market_cap = numeric(
        market.get("market_cap_usd")
    )

    turnover = (
        volume / market_cap
        if market_cap > 0
        else None
    )

    spread_range = None

    high = numeric(
        market.get("high_24h_usd")
    )

    low = numeric(
        market.get("low_24h_usd")
    )

    current = numeric(
        market.get("current_price_usd")
    )

    if current > 0 and high >= low > 0:
        spread_range = (
            (high - low)
            / current
        ) * 100

    return {
        "volume_24h_usd": volume,
        "market_cap_usd": market_cap,
        "turnover_ratio": turnover,
        "intraday_range_pct": spread_range,
    }


def calculate_quant_metrics(
    symbol,
    market,
    history,
    btc_history,
):
    prices = [
        item["price"]
        for item in history
        if item.get("price", 0) > 0
    ]

    btc_prices = [
        item["price"]
        for item in btc_history
        if item.get("price", 0) > 0
    ]

    volatility = realized_volatility(
        prices
    )

    beta = calculate_beta(
        prices,
        btc_prices,
    )

    liquidity = calculate_liquidity_metrics(
        market
    )

    current_price = numeric(
        market.get("current_price_usd")
    )

    first_price = (
        prices[0]
        if prices
        else current_price
    )

    thirty_day_change = percentage_change(
        current_price,
        first_price,
    )

    drawdown = max_drawdown(prices)

    return {
        "symbol": symbol.upper(),

        "price": {
            "current_usd": current_price,
            "change_24h_pct": numeric(
                market.get(
                    "price_change_24h_pct"
                )
            ),
            "change_7d_pct": numeric(
                market.get(
                    "price_change_7d_pct"
                )
            ),
            "change_30d_pct": (
                numeric(
                    market.get(
                        "price_change_30d_pct"
                    )
                )
                if market.get(
                    "price_change_30d_pct"
                )
                else numeric(
                    thirty_day_change
                )
            ),
        },

        "volatility": volatility,

        "beta": beta,

        "liquidity": liquidity,

        "drawdown": {
            "maximum_30d_pct": drawdown,
        },

        "history": {
            "asset_observations": len(prices),
            "btc_observations": len(btc_prices),
            "window_days": 30,
        },
    }

# ============================================================
# CryptoRisk AI — Backend v2
# PART 2 / 3
# ============================================================


# ============================================================
# RISK ENGINE
# ============================================================

def volatility_risk_score(quant):
    volatility = quant.get("volatility", {})

    annualized = volatility.get(
        "annualized_volatility_pct"
    )

    daily = volatility.get(
        "daily_volatility_pct"
    )

    change_7d = abs(
        numeric(
            quant.get("price", {})
            .get("change_7d_pct")
        )
    )

    drawdown = abs(
        numeric(
            quant.get("drawdown", {})
            .get("maximum_30d_pct")
        )
    )

    components = []

    if annualized is not None:
        # Broad risk curve rather than arbitrary
        # single-threshold classification.
        vol_score = min(
            100,
            (annualized / 150.0) * 100.0,
        )
        components.append(vol_score)

    if daily is not None:
        daily_score = min(
            100,
            (daily / 10.0) * 100.0,
        )
        components.append(daily_score)

    if change_7d:
        momentum_score = min(
            100,
            (change_7d / 40.0) * 100.0,
        )
        components.append(momentum_score)

    if drawdown:
        drawdown_score = min(
            100,
            (drawdown / 50.0) * 100.0,
        )
        components.append(drawdown_score)

    if not components:
        return {
            "score": 60,
            "confidence": 15,
            "status": "insufficient_data",
        }

    score = mean(components)

    return {
        "score": round(clamp(score), 2),
        "confidence": min(
            95,
            50 + len(components) * 10,
        ),
        "status": "calculated",
    }


def liquidity_risk_score(quant):
    liquidity = quant.get(
        "liquidity",
        {},
    )

    turnover = liquidity.get(
        "turnover_ratio"
    )

    volume = numeric(
        liquidity.get(
            "volume_24h_usd"
        )
    )

    market_cap = numeric(
        liquidity.get(
            "market_cap_usd"
        )
    )

    if turnover is None:
        if volume > 1_000_000_000:
            score = 20
            confidence = 45

        elif volume > 100_000_000:
            score = 35
            confidence = 40

        elif volume > 10_000_000:
            score = 55
            confidence = 35

        elif volume > 0:
            score = 75
            confidence = 30

        else:
            score = 70
            confidence = 10

        return {
            "score": score,
            "confidence": confidence,
            "status": (
                "partial"
                if volume > 0
                else "insufficient_data"
            ),
        }

    # Higher turnover generally means greater
    # ability to transact relative to capitalization.
    if turnover >= 0.20:
        score = 15
    elif turnover >= 0.10:
        score = 25
    elif turnover >= 0.05:
        score = 35
    elif turnover >= 0.02:
        score = 50
    elif turnover >= 0.01:
        score = 65
    else:
        score = 82

    # Very small absolute volume adds exit risk.
    if volume < 1_000_000:
        score += 15
    elif volume < 10_000_000:
        score += 8

    return {
        "score": round(
            clamp(score)
        ),
        "confidence": 70,
        "status": "calculated",
    }


def market_sensitivity_score(quant):
    beta = quant.get(
        "beta",
        {}
    ).get("beta")

    correlation = quant.get(
        "beta",
        {}
    ).get("correlation")

    if beta is None:
        return {
            "score": 55,
            "confidence": 10,
            "status": "insufficient_data",
        }

    beta_score = min(
        100,
        max(
            0,
            abs(beta) / 2.5 * 100,
        ),
    )

    if correlation is not None:
        correlation_penalty = (
            abs(correlation) * 15
        )
    else:
        correlation_penalty = 0

    score = min(
        100,
        beta_score * 0.85
        + correlation_penalty,
    )

    return {
        "score": round(score, 2),
        "confidence": 80,
        "status": "calculated",
    }


def structural_risk_score(
    symbol,
    security,
):
    # Native assets don't have token-contract
    # privileges in the same way as ERC-20 style tokens.
    if symbol.upper() in NATIVE_ASSETS:
        return {
            "score": 10,
            "confidence": 85,
            "status": "native_asset",
        }

    if not security:
        return {
            "score": None,
            "confidence": 0,
            "status": "unavailable",
        }

    score = 20

    red_flags = security.get(
        "red_flags",
        []
    )

    score += min(
        70,
        len(red_flags) * 12,
    )

    if security.get(
        "honeypot",
        False
    ):
        score = 100

    if security.get(
        "buy_tax_pct",
        0
    ) > 5:
        score += 10

    if security.get(
        "sell_tax_pct",
        0
    ) > 5:
        score += 10

    return {
        "score": round(
            clamp(score)
        ),
        "confidence": numeric(
            security.get(
                "confidence",
                50
            )
        ),
        "status": "calculated",
    }


def composite_risk_score(
    volatility,
    liquidity,
    sensitivity,
    structural,
):
    components = [
        (
            volatility,
            0.35,
        ),
        (
            liquidity,
            0.30,
        ),
        (
            sensitivity,
            0.20,
        ),
        (
            structural,
            0.15,
        ),
    ]

    available = [
        (
            score,
            weight,
        )
        for score, weight in components
        if score is not None
    ]

    if not available:
        return {
            "score": 60,
            "confidence": 5,
            "status": "unavailable",
        }

    weight_sum = sum(
        weight
        for _, weight in available
    )

    score = sum(
        numeric(score) * weight
        for score, weight in available
    ) / weight_sum

    confidence = min(
        95,
        sum(
            20
            for _, _ in available
        )
        + 10,
    )

    return {
        "score": round(
            clamp(score),
            2,
        ),
        "confidence": confidence,
        "status": "calculated",
    }


def build_risk_profile(
    symbol,
    quant,
    security,
):
    volatility = volatility_risk_score(
        quant
    )

    liquidity = liquidity_risk_score(
        quant
    )

    sensitivity = market_sensitivity_score(
        quant
    )

    structural = structural_risk_score(
        symbol,
        security,
    )

    composite = composite_risk_score(
        volatility["score"],
        liquidity["score"],
        sensitivity["score"],
        structural.get("score"),
    )

    return {
        "volatility": volatility,
        "liquidity": liquidity,
        "market_sensitivity": sensitivity,
        "structural": structural,
        "composite": composite,

        "overall_score": composite[
            "score"
        ],

        "severity": classify_risk(
            composite["score"]
        ),

        "confidence": composite[
            "confidence"
        ],
    }


# ============================================================
# SECURITY INTELLIGENCE
# ============================================================

def goplus_bool(value):
    return str(value).lower() in {
        "1",
        "true",
        "yes",
    }


def goplus_number(value):
    return numeric(
        value,
        default=0,
    )


def fetch_token_security(
    chain_id,
    contract_address,
):
    if not chain_id or not contract_address:
        return {}

    if not re.fullmatch(
        r"0x[a-fA-F0-9]{40}",
        contract_address,
    ):
        return {
            "status": "invalid_contract",
            "confidence": 0,
            "red_flags": [],
        }

    try:
        data = http_get(
            f"{GOPLUS_API_URL}/{quote(str(chain_id))}",
            params={
                "contract_addresses": contract_address,
            },
        )

        result = data.get(
            "result",
            {},
        )

        item = result.get(
            contract_address.lower()
        )

        if not item:
            # GoPlus can sometimes preserve
            # checksum casing.
            item = result.get(
                contract_address
            )

        if not item:
            return {
                "status": "unavailable",
                "confidence": 0,
                "red_flags": [],
            }

        red_flags = []

        if goplus_bool(
            item.get("is_honeypot")
        ):
            red_flags.append(
                "Potential honeypot signal"
            )

        if goplus_bool(
            item.get("is_open_source")
        ) is False:
            red_flags.append(
                "Contract source is not verified"
            )

        if goplus_bool(
            item.get("can_take_back_ownership")
        ):
            red_flags.append(
                "Ownership may be recoverable"
            )

        if goplus_bool(
            item.get("owner_change_balance")
        ):
            red_flags.append(
                "Owner may alter balances"
            )

        if goplus_bool(
            item.get("is_blacklisted")
        ):
            red_flags.append(
                "Blacklist mechanism detected"
            )

        buy_tax = goplus_number(
            item.get("buy_tax")
        ) * 100

        sell_tax = goplus_number(
            item.get("sell_tax")
        ) * 100

        if buy_tax > 5:
            red_flags.append(
                f"Buy tax reported at {buy_tax:.2f}%"
            )

        if sell_tax > 5:
            red_flags.append(
                f"Sell tax reported at {sell_tax:.2f}%"
            )

        confidence = 80

        if not item.get("is_open_source"):
            confidence -= 10

        return {
            "status": "available",
            "confidence": max(
                0,
                confidence,
            ),

            "is_open_source": (
                goplus_bool(
                    item.get(
                        "is_open_source"
                    )
                )
            ),

            "honeypot": (
                goplus_bool(
                    item.get(
                        "is_honeypot"
                    )
                )
            ),

            "buy_tax_pct": buy_tax,
            "sell_tax_pct": sell_tax,

            "owner_can_take_back": (
                goplus_bool(
                    item.get(
                        "can_take_back_ownership"
                    )
                )
            ),

            "blacklist_detected": (
                goplus_bool(
                    item.get(
                        "is_blacklisted"
                    )
                )
            ),

            "red_flags": red_flags,

            "source": "GoPlus",
            "timestamp": utc_now_iso(),
        }

    except Exception as exc:
        logger.warning(
            "GoPlus request failed: %s",
            exc,
        )

        return {
            "status": "unavailable",
            "confidence": 0,
            "red_flags": [],
            "source": "GoPlus",
            "timestamp": utc_now_iso(),
        }


# ============================================================
# BTC STRESS ENGINE
# ============================================================

def stress_scenario(
    beta,
    shock_pct,
    volatility_pct,
    liquidity_score,
):
    beta = numeric(beta, 1.0)

    if beta <= 0:
        beta = 1.0

    raw_move = shock_pct * beta

    # Higher volatility increases uncertainty around
    # the central beta estimate.
    uncertainty = (
        abs(shock_pct)
        * min(
            0.35,
            numeric(
                volatility_pct
            ) / 300.0,
        )
    )

    # Higher liquidity risk widens the downside range.
    liquidity_adjustment = (
        abs(shock_pct)
        * (
            clamp(
                liquidity_score
            ) / 100.0
        )
        * 0.20
    )

    total_uncertainty = (
        uncertainty
        + liquidity_adjustment
    )

    lower = (
        raw_move
        - total_uncertainty
    )

    upper = (
        raw_move
        + total_uncertainty
    )

    return {
        "shock_pct": shock_pct,
        "central_estimate_pct": round(
            raw_move,
            2,
        ),
        "range_low_pct": round(
            lower,
            2,
        ),
        "range_high_pct": round(
            upper,
            2,
        ),
    }


def build_stress_test(
    quant,
    risk_profile,
):
    beta = quant.get(
        "beta",
        {}
    ).get(
        "beta"
    )

    volatility = quant.get(
        "volatility",
        {}
    ).get(
        "annualized_volatility_pct"
    )

    liquidity_score = risk_profile[
        "liquidity"
    ]["score"]

    if beta is None:
        beta = 1.0

    scenarios = [
        stress_scenario(
            beta,
            -5,
            volatility or 0,
            liquidity_score,
        ),

        stress_scenario(
            beta,
            -10,
            volatility or 0,
            liquidity_score,
        ),

        stress_scenario(
            beta,
            -20,
            volatility or 0,
            liquidity_score,
        ),

        stress_scenario(
            beta,
            -30,
            volatility or 0,
            liquidity_score,
        ),
    ]

    ten_percent = scenarios[1]

    if abs(
        ten_percent[
            "central_estimate_pct"
        ]
    ) >= 20:
        resilience = "Low"

    elif abs(
        ten_percent[
            "central_estimate_pct"
        ]
    ) >= 12:
        resilience = "Moderate"

    else:
        resilience = "Higher"

    return {
        "benchmark": "BTC",
        "method": (
            "Historical beta with volatility "
            "and liquidity uncertainty adjustment."
        ),

        "beta": round(
            numeric(beta),
            4,
        ),

        "resilience_label": resilience,

        "scenarios": scenarios,

        "expected_drawdown_pct": (
            ten_percent[
                "central_estimate_pct"
            ]
        ),

        "confidence": (
            75
            if quant.get(
                "beta",
                {}
            ).get(
                "status"
            ) == "calculated"
            else 15
        ),
    }


# ============================================================
# RISK CHANGE DETECTION
# ============================================================

def detect_risk_drivers(
    quant,
    risk_profile,
):
    drivers = []

    volatility_score = numeric(
        risk_profile[
            "volatility"
        ]["score"]
    )

    liquidity_score = numeric(
        risk_profile[
            "liquidity"
        ]["score"]
    )

    sensitivity_score = numeric(
        risk_profile[
            "market_sensitivity"
        ]["score"]
    )

    structural_score = (
        risk_profile[
            "structural"
        ].get("score")
    )

    if volatility_score >= 70:
        drivers.append({
            "type": "risk",
            "severity": "high",
            "title": "Elevated volatility",
            "detail": (
                "Realized volatility is elevated "
                "relative to the model's risk bands."
            ),
        })

    if liquidity_score >= 65:
        drivers.append({
            "type": "risk",
            "severity": "high",
            "title": "Liquidity pressure",
            "detail": (
                "Observed turnover and available "
                "market activity indicate higher exit risk."
            ),
        })

    if sensitivity_score >= 70:
        drivers.append({
            "type": "risk",
            "severity": "medium",
            "title": "High market sensitivity",
            "detail": (
                "Historical returns show substantial "
                "sensitivity to BTC market movements."
            ),
        })

    if (
        structural_score is not None
        and structural_score >= 65
    ):
        drivers.append({
            "type": "risk",
            "severity": "high",
            "title": "Structural red flags",
            "detail": (
                "Available contract-security evidence "
                "contains elevated structural risk signals."
            ),
        })

    if not drivers:
        drivers.append({
            "type": "neutral",
            "severity": "low",
            "title": "No dominant risk driver",
            "detail": (
                "No single monitored risk pillar "
                "currently dominates the model."
            ),
        })

    return drivers


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
):
    evidence = []

    evidence.append({
        "category": "market",
        "claim": (
            f"{symbol.upper()} is trading at "
            f"${numeric(market.get('current_price_usd')):,.6g}."
        ),
        "value": numeric(
            market.get(
                "current_price_usd"
            )
        ),
        "source": market.get(
            "source",
            "unknown",
        ),
        "timestamp": market.get(
            "timestamp"
        ),
        "confidence": market.get(
            "data_quality",
            {},
        ).get(
            "confidence",
            0,
        ),
    })

    volatility = quant.get(
        "volatility",
        {},
    )

    evidence.append({
        "category": "volatility",
        "claim": (
            "Realized volatility was calculated "
            "from historical price observations."
        ),
        "value": volatility.get(
            "annualized_volatility_pct"
        ),
        "unit": "%",
        "source": "Historical market prices",
        "timestamp": utc_now_iso(),
        "confidence": risk_profile[
            "volatility"
        ]["confidence"],
    })

    evidence.append({
        "category": "liquidity",
        "claim": (
            "Liquidity risk is based primarily on "
            "24H turnover relative to market capitalization."
        ),
        "value": risk_profile[
            "liquidity"
        ]["score"],
        "unit": "risk_score",
        "source": market.get(
            "source",
            "unknown",
        ),
        "timestamp": market.get(
            "timestamp"
        ),
        "confidence": risk_profile[
            "liquidity"
        ]["confidence"],
    })

    evidence.append({
        "category": "beta",
        "claim": (
            "Market sensitivity is estimated from "
            "historical asset and BTC returns."
        ),
        "value": quant.get(
            "beta",
            {},
        ).get(
            "beta"
        ),
        "unit": "beta",
        "source": "Historical market prices",
        "timestamp": utc_now_iso(),
        "confidence": risk_profile[
            "market_sensitivity"
        ]["confidence"],
    })

    if security:
        evidence.append({
            "category": "security",
            "claim": (
                "Contract-security signals were retrieved "
                "from the available security provider."
            ),
            "value": security,
            "source": security.get(
                "source",
                "unknown",
            ),
            "timestamp": security.get(
                "timestamp"
            ),
            "confidence": security.get(
                "confidence",
                0,
            ),
        })

    evidence.append({
        "category": "stress",
        "claim": (
            "BTC shock scenarios use historical beta "
            "plus uncertainty adjustments."
        ),
        "value": stress,
        "source": "CryptoRisk quantitative engine",
        "timestamp": utc_now_iso(),
        "confidence": stress.get(
            "confidence",
            0,
        ),
    })

    return evidence


# ============================================================
# GEMINI PROMPT
# ============================================================

def build_gemini_prompt(
    symbol,
    market,
    quant,
    risk_profile,
    stress,
    evidence,
):
    return f"""
You are the interpretation layer of CryptoRisk AI.

You are NOT the quantitative calculator.

The backend has already calculated all numerical values.
You MUST NOT invent prices, percentages, beta values,
security findings, news, events, or market facts.

Your job is to interpret the supplied evidence into
clear, concise cryptocurrency risk intelligence.

Asset:
{symbol.upper()}

MARKET DATA:
{json.dumps(market, indent=2)}

QUANTITATIVE DATA:
{json.dumps(quant, indent=2)}

RISK PROFILE:
{json.dumps(risk_profile, indent=2)}

STRESS TEST:
{json.dumps(stress, indent=2)}

EVIDENCE:
{json.dumps(evidence, indent=2)}

Return ONLY valid JSON.

Required schema:

{{
  "executive_summary": "string",
  "risk_regime": "string",
  "primary_risk_driver": "string",
  "secondary_risk_drivers": ["string"],
  "what_changed": ["string"],
  "what_matters_now": ["string"],
  "watch_next": ["string"],
  "risk_mitigating_factors": ["string"],
  "red_flags": ["string"],
  "bull_case": "string",
  "base_case": "string",
  "bear_case": "string",
  "stress_interpretation": "string",
  "data_quality_note": "string",
  "confidence": 0
}}

Rules:

1. Never claim certainty about future prices.
2. Never create unsupported facts.
3. Never say something was detected if the evidence does not
   show it.
4. Distinguish unavailable information from safe information.
5. Mention important missing data when relevant.
6. Keep the writing analyst-like and decision-relevant.
7. Do not provide personalized financial advice.
8. Do not tell the user to buy or sell.
9. Every important numerical statement must correspond
   to supplied evidence.
10. If contract data is unavailable, explicitly say that
    structural security evidence is unavailable.
"""


# ============================================================
# GEMINI
# ============================================================

def fallback_ai_report(
    symbol,
    risk_profile,
    stress,
):
    severity = risk_profile[
        "severity"
    ]

    score = risk_profile[
        "overall_score"
    ]

    return {
        "executive_summary": (
            f"{symbol.upper()} currently has a "
            f"{severity.lower()} quantitative risk profile "
            f"with a composite score of {score:.0f}/100."
        ),

        "risk_regime": severity,

        "primary_risk_driver": (
            "Volatility and market/liquidity conditions "
            "should be monitored."
        ),

        "secondary_risk_drivers": [],

        "what_changed": [],

        "what_matters_now": [
            "Monitor volatility.",
            "Monitor liquidity conditions.",
            "Monitor BTC sensitivity.",
        ],

        "watch_next": [
            "Realized volatility",
            "Trading activity",
            "BTC correlation",
        ],

        "risk_mitigating_factors": [],

        "red_flags": [],

        "bull_case": (
            "Risk conditions could improve if volatility "
            "compresses and liquidity remains healthy."
        ),

        "base_case": (
            "The current quantitative risk regime persists "
            "until the monitored metrics materially change."
        ),

        "bear_case": (
            "A broader market selloff combined with weaker "
            "liquidity could increase downside risk."
        ),

        "stress_interpretation": (
            f"A BTC -10% scenario produces a modeled central "
            f"asset move of "
            f"{stress.get('expected_drawdown_pct', 0):.2f}%."
        ),

        "data_quality_note": (
            "This interpretation is based on the available "
            "quantitative evidence."
        ),

        "confidence": 55,
    }


def run_gemini_interpretation(
    symbol,
    market,
    quant,
    risk_profile,
    stress,
    evidence,
):
    fallback = fallback_ai_report(
        symbol,
        risk_profile,
        stress,
    )

    if not gemini_client:
        return fallback

    prompt = build_gemini_prompt(
        symbol,
        market,
        quant,
        risk_profile,
        stress,
        evidence,
    )

    try:
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )

        text = (
            getattr(
                response,
                "text",
                "",
            )
            or ""
        ).strip()

        if not text:
            return fallback

        # Remove markdown fences if Gemini returns them.
        text = re.sub(
            r"^```json\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )

        text = re.sub(
            r"^```\s*",
            "",
            text,
        )

        text = re.sub(
            r"\s*```$",
            "",
            text,
        )

        parsed = json.loads(
            text.strip()
        )

        if not isinstance(parsed, dict):
            return fallback

        # Preserve the backend's numerical truth.
        parsed["confidence"] = clamp(
            parsed.get(
                "confidence",
                55,
            )
        )

        return parsed

    except Exception:
        logger.exception(
            "Gemini interpretation failed."
        )

        return fallback


# ============================================================
# REPORT BUILDER
# ============================================================

def build_structured_report(
    symbol,
    market,
    quant,
    risk_profile,
    stress,
    security,
    evidence,
    ai_report,
):
    drivers = detect_risk_drivers(
        quant,
        risk_profile,
    )

    return {
        "schema_version": "2.0",

        "report_id": str(
            uuid.uuid4()
        ),

        "asset": {
            "symbol": symbol.upper(),
            "name": market.get(
                "asset_name",
                symbol.upper(),
            ),
        },

        "generated_at": utc_now_iso(),

        "market": market,

        "quantitative": quant,

        "risk_profile": {
            "overall_score": risk_profile[
                "overall_score"
            ],
            "severity": risk_profile[
                "severity"
            ],
            "confidence": risk_profile[
                "confidence"
            ],

            "pillars": {
                "volatility": risk_profile[
                    "volatility"
                ],

                "liquidity": risk_profile[
                    "liquidity"
                ],

                "market_sensitivity": risk_profile[
                    "market_sensitivity"
                ],

                "structural": risk_profile[
                    "structural"
                ],
            },
        },

        "risk_drivers": drivers,

        "stress_test": stress,

        "security": security or {
            "status": "unavailable",
            "confidence": 0,
            "red_flags": [],
        },

        "evidence": evidence,

        "ai": ai_report,

        "data_quality": market.get(
            "data_quality",
            {
                "status": "unknown",
                "confidence": 0,
            },
        ),
    }


# ============================================================
# COMPLETE ANALYSIS PIPELINE
# ============================================================

def run_analysis(
    symbol,
    chain_id=None,
    contract_address=None,
    force_market_refresh=False,
):
    symbol = symbol.upper().strip()

    market = fetch_market_data(
        symbol,
        force=force_market_refresh,
    )

    history = fetch_price_history(
        symbol,
        days=30,
    )

    btc_history = fetch_price_history(
        "BTC",
        days=30,
    )

    quant = calculate_quant_metrics(
        symbol,
        market,
        history,
        btc_history,
    )

    security = {}

    if chain_id and contract_address:
        security = fetch_token_security(
            chain_id,
            contract_address,
        )

    risk_profile = build_risk_profile(
        symbol,
        quant,
        security,
    )

    stress = build_stress_test(
        quant,
        risk_profile,
    )

    # Evidence is constructed BEFORE Gemini.
    evidence = build_evidence_pack(
        symbol,
        market,
        quant,
        risk_profile,
        stress,
        security,
    )

    ai_report = run_gemini_interpretation(
        symbol,
        market,
        quant,
        risk_profile,
        stress,
        evidence,
    )

    report = build_structured_report(
        symbol,
        market,
        quant,
        risk_profile,
        stress,
        security,
        evidence,
        ai_report,
    )

    return report
# ============================================================
# CryptoRisk AI — Backend v2
# PART 3 / 3
# ============================================================


# ============================================================
# DATABASE
# ============================================================

def get_db_connection():
    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require",
    )


def init_db():
    connection = get_db_connection()

    try:
        cursor = connection.cursor()

        # ONE analysis table.
        #
        # This replaces the old conflict where the application
        # created "analyses" but queried "predictions".
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT,
                google_id TEXT UNIQUE,
                avatar_url TEXT,
                created_at TIMESTAMPTZ
                    DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ
                    DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS analyses (
                id SERIAL PRIMARY KEY,

                user_id INTEGER NOT NULL
                    REFERENCES users(id)
                    ON DELETE CASCADE,

                token_symbol VARCHAR(20) NOT NULL,

                chain_id TEXT,
                contract_address TEXT,

                risk_score DOUBLE PRECISION,
                risk_severity TEXT,

                report JSONB NOT NULL,

                created_at TIMESTAMPTZ
                    DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_analyses_user_created
            ON analyses(user_id, created_at DESC);
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_analyses_token
            ON analyses(token_symbol);
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS
            idx_users_google_id
            ON users(google_id);
            """
        )

        connection.commit()

    finally:
        connection.close()


def row_to_user(row):
    if not row:
        return None

    return {
        "id": row[0],
        "username": row[1],
        "email": row[2],
        "google_id": row[3],
        "avatar_url": row[4],
        "created_at": (
            row[5].isoformat()
            if row[5]
            else None
        ),
    }


def get_user_by_id(user_id):
    connection = get_db_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                id,
                username,
                email,
                google_id,
                avatar_url,
                created_at
            FROM users
            WHERE id = %s
            """,
            (user_id,),
        )

        return row_to_user(
            cursor.fetchone()
        )

    finally:
        connection.close()


def get_user_by_email(email):
    connection = get_db_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                id,
                username,
                email,
                google_id,
                avatar_url,
                created_at
            FROM users
            WHERE LOWER(email) = LOWER(%s)
            """,
            (email,),
        )

        return row_to_user(
            cursor.fetchone()
        )

    finally:
        connection.close()


def create_local_user(
    username,
    email,
    password,
):
    password_hash = bcrypt.generate_password_hash(
        password
    ).decode("utf-8")

    connection = get_db_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            INSERT INTO users (
                username,
                email,
                password_hash
            )
            VALUES (%s, %s, %s)
            RETURNING
                id,
                username,
                email,
                google_id,
                avatar_url,
                created_at
            """,
            (
                username,
                email.lower(),
                password_hash,
            ),
        )

        row = cursor.fetchone()

        connection.commit()

        return row_to_user(row)

    finally:
        connection.close()


def create_or_update_google_user(
    email,
    name,
    google_id,
    avatar_url=None,
):
    connection = get_db_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT id
            FROM users
            WHERE google_id = %s
               OR LOWER(email) = LOWER(%s)
            LIMIT 1
            """,
            (
                google_id,
                email,
            ),
        )

        existing = cursor.fetchone()

        if existing:
            user_id = existing[0]

            cursor.execute(
                """
                UPDATE users
                SET
                    username = %s,
                    email = %s,
                    google_id = %s,
                    avatar_url = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (
                    name or "Google User",
                    email.lower(),
                    google_id,
                    avatar_url,
                    user_id,
                ),
            )

        else:
            cursor.execute(
                """
                INSERT INTO users (
                    username,
                    email,
                    google_id,
                    avatar_url
                )
                VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (
                    name or "Google User",
                    email.lower(),
                    google_id,
                    avatar_url,
                ),
            )

            user_id = cursor.fetchone()[0]

        connection.commit()

        return get_user_by_id(
            user_id
        )

    finally:
        connection.close()


def save_analysis(
    user_id,
    report,
    chain_id=None,
    contract_address=None,
):
    connection = get_db_connection()

    try:
        cursor = connection.cursor()

        risk = report.get(
            "risk_profile",
            {},
        )

        cursor.execute(
            """
            INSERT INTO analyses (
                user_id,
                token_symbol,
                chain_id,
                contract_address,
                risk_score,
                risk_severity,
                report
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s::jsonb
            )
            RETURNING id, created_at
            """,
            (
                user_id,

                report.get(
                    "asset",
                    {},
                ).get(
                    "symbol",
                    "",
                ),

                chain_id,
                contract_address,

                numeric(
                    risk.get(
                        "overall_score"
                    )
                ),

                risk.get(
                    "severity",
                    "Unknown",
                ),

                json.dumps(report),
            ),
        )

        row = cursor.fetchone()

        connection.commit()

        return {
            "id": row[0],
            "created_at": (
                row[1].isoformat()
                if row[1]
                else None
            ),
        }

    finally:
        connection.close()


def get_analysis_by_id(
    user_id,
    report_id,
):
    connection = get_db_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                id,
                token_symbol,
                risk_score,
                risk_severity,
                report,
                created_at
            FROM analyses
            WHERE id = %s
              AND user_id = %s
            """,
            (
                report_id,
                user_id,
            ),
        )

        row = cursor.fetchone()

        if not row:
            return None

        return {
            "id": row[0],
            "token_symbol": row[1],
            "risk_score": row[2],
            "risk_severity": row[3],
            "report": row[4],
            "created_at": (
                row[5].isoformat()
                if row[5]
                else None
            ),
        }

    finally:
        connection.close()


def get_user_history(
    user_id,
    limit=50,
):
    connection = get_db_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                id,
                token_symbol,
                risk_score,
                risk_severity,
                report,
                created_at
            FROM analyses
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (
                user_id,
                limit,
            ),
        )

        rows = cursor.fetchall()

        history = []

        for row in rows:
            report = row[4] or {}

            history.append({
                "id": row[0],
                "token_symbol": row[1],
                "risk_score": (
                    row[2]
                    if row[2] is not None
                    else report.get(
                        "risk_profile",
                        {},
                    ).get(
                        "overall_score"
                    )
                ),
                "risk_severity": row[3],
                "trend": report.get(
                    "ai",
                    {},
                ).get(
                    "risk_regime"
                ),
                "current_price": report.get(
                    "market",
                    {},
                ).get(
                    "current_price_usd"
                ),
                "created_at": (
                    row[5].isoformat()
                    if row[5]
                    else None
                ),
            })

        return history

    finally:
        connection.close()


def delete_analysis(
    user_id,
    report_id,
):
    connection = get_db_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            DELETE FROM analyses
            WHERE id = %s
              AND user_id = %s
            """,
            (
                report_id,
                user_id,
            ),
        )

        deleted = cursor.rowcount > 0

        connection.commit()

        return deleted

    finally:
        connection.close()


def delete_all_analyses(user_id):
    connection = get_db_connection()

    try:
        cursor = connection.cursor()

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
        connection.close()


# ============================================================
# INITIALIZE DATABASE
# ============================================================

try:
    init_db()
except Exception:
    logger.exception(
        "Database initialization failed."
    )


# ============================================================
# AUTH HELPERS
# ============================================================

def current_user():
    try:
        identity = get_jwt_identity()

        if identity is None:
            return None

        return get_user_by_id(
            int(identity)
        )

    except Exception:
        return None


def login_required_api(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        user = current_user()

        if not user:
            return jsonify({
                "success": False,
                "message": "Authentication required.",
            }), 401

        return fn(*args, **kwargs)

    return wrapper


# ============================================================
# REQUEST ID
# ============================================================

@app.before_request
def attach_request_id():
    request.request_id = request.headers.get(
        "X-Request-ID"
    ) or str(
        uuid.uuid4()
    )


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():
    db_ok = False

    try:
        connection = get_db_connection()

        try:
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            db_ok = True

        finally:
            connection.close()

    except Exception:
        logger.exception(
            "Health database check failed."
        )

    return jsonify({
        "success": True,
        "service": "CryptoRisk AI",
        "version": "2.0",
        "status": (
            "healthy"
            if db_ok
            else "degraded"
        ),
        "database": db_ok,
        "timestamp": utc_now_iso(),
        "request_id": request.request_id,
    })


# ============================================================
# LANDING PAGE
# ============================================================

@app.get("/")
def home():
    return render_template(
        "index.html"
    )


# ============================================================
# DASHBOARD PAGE
# ============================================================

@app.get("/dashboard")
def dashboard_page():
    return render_template(
        "dashboard.html"
    )


# ============================================================
# LOCAL SIGNUP
# ============================================================

@app.post("/api/auth/signup")
def signup():
    data = request.get_json(
        silent=True
    ) or {}

    username = str(
        data.get(
            "username",
            "",
        )
    ).strip()

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

    if not username:
        return jsonify({
            "success": False,
            "message": "Username is required.",
        }), 400

    if not re.fullmatch(
        r"[^@\s]+@[^@\s]+\.[^@\s]+",
        email,
    ):
        return jsonify({
            "success": False,
            "message": "Enter a valid email.",
        }), 400

    if len(password) < 8:
        return jsonify({
            "success": False,
            "message": (
                "Password must contain at least "
                "8 characters."
            ),
        }), 400

    if get_user_by_email(email):
        return jsonify({
            "success": False,
            "message": "An account already exists.",
        }), 409

    try:
        user = create_local_user(
            username,
            email,
            password,
        )

        token = create_access_token(
            identity=str(
                user["id"]
            )
        )

        return jsonify({
            "success": True,
            "token": token,
            "user": user,
        }), 201

    except psycopg2.errors.UniqueViolation:
        return jsonify({
            "success": False,
            "message": "An account already exists.",
        }), 409

    except Exception:
        logger.exception(
            "Signup failed."
        )

        return jsonify({
            "success": False,
            "message": "Unable to create account.",
        }), 500


# ============================================================
# LOCAL LOGIN
# ============================================================

@app.post("/api/auth/login")
def login():
    data = request.get_json(
        silent=True
    ) or {}

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
            "message": "Email and password are required.",
        }), 400

    connection = get_db_connection()

    try:
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                id,
                username,
                email,
                password_hash,
                google_id,
                avatar_url,
                created_at
            FROM users
            WHERE LOWER(email) = LOWER(%s)
            """,
            (email,),
        )

        row = cursor.fetchone()

    finally:
        connection.close()

    if not row:
        return jsonify({
            "success": False,
            "message": "Invalid email or password.",
        }), 401

    password_hash = row[3]

    if not password_hash:
        return jsonify({
            "success": False,
            "message": (
                "This account uses Google sign-in."
            ),
        }), 401

    if not bcrypt.check_password_hash(
        password_hash,
        password,
    ):
        return jsonify({
            "success": False,
            "message": "Invalid email or password.",
        }), 401

    user = {
        "id": row[0],
        "username": row[1],
        "email": row[2],
        "google_id": row[4],
        "avatar_url": row[5],
        "created_at": (
            row[6].isoformat()
            if row[6]
            else None
        ),
    }

    token = create_access_token(
        identity=str(
            user["id"]
        )
    )

    return jsonify({
        "success": True,
        "token": token,
        "user": user,
    })


# ============================================================
# GOOGLE LOGIN
# ============================================================

@app.get("/api/auth/google")
def google_login():
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return jsonify({
            "success": False,
            "message": (
                "Google OAuth is not configured."
            ),
        }), 503

    redirect_uri = url_for(
        "google_callback",
        _external=True,
    )

    return oauth.google.authorize_redirect(
        redirect_uri
    )


# ============================================================
# GOOGLE CALLBACK
# ============================================================

@app.get("/api/auth/google/callback")
def google_callback():
    try:
        token_data = (
            oauth.google.authorize_access_token()
        )

        user_info = (
            token_data.get(
                "userinfo"
            )
            or {}
        )

        email = user_info.get(
            "email"
        )

        google_id = user_info.get(
            "sub"
        )

        name = (
            user_info.get(
                "name"
            )
            or "Google User"
        )

        avatar = user_info.get(
            "picture"
        )

        if not email or not google_id:
            return jsonify({
                "success": False,
                "message": (
                    "Google did not return "
                    "required account information."
                ),
            }), 400

        user = create_or_update_google_user(
            email=email,
            name=name,
            google_id=google_id,
            avatar_url=avatar,
        )

        jwt_token = create_access_token(
            identity=str(
                user["id"]
            )
        )

        # Backend dashboard is the canonical dashboard
        # for this phase.
        return redirect(
            url_for(
                "dashboard_page",
                token=jwt_token,
            )
        )

    except Exception:
        logger.exception(
            "Google OAuth callback failed."
        )

        return jsonify({
            "success": False,
            "message": (
                "Google authentication failed."
            ),
        }), 500


# ============================================================
# LOGOUT
# ============================================================

@app.get("/logout")
def logout():
    session.clear()

    return redirect(
        url_for("home")
    )


@app.post("/api/auth/logout")
def api_logout():
    session.clear()

    return jsonify({
        "success": True,
    })


# ============================================================
# CURRENT USER
# ============================================================

@app.get("/api/auth/me")
@login_required_api
def auth_me():
    user = current_user()

    return jsonify({
        "success": True,
        "user": user,
    })


# ============================================================
# LIVE MARKET ENDPOINT
# ============================================================

@app.get("/api/market/<symbol>")
@login_required_api
def live_market(symbol):
    symbol = symbol.upper().strip()

    if not re.fullmatch(
        r"[A-Z0-9]{2,15}",
        symbol,
    ):
        return jsonify({
            "success": False,
            "message": "Invalid asset symbol.",
        }), 400

    market = fetch_market_data(
        symbol,
        force=True,
    )

    return jsonify({
        "success": True,
        "market": market,
        "timestamp": utc_now_iso(),
        "request_id": request.request_id,
    })


# ============================================================
# RUN ANALYSIS
# ============================================================

@app.post("/api/analyze")
@login_required_api
def analyze():
    data = request.get_json(
        silent=True
    ) or {}

    symbol = str(
        data.get(
            "token_symbol",
            "",
        )
    ).strip().upper()

    chain_id = str(
        data.get(
            "chain_id",
            "",
        )
    ).strip() or None

    contract_address = str(
        data.get(
            "contract_address",
            "",
        )
    ).strip() or None

    if not re.fullmatch(
        r"[A-Z0-9]{2,15}",
        symbol,
    ):
        return jsonify({
            "success": False,
            "message": (
                "Enter a valid cryptocurrency "
                "symbol such as BTC or ETH."
            ),
        }), 400

    user = current_user()

    if not user:
        return jsonify({
            "success": False,
            "message": "Authentication required.",
        }), 401

    started = time.perf_counter()

    try:
        report = run_analysis(
            symbol=symbol,
            chain_id=chain_id,
            contract_address=contract_address,
            force_market_refresh=True,
        )

        saved = save_analysis(
            user_id=user["id"],
            report=report,
            chain_id=chain_id,
            contract_address=contract_address,
        )

        report["database"] = {
            "id": saved["id"],
            "created_at": saved["created_at"],
        }

        elapsed = (
            time.perf_counter()
            - started
        )

        return jsonify({
            "success": True,

            "latest": report,

            "analysis": report,

            "history": get_user_history(
                user["id"]
            ),

            "user": user,

            "meta": {
                "processing_time_seconds": round(
                    elapsed,
                    3,
                ),
                "request_id": request.request_id,
                "timestamp": utc_now_iso(),
            },
        })

    except Exception:
        logger.exception(
            "Analysis failed for %s",
            symbol,
        )

        return jsonify({
            "success": False,
            "message": (
                "The analysis engine could not "
                "complete this request."
            ),
            "request_id": request.request_id,
        }), 500


# ============================================================
# DASHBOARD GET
# ============================================================

@app.get("/api/dashboard")
@login_required_api
def dashboard_api():
    user = current_user()

    history = get_user_history(
        user["id"]
    )

    latest = None

    if history:
        latest_record = get_analysis_by_id(
            user["id"],
            history[0]["id"],
        )

        if latest_record:
            latest = latest_record[
                "report"
            ]

            latest["database"] = {
                "id": latest_record[
                    "id"
                ],
                "created_at": (
                    latest_record[
                        "created_at"
                    ]
                ),
            }

    return jsonify({
        "success": True,
        "latest": latest,
        "history": history,
        "user": user,
        "timestamp": utc_now_iso(),
        "request_id": request.request_id,
    })


# ============================================================
# SINGLE REPORT
# ============================================================

@app.get("/api/history/<int:report_id>")
@login_required_api
def get_history_report(report_id):
    user = current_user()

    record = get_analysis_by_id(
        user["id"],
        report_id,
    )

    if not record:
        return jsonify({
            "success": False,
            "message": "Report not found.",
        }), 404

    return jsonify({
        "success": True,
        "report": record["report"],
        "database": {
            "id": record["id"],
            "created_at": record[
                "created_at"
            ],
        },
    })


# ============================================================
# DELETE SINGLE REPORT
# ============================================================

@app.delete("/api/history/<int:report_id>")
@app.post("/api/history/<int:report_id>/delete")
@login_required_api
def delete_history_report(report_id):
    user = current_user()

    deleted = delete_analysis(
        user["id"],
        report_id,
    )

    if not deleted:
        return jsonify({
            "success": False,
            "message": "Report not found.",
        }), 404

    return jsonify({
        "success": True,
        "message": "Report deleted.",
        "history": get_user_history(
            user["id"]
        ),
    })


# ============================================================
# DELETE ALL HISTORY
# ============================================================

@app.delete("/api/history")
@app.post("/api/history/delete-all")
@login_required_api
def delete_history():
    user = current_user()

    count = delete_all_analyses(
        user["id"]
    )

    return jsonify({
        "success": True,
        "deleted": count,
        "history": [],
    })


# ============================================================
# ERROR HANDLERS
# ============================================================

@app.errorhandler(404)
def not_found(error):
    if request.path.startswith("/api/"):
        return jsonify({
            "success": False,
            "message": "Endpoint not found.",
            "request_id": getattr(
                request,
                "request_id",
                None,
            ),
        }), 404

    return render_template(
        "index.html"
    )


@app.errorhandler(405)
def method_not_allowed(error):
    if request.path.startswith("/api/"):
        return jsonify({
            "success": False,
            "message": "Method not allowed.",
            "request_id": getattr(
                request,
                "request_id",
                None,
            ),
        }), 405

    return (
        "Method not allowed",
        405,
    )


@app.errorhandler(500)
def internal_server_error(error):
    logger.exception(
        "Unhandled server error."
    )

    if request.path.startswith("/api/"):
        return jsonify({
            "success": False,
            "message": (
                "Internal server error."
            ),
            "request_id": getattr(
                request,
                "request_id",
                None,
            ),
        }), 500

    return (
        "Internal server error",
        500,
    )


# ============================================================
# LOCAL DEVELOPMENT
# ============================================================

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(
            os.getenv(
                "PORT",
                "5000",
            )
        ),
        debug=os.getenv(
            "FLASK_DEBUG",
            "false",
        ).lower() == "true",
    )
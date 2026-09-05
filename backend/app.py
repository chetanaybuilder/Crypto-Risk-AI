# ============================================================
# CRYPTORISK AI — BACKEND
# PART 1 / 3
# ============================================================

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from threading import Lock
from typing import Any, Optional
from urllib.parse import quote

import psycopg2
import requests
from authlib.integrations.flask_client import OAuth
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    get_jwt_identity,
    jwt_required,
)
from flask_bcrypt import Bcrypt
from google import genai
from google.genai import types


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("cryptorisk-ai")


# ============================================================
# PATHS / ENVIRONMENT
# ============================================================

PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)

ENV_FILE = os.path.join(PROJECT_ROOT, ".env")

try:
    from dotenv import load_dotenv

    load_dotenv(ENV_FILE)
except ImportError:
    logger.warning("python-dotenv is not installed.")


SECRET_KEY = os.getenv("SECRET_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

FRONTEND_URL = os.getenv(
    "FRONTEND_URL",
    "http://localhost:3000",
).rstrip("/")

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY") or SECRET_KEY


if not SECRET_KEY:
    raise ValueError("SECRET_KEY is missing.")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is missing.")

if not JWT_SECRET_KEY:
    raise ValueError("JWT_SECRET_KEY is missing.")


# ============================================================
# FLASK APP
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

app.config["JWT_ACCESS_TOKEN_EXPIRES"] = False

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = bool(
    FRONTEND_URL.startswith("https://")
)


# ============================================================
# CORS
# ============================================================

CORS(
    app,
    resources={
        r"/api/*": {
            "origins": FRONTEND_URL,
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
        "OPTIONS",
    ],
)


jwt = JWTManager(app)
bcrypt = Bcrypt(app)


# ============================================================
# GEMINI
# ============================================================

gemini_client = None

if GEMINI_API_KEY:
    try:
        gemini_client = genai.Client(
            api_key=GEMINI_API_KEY
        )
        logger.info("Gemini client initialized.")
    except Exception:
        logger.exception(
            "Failed to initialize Gemini client."
        )
else:
    logger.warning(
        "GEMINI_API_KEY is not configured."
    )


# ============================================================
# GOOGLE OAUTH
# ============================================================

oauth = OAuth(app)

if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url=(
            "https://accounts.google.com/.well-known/"
            "openid-configuration"
        ),
        client_kwargs={
            "scope": (
                "openid email profile "
                "https://www.googleapis.com/auth/gmail.readonly"
            )
        },
    )
else:
    logger.warning(
        "Google OAuth credentials are not configured."
    )


# ============================================================
# MARKET DATA CONFIGURATION
# ============================================================

COINGECKO_API_URL = (
    "https://api.coingecko.com/api/v3"
)

BINANCE_API_URL = (
    "https://api.binance.com/api/v3/ticker/24hr"
)

MARKET_REQUEST_TIMEOUT = 10


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
}


MARKET_DATA_DEFAULTS = {
    "ticker": "",
    "symbol": "",
    "current_price": 0.0,
    "current_price_usd": 0.0,
    "volume_24h": 0.0,
    "volume_24h_usd": 0.0,
    "market_cap": 0.0,
    "market_cap_usd": 0.0,
    "price_change_percentage_24h": 0.0,
    "price_change_percentage_7d": 0.0,
    "high_24h_usd": 0.0,
    "low_24h_usd": 0.0,
    "market_data_available": False,
    "data_source": "unavailable",
}


# ============================================================
# GENERIC HELPERS
# ============================================================

def _numeric_value(
    value: Any,
    default: float = 0.0,
) -> float:
    """
    Safely convert arbitrary input into a finite float.
    """

    try:
        if value is None:
            return default

        if isinstance(value, str):
            value = value.strip()

            if not value:
                return default

            value = value.replace(",", "")

        number = float(value)

        if number != number:
            return default

        if number in (float("inf"), float("-inf")):
            return default

        return number

    except (
        ValueError,
        TypeError,
        OverflowError,
    ):
        return default


def _bounded_score(
    value: Any,
    default: float = 50,
) -> int:
    """
    Convert arbitrary input to an integer risk score
    between 0 and 100.
    """

    number = _numeric_value(
        value,
        default,
    )

    return max(
        0,
        min(
            100,
            int(round(number)),
        ),
    )


def format_percentage(
    value: Any,
) -> str:
    """
    Always display percentages using exactly 2 decimals.
    """

    number = _numeric_value(value)

    return f"{number:.2f}%"


def format_usd(
    value: Any,
) -> str:
    """
    Human-readable USD formatting.
    """

    number = _numeric_value(value)

    absolute = abs(number)

    if absolute >= 1_000_000_000:
        return f"${number / 1_000_000_000:.2f}B"

    if absolute >= 1_000_000:
        return f"${number / 1_000_000:.2f}M"

    if absolute >= 1_000:
        return f"${number / 1_000:.2f}K"

    return f"${number:,.2f}"


def sanitize_market_data(
    data: Optional[dict],
    ticker: str = "",
) -> dict:
    """
    Normalize market-data payloads coming from CoinGecko,
    Binance, or fallback logic.
    """

    source = dict(MARKET_DATA_DEFAULTS)

    if isinstance(data, dict):
        source.update(data)

    clean_ticker = (
        str(
            source.get("ticker")
            or ticker
            or ""
        )
        .strip()
        .upper()
    )

    current_price = _numeric_value(
        source.get(
            "current_price",
            source.get("current_price_usd", 0),
        )
    )

    volume_24h = _numeric_value(
        source.get(
            "volume_24h_usd",
            source.get("volume_24h", 0),
        )
    )

    market_cap = _numeric_value(
        source.get(
            "market_cap_usd",
            source.get("market_cap", 0),
        )
    )

    change_24h = _numeric_value(
        source.get(
            "price_change_percentage_24h",
            0,
        )
    )

    change_7d = _numeric_value(
        source.get(
            "price_change_percentage_7d",
            0,
        )
    )

    high_24h = _numeric_value(
        source.get(
            "high_24h_usd",
            0,
        )
    )

    low_24h = _numeric_value(
        source.get(
            "low_24h_usd",
            0,
        )
    )

    return {
        **source,

        "ticker": clean_ticker,

        "symbol": (
            str(
                source.get("symbol")
                or clean_ticker
            )
            .strip()
            .upper()
        ),

        "current_price": current_price,
        "current_price_usd": current_price,

        "volume_24h": volume_24h,
        "volume_24h_usd": volume_24h,

        "market_cap": market_cap,
        "market_cap_usd": market_cap,

        "price_change_percentage_24h": change_24h,
        "price_change_percentage_7d": change_7d,

        "high_24h_usd": high_24h,
        "low_24h_usd": low_24h,

        "market_data_available": bool(
            source.get(
                "market_data_available",
                current_price > 0,
            )
        ),

        "data_source": str(
            source.get(
                "data_source",
                "unknown",
            )
        ),
    }


def format_market_data_for_display(
    market_data: dict,
) -> dict:
    """
    Build frontend-safe display values while preserving
    raw numeric values for calculations.
    """

    data = sanitize_market_data(market_data)

    return {
        **data,

        "current_price_display": format_usd(
            data["current_price"]
        ),

        "volume_24h_display": format_usd(
            data["volume_24h_usd"]
        ),

        "market_cap_display": format_usd(
            data["market_cap_usd"]
        ),

        "change_24h_display": format_percentage(
            data["price_change_percentage_24h"]
        ),

        "change_7d_display": format_percentage(
            data["price_change_percentage_7d"]
        ),
    }


# ============================================================
# BINANCE FALLBACK
# ============================================================

def fetch_binance_market_data(
    ticker: str,
) -> dict:
    """
    Fetch 24h market data from Binance public API.

    Binance does not provide the requested 7-day percentage
    in this endpoint, so we estimate it as:

        estimated_7d = 24h_change * 1.35

    This is intentionally an estimate and is clearly marked
    in the returned payload.
    """

    ticker = (
        str(ticker)
        .strip()
        .upper()
    )

    if not ticker:
        raise ValueError(
            "Ticker is required."
        )

    symbol = f"{ticker}USDT"

    response = requests.get(
        BINANCE_API_URL,
        params={
            "symbol": symbol,
        },
        timeout=MARKET_REQUEST_TIMEOUT,
        headers={
            "Accept": "application/json",
            "User-Agent": "CryptoRiskAI/1.0",
        },
    )

    response.raise_for_status()

    payload = response.json()

    if not isinstance(payload, dict):
        raise ValueError(
            "Invalid Binance response."
        )

    current_price = _numeric_value(
        payload.get("lastPrice")
    )

    volume_24h = _numeric_value(
        payload.get("quoteVolume")
    )

    change_24h = _numeric_value(
        payload.get("priceChangePercent")
    )

    high_24h = _numeric_value(
        payload.get("highPrice")
    )

    low_24h = _numeric_value(
        payload.get("lowPrice")
    )

    if current_price <= 0:
        raise ValueError(
            f"Binance returned invalid price for {ticker}."
        )

    # The 24h ticker endpoint gives quote volume.
    # It does not give market cap.
    #
    # Therefore market cap intentionally remains 0 rather
    # than inventing a value.
    estimated_7d = change_24h * 1.35

    return sanitize_market_data(
        {
            "ticker": ticker,
            "symbol": ticker,

            "current_price": current_price,
            "current_price_usd": current_price,

            "volume_24h": volume_24h,
            "volume_24h_usd": volume_24h,

            "market_cap": 0.0,
            "market_cap_usd": 0.0,

            "price_change_percentage_24h": change_24h,

            "price_change_percentage_7d": (
                estimated_7d
            ),

            "high_24h_usd": high_24h,
            "low_24h_usd": low_24h,

            "market_data_available": True,

            "data_source": (
                "binance_estimated_7d"
            ),
        },
        ticker=ticker,
    )


# ============================================================
# COINGECKO
# ============================================================

def fetch_crypto_market_data(
    ticker: str,
) -> dict:
    """
    Primary market-data provider: CoinGecko.

    Automatic fallback:

        CoinGecko
             ↓
        Binance
             ↓
        unavailable

    Never silently pretends unavailable data is real.
    """

    ticker = (
        str(ticker)
        .strip()
        .upper()
    )

    if not ticker:
        raise ValueError(
            "Ticker is required."
        )

    coin_id = TOKEN_MAP.get(ticker)

    try:
        # ----------------------------------------------------
        # Resolve unknown ticker through CoinGecko search
        # ----------------------------------------------------

        if not coin_id:
            search_response = requests.get(
                f"{COINGECKO_API_URL}/search",
                params={
                    "query": ticker,
                },
                timeout=MARKET_REQUEST_TIMEOUT,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "CryptoRiskAI/1.0",
                },
            )

            if search_response.status_code == 429:
                raise requests.HTTPError(
                    "CoinGecko rate limited."
                )

            search_response.raise_for_status()

            search_payload = (
                search_response.json()
            )

            coins = search_payload.get(
                "coins",
                [],
            )

            if not coins:
                raise ValueError(
                    f"CoinGecko could not find {ticker}."
                )

            # Prefer exact symbol match.
            exact_match = next(
                (
                    coin
                    for coin in coins
                    if str(
                        coin.get("symbol", "")
                    ).upper()
                    == ticker
                ),
                None,
            )

            selected_coin = (
                exact_match
                or coins[0]
            )

            coin_id = selected_coin.get(
                "id"
            )

            if not coin_id:
                raise ValueError(
                    "CoinGecko returned no coin ID."
                )

        # ----------------------------------------------------
        # Fetch market data
        # ----------------------------------------------------

        market_response = requests.get(
            f"{COINGECKO_API_URL}/coins/markets",
            params={
                "vs_currency": "usd",
                "ids": coin_id,
                "price_change_percentage": "7d",
            },
            timeout=MARKET_REQUEST_TIMEOUT,
            headers={
                "Accept": "application/json",
                "User-Agent": "CryptoRiskAI/1.0",
            },
        )

        if market_response.status_code == 429:
            raise requests.HTTPError(
                "CoinGecko rate limited."
            )

        market_response.raise_for_status()

        markets = market_response.json()

        if not markets:
            raise ValueError(
                "CoinGecko returned empty market data."
            )

        market = markets[0]

        current_price = _numeric_value(
            market.get("current_price")
        )

        volume_24h = _numeric_value(
            market.get("total_volume")
        )

        market_cap = _numeric_value(
            market.get("market_cap")
        )

        change_24h = _numeric_value(
            market.get(
                "price_change_percentage_24h"
            )
        )

        change_7d = _numeric_value(
            market.get(
                "price_change_percentage_7d_in_currency"
            )
        )

        high_24h = _numeric_value(
            market.get("high_24h")
        )

        low_24h = _numeric_value(
            market.get("low_24h")
        )

        if current_price <= 0:
            raise ValueError(
                "CoinGecko returned invalid price."
            )

        return sanitize_market_data(
            {
                "ticker": ticker,

                "symbol": str(
                    market.get("symbol")
                    or ticker
                ).upper(),

                "current_price": current_price,
                "current_price_usd": current_price,

                "volume_24h": volume_24h,
                "volume_24h_usd": volume_24h,

                "market_cap": market_cap,
                "market_cap_usd": market_cap,

                "price_change_percentage_24h": (
                    change_24h
                ),

                "price_change_percentage_7d": (
                    change_7d
                ),

                "high_24h_usd": high_24h,
                "low_24h_usd": low_24h,

                "market_data_available": True,

                "data_source": "coingecko",
            },
            ticker=ticker,
        )

    except (
        requests.RequestException,
        ValueError,
        TypeError,
        KeyError,
    ) as primary_error:

        logger.warning(
            "CoinGecko failed for %s: %s. "
            "Trying Binance fallback.",
            ticker,
            primary_error,
        )

        # ----------------------------------------------------
        # BINANCE FALLBACK
        # ----------------------------------------------------

        try:
            return fetch_binance_market_data(
                ticker
            )

        except (
            requests.RequestException,
            ValueError,
            TypeError,
            KeyError,
        ) as fallback_error:

            logger.error(
                "Both CoinGecko and Binance failed "
                "for %s: %s",
                ticker,
                fallback_error,
            )

            # IMPORTANT:
            # Do not manufacture $0.00 as real market data.
            return sanitize_market_data(
                {
                    "ticker": ticker,
                    "symbol": ticker,
                    "market_data_available": False,
                    "data_source": "unavailable",
                },
                ticker=ticker,
            )


# ============================================================
# GOPLUS TOKEN SECURITY
# ============================================================

GOPLUS_API_URL = (
    "https://api.gopluslabs.io/api/v1/token_security"
)


def _goplus_bool(
    value: Any,
) -> bool:
    """
    Normalize GoPlus boolean-like values.
    """

    if isinstance(value, bool):
        return value

    return str(value).strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _goplus_tax_percentage(
    value: Any,
) -> float:
    """
    Normalize GoPlus tax values.

    GoPlus may return decimal strings such as:
        0.05
    or:
        5

    Values <= 1 are treated as fractions.
    """

    number = _numeric_value(value)

    if number <= 1:
        return number * 100

    return number


def fetch_token_security(
    chain_id: str,
    contract_address: str,
) -> dict:
    """
    Fetch token-security data from GoPlus.

    Returns an empty dict when unavailable rather than
    fabricating security information.
    """

    chain_id = str(
        chain_id or ""
    ).strip()

    contract_address = str(
        contract_address or ""
    ).strip()

    if not chain_id or not contract_address:
        return {}

    try:
        response = requests.get(
            f"{GOPLUS_API_URL}/{chain_id}",
            params={
                "contract_addresses": contract_address,
            },
            timeout=MARKET_REQUEST_TIMEOUT,
            headers={
                "Accept": "application/json",
                "User-Agent": "CryptoRiskAI/1.0",
            },
        )

        response.raise_for_status()

        payload = response.json()

        result = payload.get(
            "result",
            {},
        )

        if not isinstance(result, dict):
            return {}

        security = result.get(
            contract_address.lower()
        )

        if not security:
            security = result.get(
                contract_address
            )

        if not isinstance(security, dict):
            return {}

        return {
            "is_honeypot": _goplus_bool(
                security.get(
                    "is_honeypot",
                    0,
                )
            ),

            "buy_tax": _goplus_tax_percentage(
                security.get(
                    "buy_tax",
                    0,
                )
            ),

            "sell_tax": _goplus_tax_percentage(
                security.get(
                    "sell_tax",
                    0,
                )
            ),

            "is_open_source": _goplus_bool(
                security.get(
                    "is_open_source",
                    1,
                )
            ),

            "owner_change_balance": _goplus_bool(
                security.get(
                    "owner_change_balance",
                    0,
                )
            ),

            "hidden_owner": _goplus_bool(
                security.get(
                    "hidden_owner",
                    0,
                )
            ),

            "can_take_back_ownership": _goplus_bool(
                security.get(
                    "can_take_back_ownership",
                    0,
                )
            ),

            "cannot_sell_all": _goplus_bool(
                security.get(
                    "cannot_sell_all",
                    0,
                )
            ),

            "data_source": "goplus",
        }

    except (
        requests.RequestException,
        ValueError,
        TypeError,
        KeyError,
    ) as error:

        logger.warning(
            "GoPlus security lookup failed: %s",
            error,
        )

        return {}


# ============================================================
# RISK ENGINE
# ============================================================

def evaluate_risk_profile(
    market_data: dict,
    security_data: Optional[dict] = None,
) -> dict:
    """
    Calculate the four-pillar risk profile.

    Pillars:
        1. Volatility
        2. Liquidity
        3. Contract
        4. Composite
    """

    market = sanitize_market_data(
        market_data
    )

    security = (
        security_data
        if isinstance(security_data, dict)
        else {}
    )

    # --------------------------------------------------------
    # VOLATILITY
    # --------------------------------------------------------

    change_7d = abs(
        _numeric_value(
            market.get(
                "price_change_percentage_7d"
            )
        )
    )

    change_24h = abs(
        _numeric_value(
            market.get(
                "price_change_percentage_24h"
            )
        )
    )

    high_24h = _numeric_value(
        market.get("high_24h_usd")
    )

    low_24h = _numeric_value(
        market.get("low_24h_usd")
    )

    current_price = _numeric_value(
        market.get("current_price")
    )

    range_percentage = 0.0

    if (
        current_price > 0
        and high_24h > 0
        and low_24h >= 0
        and high_24h >= low_24h
    ):
        range_percentage = (
            (
                high_24h - low_24h
            )
            / current_price
        ) * 100

    volatility_signal = max(
        change_7d,
        change_24h * 2,
        range_percentage,
    )

    if volatility_signal >= 40:
        volatility_risk = 95
    elif volatility_signal >= 30:
        volatility_risk = 85
    elif volatility_signal >= 20:
        volatility_risk = 72
    elif volatility_signal >= 12:
        volatility_risk = 58
    elif volatility_signal >= 7:
        volatility_risk = 42
    else:
        volatility_risk = 25

    # --------------------------------------------------------
    # LIQUIDITY
    # --------------------------------------------------------

    volume_24h = _numeric_value(
        market.get("volume_24h_usd")
    )

    market_cap = _numeric_value(
        market.get("market_cap_usd")
    )

    liquidity_data_complete = (
        volume_24h > 0
        and market_cap > 0
    )

    if liquidity_data_complete:
        turnover = (
            volume_24h / market_cap
        )

        if turnover < 0.01:
            liquidity_risk = 92
        elif turnover < 0.02:
            liquidity_risk = 78
        elif turnover < 0.05:
            liquidity_risk = 60
        elif turnover < 0.10:
            liquidity_risk = 42
        else:
            liquidity_risk = 25

    elif volume_24h > 0:
        # Binance fallback does not provide market cap.
        # Do NOT incorrectly label the asset as maximally
        # illiquid just because market cap is unavailable.
        liquidity_risk = 50

    else:
        liquidity_risk = 60

    # --------------------------------------------------------
    # CONTRACT
    # --------------------------------------------------------

    if security:
        if security.get("is_honeypot"):
            contract_risk = 100
        else:
            buy_tax = _numeric_value(
                security.get("buy_tax")
            )

            sell_tax = _numeric_value(
                security.get("sell_tax")
            )

            contract_risk = 15

            if buy_tax >= 10:
                contract_risk += 25
            elif buy_tax >= 5:
                contract_risk += 15

            if sell_tax >= 10:
                contract_risk += 30
            elif sell_tax >= 5:
                contract_risk += 20

            if not security.get(
                "is_open_source",
                True,
            ):
                contract_risk += 15

            if security.get(
                "hidden_owner",
                False,
            ):
                contract_risk += 20

            if security.get(
                "can_take_back_ownership",
                False,
            ):
                contract_risk += 20

            contract_risk = _bounded_score(
                contract_risk
            )

    else:
        # Native assets such as BTC/ETH/SOL do not have a
        # normal ERC-style contract-security profile.
        # Unknown contract information must not become 100.
        if str(
            market.get("ticker", "")
        ).upper() in {
            "BTC",
            "ETH",
            "SOL",
            "BNB",
            "XRP",
            "ADA",
            "DOGE",
        }:
            contract_risk = 15
        else:
            contract_risk = 50

    # --------------------------------------------------------
    # COMPOSITE
    # --------------------------------------------------------

    composite_score = _bounded_score(
        (
            volatility_risk * 0.35
            + liquidity_risk * 0.35
            + contract_risk * 0.30
        )
    )

    if composite_score >= 75:
        severity = "Critical"
    elif composite_score >= 55:
        severity = "High"
    elif composite_score >= 35:
        severity = "Moderate"
    else:
        severity = "Low"

    return {
        "volatility_risk": _bounded_score(
            volatility_risk
        ),

        "liquidity_risk": _bounded_score(
            liquidity_risk
        ),

        "contract_risk": _bounded_score(
            contract_risk
        ),

        "composite_score": _bounded_score(
            composite_score
        ),

        "severity": severity,

        "liquidity_data_complete": (
            liquidity_data_complete
        ),
    }


def calculate_risk_score(
    market_data: dict,
    security_data: Optional[dict] = None,
) -> int:
    """
    Compatibility wrapper used by older parts of the app.
    """

    profile = evaluate_risk_profile(
        market_data,
        security_data,
    )

    return _bounded_score(
        profile.get(
            "composite_score",
            50,
        )
    )


# ============================================================
# STRESS TEST
# ============================================================

def simulate_stress_test(
    asset_change_7d: Any,
    btc_change_7d: Any,
    shock_pct: float = -10.0,
) -> dict:
    """
    Estimate asset drawdown under a BTC market shock.

    Beta is estimated from the relative 7-day moves and
    bounded between 0.5x and 3.0x.
    """

    asset_change = _numeric_value(
        asset_change_7d
    )

    btc_change = _numeric_value(
        btc_change_7d
    )

    shock = _numeric_value(
        shock_pct,
        -10.0,
    )

    benchmark_available = (
        abs(btc_change) > 0.000001
    )

    if benchmark_available:
        raw_beta = (
            asset_change / btc_change
        )
    else:
        raw_beta = 1.0

    beta = max(
        0.5,
        min(
            3.0,
            raw_beta,
        ),
    )

    projected_drawdown = (
        shock * beta
    )

    if projected_drawdown <= -25:
        verdict = "Severe downside sensitivity"
    elif projected_drawdown <= -15:
        verdict = "High downside sensitivity"
    elif projected_drawdown <= -10:
        verdict = "Moderate downside sensitivity"
    else:
        verdict = "Contained downside sensitivity"

    return {
        "shock_pct": float(shock),
        "beta": round(beta, 2),
        "projected_drawdown_pct": round(
            projected_drawdown,
            2,
        ),
        "benchmark_available": (
            benchmark_available
        ),
        "verdict": verdict,
    }


# ============================================================
# AI DISCLAIMER FILTER
# ============================================================

FORBIDDEN_AI_PHRASES = (
    "i am not a financial advisor",
    "i'm not a financial advisor",
    "this is not financial advice",
    "not financial advice",
    "consult a financial advisor",
    "consult your financial advisor",
    "do your own research",
    "dyor",
)


def _is_generic_ai_disclaimer(
    value: str,
) -> bool:
    """
    Detect boilerplate disclaimer text that should never
    become part of the forensic risk report.
    """

    normalized_value = str(
        value or ""
    ).lower()

    return any(
        phrase in normalized_value
        for phrase in FORBIDDEN_AI_PHRASES
    )


# ============================================================
# JSON EXTRACTION
# ============================================================

def extract_json(
    value: Any,
) -> dict:
    """
    Safely extract a JSON object from Gemini output.

    Handles:
        - plain JSON
        - ```json ... ```
        - surrounding prose
    """

    if isinstance(value, dict):
        return value

    if value is None:
        return {}

    text = str(value).strip()

    if not text:
        return {}

    # Remove markdown fences.
    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"\s*```$",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = text.strip()

    # Direct parse first.
    try:
        parsed = json.loads(text)

        if isinstance(parsed, dict):
            return parsed

    except json.JSONDecodeError:
        pass

    # Search for the first JSON object.
    start = text.find("{")
    end = text.rfind("}")

    if start == -1 or end == -1:
        return {}

    candidate = text[
        start : end + 1
    ]

    try:
        parsed = json.loads(
            candidate
        )

        return (
            parsed
            if isinstance(parsed, dict)
            else {}
        )

    except json.JSONDecodeError:
        return {}


def is_api_request() -> bool:
    """
    Determine if the current request is an API request.
    """

    return bool(
        request.path.startswith("/api/")
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )


# ============================================================
# END OF PART 1
# ============================================================

# ============================================================
# PART 2 — DATABASE + AUTH + GOOGLE OAUTH + GEMINI + NORMALIZER
# ============================================================


# ============================================================
# DATABASE
# ============================================================

def get_db_connection():
    """Create a PostgreSQL connection."""
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured.")

    return psycopg2.connect(
        database_url,
        sslmode="require",
    )


def init_db():
    """Create required database tables if they do not exist."""
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT,
                google_id TEXT UNIQUE,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS analyses (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id)
                    ON DELETE CASCADE,
                token_address TEXT NOT NULL,
                chain TEXT,
                report JSONB NOT NULL,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        connection.commit()

    except Exception:
        if connection:
            connection.rollback()
        raise

    finally:
        if cursor:
            cursor.close()

        if connection:
            connection.close()


def row_to_dict(cursor, row):
    """Convert a PostgreSQL row into a dictionary."""
    if row is None:
        return None

    columns = [
        description[0]
        for description in cursor.description
    ]

    return dict(zip(columns, row))


def get_user_by_id(user_id):
    """Get user by database ID."""
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                id,
                name,
                email,
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

        return row_to_dict(
            cursor,
            row,
        )

    finally:
        if cursor:
            cursor.close()

        if connection:
            connection.close()


def get_user_by_email(email):
    """Get user by email."""
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                id,
                name,
                email,
                password_hash,
                google_id,
                created_at
            FROM users
            WHERE LOWER(email) = LOWER(%s)
            LIMIT 1
            """,
            (email,),
        )

        row = cursor.fetchone()

        return row_to_dict(
            cursor,
            row,
        )

    finally:
        if cursor:
            cursor.close()

        if connection:
            connection.close()


def get_user_by_google_id(google_id):
    """Get user by Google subject ID."""
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                id,
                name,
                email,
                password_hash,
                google_id,
                created_at
            FROM users
            WHERE google_id = %s
            LIMIT 1
            """,
            (google_id,),
        )

        row = cursor.fetchone()

        return row_to_dict(
            cursor,
            row,
        )

    finally:
        if cursor:
            cursor.close()

        if connection:
            connection.close()


def create_local_user(
    name,
    email,
    password_hash,
):
    """Create a standard email/password user."""
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            INSERT INTO users (
                name,
                email,
                password_hash
            )
            VALUES (%s, %s, %s)
            RETURNING
                id,
                name,
                email,
                password_hash,
                google_id,
                created_at
            """,
            (
                name,
                email,
                password_hash,
            ),
        )

        row = row_to_dict(
            cursor,
            cursor.fetchone(),
        )

        connection.commit()

        return row

    except Exception:
        if connection:
            connection.rollback()
        raise

    finally:
        if cursor:
            cursor.close()

        if connection:
            connection.close()


def create_or_update_google_user(
    name,
    email,
    google_id,
):
    """Create or update a Google-authenticated user."""
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                id,
                name,
                email,
                password_hash,
                google_id,
                created_at
            FROM users
            WHERE LOWER(email) = LOWER(%s)
            LIMIT 1
            """,
            (email,),
        )

        existing_user = row_to_dict(
            cursor,
            cursor.fetchone(),
        )

        if existing_user:
            cursor.execute(
                """
                UPDATE users
                SET
                    name = %s,
                    google_id = %s
                WHERE id = %s
                RETURNING
                    id,
                    name,
                    email,
                    password_hash,
                    google_id,
                    created_at
                """,
                (
                    name or existing_user["name"],
                    google_id,
                    existing_user["id"],
                ),
            )

        else:
            cursor.execute(
                """
                INSERT INTO users (
                    name,
                    email,
                    google_id
                )
                VALUES (%s, %s, %s)
                RETURNING
                    id,
                    name,
                    email,
                    password_hash,
                    google_id,
                    created_at
                """,
                (
                    name or "CryptoRisk User",
                    email,
                    google_id,
                ),
            )

        row = row_to_dict(
            cursor,
            cursor.fetchone(),
        )

        connection.commit()

        return row

    except Exception:
        if connection:
            connection.rollback()
        raise

    finally:
        if cursor:
            cursor.close()

        if connection:
            connection.close()


def public_user_payload(user):
    """Return only safe user fields."""
    if not user:
        return None

    created_at = user.get("created_at")

    if hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat()

    return {
        "id": user.get("id"),
        "name": user.get("name"),
        "email": user.get("email"),
        "created_at": created_at,
    }


# ============================================================
# AUTH HELPERS
# ============================================================

def authenticated_user_id():
    """Return authenticated JWT identity as an integer."""
    try:
        identity = get_jwt_identity()
    except Exception:
        return None

    if identity in (
        None,
        "",
        False,
    ):
        return None

    try:
        return int(identity)

    except (
        TypeError,
        ValueError,
    ):
        return None


def issue_auth_token(user_id):
    """Create a JWT for the user."""
    return create_access_token(
        identity=str(user_id)
    )


def require_authenticated_user():
    """Return current user or a 401 response."""
    user_id = authenticated_user_id()

    if user_id is None:
        return (
            None,
            (
                jsonify(
                    {
                        "success": False,
                        "error": "Authentication required.",
                    }
                ),
                401,
            ),
        )

    user = get_user_by_id(user_id)

    if not user:
        return (
            None,
            (
                jsonify(
                    {
                        "success": False,
                        "error": "User account not found.",
                    }
                ),
                401,
            ),
        )

    return user, None


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

@app.before_request
def ensure_database():
    """Ensure database tables exist before normal requests."""
    if request.method == "OPTIONS":
        return None

    init_db()

    return None


# ============================================================
# SIGN UP
# ============================================================

@app.route(
    "/api/signup",
    methods=["POST", "OPTIONS"],
)
def api_signup():
    if request.method == "OPTIONS":
        return "", 204

    payload = request.get_json(
        silent=True
    ) or {}

    name = str(
        payload.get("name", "")
    ).strip()

    email = str(
        payload.get("email", "")
    ).strip().lower()

    password = str(
        payload.get("password", "")
    )

    if not name or not email or not password:
        return (
            jsonify(
                {
                    "success": False,
                    "error": (
                        "Name, email, and password "
                        "are required."
                    ),
                }
            ),
            400,
        )

    if len(password) < 8:
        return (
            jsonify(
                {
                    "success": False,
                    "error": (
                        "Password must be at least "
                        "8 characters."
                    ),
                }
            ),
            400,
        )

    existing_user = get_user_by_email(email)

    if existing_user:
        return (
            jsonify(
                {
                    "success": False,
                    "error": (
                        "An account with this email "
                        "already exists."
                    ),
                }
            ),
            409,
        )

    password_hash = (
        bcrypt
        .generate_password_hash(password)
        .decode("utf-8")
    )

    try:
        user = create_local_user(
            name,
            email,
            password_hash,
        )

    except psycopg2.IntegrityError:
        return (
            jsonify(
                {
                    "success": False,
                    "error": (
                        "An account with this email "
                        "already exists."
                    ),
                }
            ),
            409,
        )

    token = issue_auth_token(
        user["id"]
    )

    return (
        jsonify(
            {
                "success": True,
                "message": (
                    "Account created successfully."
                ),
                "token": token,
                "user": public_user_payload(user),
            }
        ),
        201,
    )


# ============================================================
# LOGIN
# ============================================================

@app.route(
    "/api/login",
    methods=["POST", "OPTIONS"],
)
def api_login():
    if request.method == "OPTIONS":
        return "", 204

    payload = request.get_json(
        silent=True
    ) or {}

    email = str(
        payload.get("email", "")
    ).strip().lower()

    password = str(
        payload.get("password", "")
    )

    if not email or not password:
        return (
            jsonify(
                {
                    "success": False,
                    "error": (
                        "Email and password "
                        "are required."
                    ),
                }
            ),
            400,
        )

    user = get_user_by_email(email)

    if not user:
        return (
            jsonify(
                {
                    "success": False,
                    "error": (
                        "Invalid email or password."
                    ),
                }
            ),
            401,
        )

    password_hash = user.get(
        "password_hash"
    )

    if not password_hash:
        return (
            jsonify(
                {
                    "success": False,
                    "error": (
                        "This account uses "
                        "Google authentication."
                    ),
                }
            ),
            401,
        )

    try:
        valid_password = (
            bcrypt.check_password_hash(
                password_hash,
                password,
            )
        )

    except Exception:
        valid_password = False

    if not valid_password:
        return (
            jsonify(
                {
                    "success": False,
                    "error": (
                        "Invalid email or password."
                    ),
                }
            ),
            401,
        )

    token = issue_auth_token(
        user["id"]
    )

    return jsonify(
        {
            "success": True,
            "message": "Login successful.",
            "token": token,
            "user": public_user_payload(user),
        }
    )


# ============================================================
# GOOGLE LOGIN
# ============================================================

@app.route(
    "/api/auth/google",
    methods=["GET"],
)
def google_login():
    if (
        not GOOGLE_CLIENT_ID
        or not GOOGLE_CLIENT_SECRET
    ):
        return (
            jsonify(
                {
                    "success": False,
                    "error": (
                        "Google OAuth is not "
                        "configured."
                    ),
                }
            ),
            503,
        )

    redirect_uri = url_for(
        "google_callback",
        _external=True,
    )

    return OAuth.google.authorize_redirect(
        redirect_uri
    )


@app.route(
    "/api/auth/google/callback",
    methods=["GET"],
)
def google_callback():
    if (
        not GOOGLE_CLIENT_ID
        or not GOOGLE_CLIENT_SECRET
    ):
        return (
            jsonify(
                {
                    "success": False,
                    "error": (
                        "Google OAuth is not "
                        "configured."
                    ),
                }
            ),
            503,
        )

    try:
        token = (
           OAuth.google.authorize_access_token()
        )

        user_info = (
            token.get("userinfo")
            or {}
        )

        google_id = str(
            user_info.get("sub", "")
        ).strip()

        email = str(
            user_info.get("email", "")
        ).strip().lower()

        name = str(
            user_info.get("name")
            or user_info.get("given_name")
            or "CryptoRisk User"
        ).strip()

        if not google_id or not email:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": (
                            "Google did not return "
                            "a valid account."
                        ),
                    }
                ),
                400,
            )

        user = create_or_update_google_user(
            name=name,
            email=email,
            google_id=google_id,
        )

        auth_token = issue_auth_token(
            user["id"]
        )

        return redirect(
            f"{FRONTEND_URL}/dashboard"
            f"?token={quote(auth_token)}"
        )

    except Exception:
        logger.exception(
            "Google OAuth callback failed."
        )

        return (
            jsonify(
                {
                    "success": False,
                    "error": (
                        "Google authentication "
                        "failed."
                    ),
                }
            ),
            500,
        )


# ============================================================
# SESSION
# ============================================================

@app.route(
    "/api/session",
    methods=["GET", "OPTIONS"],
)
@jwt_required(optional=True)
def api_session():
    if request.method == "OPTIONS":
        return "", 204

    user_id = authenticated_user_id()

    if user_id is None:
        return jsonify(
            {
                "success": True,
                "authenticated": False,
                "user": None,
            }
        )

    user = get_user_by_id(
        user_id
    )

    if not user:
        return jsonify(
            {
                "success": True,
                "authenticated": False,
                "user": None,
            }
        )

    return jsonify(
        {
            "success": True,
            "authenticated": True,
            "user": public_user_payload(user),
        }
    )


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route(
    "/api/health",
    methods=["GET", "OPTIONS"],
)
def api_health():
    if request.method == "OPTIONS":
        return "", 204

    database_ok = False
    connection = None
    cursor = None

    try:
        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            "SELECT 1"
        )

        cursor.fetchone()

        database_ok = True

    except Exception:
        database_ok = False

    finally:
        if cursor:
            cursor.close()

        if connection:
            connection.close()

    return jsonify(
        {
            "success": True,
            "status": "ok",
            "database": database_ok,
        }
    )


# ============================================================
# GEMINI PROMPT
# ============================================================

def build_crypto_prompt(
    token_address,
    chain,
    market_data,
    security_data,
    risk_data,
    stress_data,
):
    """Build the forensic Gemini prompt."""

    market_text = (
        format_market_data_for_display(
            market_data
        )
    )

    return f"""
You are the senior risk-forensics engine
inside CryptoRisk AI.

Analyze this cryptocurrency using ONLY
the supplied evidence.

TOKEN:
Address: {token_address}
Chain: {chain}

MARKET DATA:
{json.dumps(
    market_text,
    indent=2,
    default=str,
)}

TOKEN SECURITY DATA:
{json.dumps(
    security_data,
    indent=2,
    default=str,
)}

CALCULATED RISK DATA:
{json.dumps(
    risk_data,
    indent=2,
    default=str,
)}

STRESS TEST DATA:
{json.dumps(
    stress_data,
    indent=2,
    default=str,
)}

RULES:

1. Never invent market data.
2. Never invent contract facts.
3. Never invent holder data.
4. Never invent exploits.
5. Never use generic financial disclaimers.
6. If evidence is unavailable, say:
   "Evidence unavailable."
7. Severity must be one of:
   Critical, High, Moderate, Low, Minimal.
8. Scores must be between 0 and 100.
9. Return valid JSON only.
10. Do not use markdown code fences.

Return exactly:

{{
  "executive_verdict": {{
    "severity": "Moderate",
    "score": 50,
    "summary": "Evidence-based summary."
  }},
  "market_structure": {{
    "severity": "Moderate",
    "description": "Market structure assessment.",
    "evidence": "Evidence-based market evidence."
  }},
  "contract_risk": {{
    "severity": "Moderate",
    "description": "Contract security assessment.",
    "evidence": "Evidence-based contract evidence."
  }},
  "liquidity_risk": {{
    "severity": "Moderate",
    "description": "Liquidity assessment.",
    "evidence": "Evidence-based liquidity evidence."
  }},
  "holder_risk": {{
    "severity": "Moderate",
    "description": "Holder concentration assessment.",
    "evidence": "Evidence-based holder evidence."
  }},
  "stress_test": {{
    "verdict": "Moderate",
    "description": "Stress-test interpretation.",
    "evidence": "Evidence-based stress evidence."
  }},
  "key_findings": [
    "Finding 1",
    "Finding 2",
    "Finding 3"
  ],
  "investigation_notes": [
    "Note 1",
    "Note 2"
  ]
}}
""".strip()


# ============================================================
# GEMINI EXECUTION
# ============================================================

def run_gemini_analysis(
    token_address,
    chain,
    market_data,
    security_data,
    risk_data,
    stress_data,
):
    """Run Gemini and parse its JSON response."""

    if gemini_client is None:
        raise RuntimeError(
            "Gemini client is not configured."
        )

    prompt = build_crypto_prompt(
        token_address=token_address,
        chain=chain,
        market_data=market_data,
        security_data=security_data,
        risk_data=risk_data,
        stress_data=stress_data,
    )

    response = (
        gemini_client
        .models
        .generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
    )

    text = str(
        getattr(
            response,
            "text",
            "",
        )
        or ""
    ).strip()

    if not text:
        raise RuntimeError(
            "Gemini returned an empty response."
        )

    parsed = extract_json(text)

    if not isinstance(parsed, dict):
        raise RuntimeError(
            "Gemini returned invalid report JSON."
        )

    return parsed


# ============================================================
# REPORT NORMALIZATION HELPERS
# ============================================================

def safe_severity(
    value,
    fallback="Moderate",
):
    """Normalize severity into allowed values."""

    allowed = {
        "critical": "Critical",
        "high": "High",
        "moderate": "Moderate",
        "medium": "Moderate",
        "low": "Low",
        "minimal": "Minimal",
    }

    normalized = str(
        value or ""
    ).strip().lower()

    return allowed.get(
        normalized,
        fallback,
    )


def normalize_text_list(
    value,
    limit=8,
):
    """Normalize list-like AI fields."""

    if isinstance(value, str):
        items = [
            value.strip()
        ]

    elif isinstance(value, list):
        items = [
            str(item).strip()
            for item in value
            if str(item).strip()
        ]

    else:
        items = []

    return items[:limit]


# ============================================================
# REPORT NORMALIZER
# ============================================================

def normalize_report(
    report,
    market_data,
    risk_data,
    stress_data,
    security_data=None,
):
    """Normalize Gemini output for the frontend."""

    if not isinstance(report, dict):
        report = {}

    if not isinstance(
        security_data,
        dict,
    ):
        security_data = {}

    if not isinstance(
        market_data,
        dict,
    ):
        market_data = {}

    if not isinstance(
        risk_data,
        dict,
    ):
        risk_data = {}

    if not isinstance(
        stress_data,
        dict,
    ):
        stress_data = {}

    executive = report.get(
        "executive_verdict"
    )

    if not isinstance(
        executive,
        dict,
    ):
        executive = {}

    market_structure = report.get(
        "market_structure"
    )

    if not isinstance(
        market_structure,
        dict,
    ):
        market_structure = {}

    contract_risk = report.get(
        "contract_risk"
    )

    if not isinstance(
        contract_risk,
        dict,
    ):
        contract_risk = {}

    liquidity_risk = report.get(
        "liquidity_risk"
    )

    if not isinstance(
        liquidity_risk,
        dict,
    ):
        liquidity_risk = {}

    holder_risk = report.get(
        "holder_risk"
    )

    if not isinstance(
        holder_risk,
        dict,
    ):
        holder_risk = {}

    stress_test = report.get(
        "stress_test"
    )

    if not isinstance(
        stress_test,
        dict,
    ):
        stress_test = {}

    # --------------------------------------------------------
    # MARKET STRUCTURE
    # --------------------------------------------------------

    volatility_score = _bounded_score(
        risk_data.get(
            "volatility",
            50,
        )
    )

    if volatility_score >= 75:
        market_structure_fallback = "Critical"

    elif volatility_score >= 55:
        market_structure_fallback = "High"

    else:
        market_structure_fallback = "Moderate"

    market_structure_severity = safe_severity(
        market_structure.get(
            "severity"
        ),
        market_structure_fallback,
    )

    market_structure_description = str(
        market_structure.get(
            "description",
            "Price behavior and volatility evidence.",
        )
    ).strip()

    market_structure_evidence = str(
        market_structure.get(
            "evidence",
            (
                "24h change: "
                f"{format_percentage(market_data.get('change_24h'))}; "
                "7d change: "
                f"{format_percentage(market_data.get('change_7d'))}."
            ),
        )
    ).strip()

    # --------------------------------------------------------
    # LIQUIDITY
    # --------------------------------------------------------

    liquidity_score = _bounded_score(
        risk_data.get(
            "liquidity",
            50,
        )
    )

    if liquidity_score >= 75:
        liquidity_fallback = "Critical"

    elif liquidity_score >= 55:
        liquidity_fallback = "High"

    else:
        liquidity_fallback = "Moderate"

    liquidity_severity = safe_severity(
        liquidity_risk.get(
            "severity"
        ),
        liquidity_fallback,
    )

    volume_24h = _numeric_value(
        market_data.get(
            "volume_24h"
        )
    )

    liquidity_description = str(
        liquidity_risk.get(
            "description",
            "Trading liquidity and market depth assessment.",
        )
    ).strip()

    liquidity_evidence = str(
        liquidity_risk.get(
            "evidence",
            (
                "24h volume: "
                f"{format_usd(volume_24h)}."
            ),
        )
    ).strip()

    # --------------------------------------------------------
    # CONTRACT
    # --------------------------------------------------------

    contract_score = _bounded_score(
        risk_data.get(
            "contract",
            50,
        )
    )

    if contract_score >= 75:
        contract_fallback = "Critical"

    elif contract_score >= 55:
        contract_fallback = "High"

    else:
        contract_fallback = "Moderate"

    contract_severity = safe_severity(
        contract_risk.get(
            "severity"
        ),
        contract_fallback,
    )

    contract_description = str(
        contract_risk.get(
            "description",
            "Smart-contract security assessment.",
        )
    ).strip()

    contract_evidence = str(
        contract_risk.get(
            "evidence",
            "Contract security evidence unavailable.",
        )
    ).strip()

    # --------------------------------------------------------
    # HOLDER RISK
    # --------------------------------------------------------

    holder_score = _bounded_score(
        risk_data.get(
            "holder",
            50,
        )
    )

    if holder_score >= 75:
        holder_fallback = "Critical"

    elif holder_score >= 55:
        holder_fallback = "High"

    else:
        holder_fallback = "Moderate"

    holder_severity = safe_severity(
        holder_risk.get(
            "severity"
        ),
        holder_fallback,
    )

    holder_description = str(
        holder_risk.get(
            "description",
            "Holder concentration assessment.",
        )
    ).strip()

    holder_evidence = str(
        holder_risk.get(
            "evidence",
            "Holder concentration evidence unavailable.",
        )
    ).strip()

    # --------------------------------------------------------
    # STRESS TEST
    # --------------------------------------------------------

    stress_verdict = str(
        stress_test.get(
            "verdict",
            stress_data.get(
                "verdict",
                "Moderate",
            ),
        )
    ).strip()

    if _is_generic_ai_disclaimer(
        stress_verdict
    ):
        stress_verdict = str(
            stress_data.get(
                "verdict",
                "Moderate",
            )
        ).strip()

    stress_description = str(
        stress_test.get(
            "description",
            "Stress-test interpretation.",
        )
    ).strip()

    stress_evidence = str(
        stress_test.get(
            "evidence",
            stress_data.get(
                "summary",
                "Stress-test evidence unavailable.",
            ),
        )
    ).strip()

    # --------------------------------------------------------
    # EXECUTIVE VERDICT
    # --------------------------------------------------------

    executive_score = _bounded_score(
        executive.get(
            "score",
            risk_data.get(
                "composite",
                50,
            ),
        )
    )

    executive_severity = safe_severity(
        executive.get(
            "severity"
        ),
        safe_severity(
            risk_data.get(
                "severity",
                "Moderate",
            ),
            "Moderate",
        ),
    )

    executive_summary = str(
        executive.get(
            "summary",
            (
                "Risk assessment generated "
                "from available market and "
                "security evidence."
            ),
        )
    ).strip()

    # --------------------------------------------------------
    # FINAL STABLE REPORT
    # --------------------------------------------------------

    return {
        "executive_verdict": {
            "severity": executive_severity,
            "score": executive_score,
            "summary": executive_summary,
        },

        "market_structure": {
            "severity": market_structure_severity,
            "description": market_structure_description,
            "evidence": market_structure_evidence,
            "score": volatility_score,
        },

        "contract_risk": {
            "severity": contract_severity,
            "description": contract_description,
            "evidence": contract_evidence,
            "score": contract_score,
        },

        "liquidity_risk": {
            "severity": liquidity_severity,
            "description": liquidity_description,
            "evidence": liquidity_evidence,
            "score": liquidity_score,
        },

        "holder_risk": {
            "severity": holder_severity,
            "description": holder_description,
            "evidence": holder_evidence,
            "score": holder_score,
        },

        "stress_test": {
            "verdict": stress_verdict,
            "description": stress_description,
            "evidence": stress_evidence,
        },

        "key_findings": normalize_text_list(
            report.get(
                "key_findings"
            ),
            limit=8,
        ),

        "investigation_notes": normalize_text_list(
            report.get(
                "investigation_notes"
            ),
            limit=8,
        ),

        "market_data": sanitize_market_data(
            market_data
        ),

        "risk_data": risk_data,

        "stress_data": stress_data,

        "security_data": security_data,
    }



# ============================================================
# CRYPTORISK AI — BACKEND
# PART 3 / 3
# DASHBOARD → ANALYSIS → HISTORY → DELETE → LOGOUT → START
# ============================================================


# ============================================================
# DASHBOARD / MAIN ANALYSIS ENGINE
# ============================================================

@app.route(
    "/api/dashboard",
    methods=["GET", "POST", "OPTIONS"],
)
@app.route(
    "/dashboard",
    methods=["GET", "POST", "OPTIONS"],
)
@jwt_required(optional=True)
def dashboard():

    if request.method == "OPTIONS":
        return "", 204

    api_request = is_api_request()

    # --------------------------------------------------------
    # AUTHENTICATION
    # --------------------------------------------------------

    user_id = authenticated_user_id()

    if not user_id:

        if api_request:
            return jsonify(
                {
                    "success": False,
                    "authenticated": False,
                    "error": "Authentication required.",
                }
            ), 401

        return redirect(
            f"{FRONTEND_URL}/login"
        )

    user = get_user_by_id(
        user_id
    )

    if not user:

        session.pop(
            "user_id",
            None,
        )

        if api_request:
            return jsonify(
                {
                    "success": False,
                    "authenticated": False,
                    "error": "User account not found.",
                }
            ), 401

        return redirect(
            f"{FRONTEND_URL}/login"
        )

    # --------------------------------------------------------
    # GET = LOAD LATEST REPORT
    # POST = RUN NEW ANALYSIS
    # --------------------------------------------------------

    if request.method == "GET":

        try:
            connection = get_db_connection()
            cursor = connection.cursor()

            cursor.execute(
                """
                SELECT
                    id,
                    token_symbol,
                    trend,
                    risk_score,
                    predicted_price,
                    summary,
                    created_at
                FROM predictions
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 25
                """,
                (user_id,),
            )

            rows = cursor.fetchall()

            cursor.close()
            connection.close()

            history = []

            for row in rows:

                history.append(
                    {
                        "id": row[0],
                        "token_symbol": row[1],
                        "trend": row[2],
                        "risk_score": _bounded_score(
                            row[3],
                            50,
                        ),
                        "predicted_price": (
                            _numeric_value(
                                row[4],
                                0,
                            )
                        ),
                        "summary": row[5] or "",
                        "created_at": (
                            row[6].isoformat()
                            if row[6]
                            else None
                        ),
                    }
                )

            latest = (
                history[0]
                if history
                else None
            )

            latest_analysis = None

            if latest:

                latest_token = str(
                    latest.get(
                        "token_symbol",
                        "",
                    )
                ).upper()

                try:
                    latest_market = (
                        fetch_crypto_market_data(
                            latest_token
                        )
                    )

                    if not latest_market.get(
                        "market_data_available",
                        False,
                    ):
                        raise ValueError(
                            "Latest market data unavailable."
                        )

                    latest_risk = (
                        evaluate_risk_profile(
                            latest_market,
                            {},
                        )
                    )

                    btc_market = (
                        fetch_crypto_market_data(
                            "BTC"
                        )
                    )

                    btc_change = (
                        _numeric_value(
                            btc_market.get(
                                "price_change_percentage_7d",
                                0,
                            )
                        )
                    )

                    latest_stress = (
                        simulate_stress_test(
                            latest_market.get(
                                "price_change_percentage_7d",
                                0,
                            ),
                            btc_change,
                            -10,
                        )
                    )

                    latest_data = {
                        "autopsy_summary": (
                            latest.get(
                                "summary",
                                "",
                            )
                        ),
                        "predicted_price": (
                            latest.get(
                                "predicted_price",
                                latest_market.get(
                                    "current_price",
                                    0,
                                ),
                            )
                        ),
                    }

                    latest_analysis = (
                        normalize_report(
                            latest_data,
                            latest_token,
                            latest_market,
                            latest_risk,
                            latest_stress,
                            {},
                        )
                    )

                    # Preserve the historical database score
                    # only when it exists and is valid.
                    stored_score = _bounded_score(
                        latest.get(
                            "risk_score",
                            latest_analysis[
                                "risk_profile"
                            ]["composite_score"],
                        )
                    )

                    latest_analysis[
                        "risk_profile"
                    ][
                        "composite_score"
                    ] = stored_score

                    latest_analysis[
                        "id"
                    ] = latest.get("id")

                    latest_analysis[
                        "created_at"
                    ] = latest.get(
                        "created_at"
                    )

                except Exception:
                    logger.exception(
                        "Failed to hydrate latest report."
                    )

                    # Do not destroy the user's saved report
                    # just because live market data is temporarily
                    # unavailable.
                    latest_analysis = {
                        "token": latest_token,
                        "summary": latest.get(
                            "summary",
                            "",
                        ),
                        "autopsy_summary": latest.get(
                            "summary",
                            "",
                        ),
                        "predicted_price": (
                            latest.get(
                                "predicted_price",
                                0,
                            )
                        ),
                        "risk_profile": {
                            "composite_score": (
                                _bounded_score(
                                    latest.get(
                                        "risk_score",
                                        50,
                                    )
                                )
                            ),
                        },
                        "market_data": {
                            "market_data_available": False,
                            "data_source": "unavailable",
                        },
                        "autopsy": [],
                        "fatal_flaws": [],
                        "stress_test": {},
                        "stress_verdict": (
                            "Live market data temporarily unavailable."
                        ),
                        "id": latest.get("id"),
                        "created_at": latest.get(
                            "created_at"
                        ),
                    }

            response = {
                "success": True,
                "authenticated": True,
                "user": public_user_payload(
                    user
                ),
                "history": history,
                "latest_analysis": latest_analysis,
            }

            if api_request:
                return jsonify(
                    response
                ), 200

            return render_template(
                "dashboard.html",
                user=public_user_payload(
                    user
                ),
                history=history,
                latest_analysis=latest_analysis,
            )

        except Exception:
            logger.exception(
                "Dashboard GET failed."
            )

            if api_request:
                return jsonify(
                    {
                        "success": False,
                        "error": (
                            "Unable to load dashboard."
                        ),
                    }
                ), 500

            flash(
                "Unable to load dashboard.",
                "error",
            )

            return render_template(
                "dashboard.html",
                user=public_user_payload(
                    user
                ),
                history=[],
                latest_analysis=None,
            )

    # ========================================================
    # POST — NEW CRYPTO ANALYSIS
    # ========================================================

    data = request.get_json(
        silent=True
    )

    if not isinstance(
        data,
        dict,
    ):
        data = request.form.to_dict()

    token = str(
        data.get(
            "token",
            data.get(
                "symbol",
                data.get(
                    "ticker",
                    "",
                ),
            ),
        )
        or ""
    ).strip().upper()

    # --------------------------------------------------------
    # VALIDATION
    # --------------------------------------------------------

    if not token:

        return jsonify(
            {
                "success": False,
                "error": "Enter a cryptocurrency symbol.",
            }
        ), 400

    if (
        not re.fullmatch(
            r"[A-Z0-9]{2,15}",
            token,
        )
    ):

        return jsonify(
            {
                "success": False,
                "error": "Invalid cryptocurrency symbol.",
            }
        ), 400

    # --------------------------------------------------------
    # MARKET DATA
    # --------------------------------------------------------

    try:

        market_data = (
            fetch_crypto_market_data(
                token
            )
        )

    except Exception:
        logger.exception(
            "Market data request failed for %s.",
            token,
        )

        return jsonify(
            {
                "success": False,
                "error": (
                    "Unable to fetch market data."
                ),
            }
        ), 502

    if not market_data.get(
        "market_data_available",
        False,
    ):

        return jsonify(
            {
                "success": False,
                "error": (
                    f"Live market data for "
                    f"{token} is temporarily unavailable."
                ),
                "data_source": market_data.get(
                    "data_source",
                    "unavailable",
                ),
            }
        ), 503

    # --------------------------------------------------------
    # CONTRACT SECURITY
    # --------------------------------------------------------
    #
    # IMPORTANT:
    #
    # A ticker alone does not uniquely identify a smart
    # contract. Therefore we DO NOT invent a contract address
    # or incorrectly call GoPlus for native assets.
    #
    # If your frontend later supplies:
    #
    #   chain_id
    #   contract_address
    #
    # this section automatically supports GoPlus.
    # --------------------------------------------------------

    chain_id = str(
        data.get(
            "chain_id",
            "",
        )
        or ""
    ).strip()

    contract_address = str(
        data.get(
            "contract_address",
            "",
        )
        or ""
    ).strip()

    security_data = {}

    if (
        chain_id
        and contract_address
    ):

        security_data = (
            fetch_token_security(
                chain_id,
                contract_address,
            )
        )

    # --------------------------------------------------------
    # RISK ENGINE
    # --------------------------------------------------------

    risk_profile = evaluate_risk_profile(
        market_data,
        security_data,
    )

    # --------------------------------------------------------
    # BTC BENCHMARK
    # --------------------------------------------------------

    try:

        btc_market_data = (
            fetch_crypto_market_data(
                "BTC"
            )
        )

        btc_change_7d = (
            _numeric_value(
                btc_market_data.get(
                    "price_change_percentage_7d",
                    0,
                )
            )
        )

        btc_available = bool(
            btc_market_data.get(
                "market_data_available",
                False,
            )
        )

    except Exception:

        logger.exception(
            "BTC benchmark fetch failed."
        )

        btc_change_7d = 0.0
        btc_available = False

    # --------------------------------------------------------
    # STRESS TEST
    # --------------------------------------------------------

    stress_test = simulate_stress_test(
        market_data.get(
            "price_change_percentage_7d",
            0,
        ),
        btc_change_7d,
        -10.0,
    )

    stress_test[
        "benchmark_available"
    ] = btc_available and bool(
        stress_test.get(
            "benchmark_available",
            False,
        )
    )

    # --------------------------------------------------------
    # AI ANALYSIS
    # --------------------------------------------------------

    ai_data = {}

    if gemini_client:

        prompt = build_crypto_prompt(
            token,
            market_data,
            risk_profile,
            stress_test,
            security_data,
        )

        executor = ThreadPoolExecutor(
            max_workers=1
        )

        future = executor.submit(
            run_gemini_analysis,
            prompt,
        )

        try:

            ai_data = future.result(
                timeout=45
            )

        except FuturesTimeoutError:

            logger.warning(
                "Gemini analysis timed out for %s.",
                token,
            )

            future.cancel()

            ai_data = {}

        except Exception:

            logger.exception(
                "Gemini analysis failed for %s.",
                token,
            )

            ai_data = {}

        finally:

            try:
                executor.shutdown(
                    wait=False,
                    cancel_futures=True,
                )
            except TypeError:
                # Compatibility fallback for older Python.
                executor.shutdown(
                    wait=False
                )

    # --------------------------------------------------------
    # NORMALIZE REPORT
    # --------------------------------------------------------

    report = normalize_report(
        ai_data,
        token,
        market_data,
        risk_profile,
        stress_test,
        security_data,
    )

    report[
        "btc_benchmark"
    ] = {
        "change_7d": btc_change_7d,
        "change_7d_display": format_percentage(
            btc_change_7d
        ),
        "available": btc_available,
    }

    # --------------------------------------------------------
    # SAVE ANALYSIS
    # --------------------------------------------------------

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            INSERT INTO predictions (
                user_id,
                token_symbol,
                trend,
                risk_score,
                predicted_price,
                summary
            )
            VALUES (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            )
            RETURNING id, created_at
            """,
            (
                user_id,
                token,
                report.get(
                    "trend",
                    "Neutral",
                ),
                _bounded_score(
                    report.get(
                        "risk_profile",
                        {}
                    ).get(
                        "composite_score",
                        50,
                    )
                ),
                _numeric_value(
                    report.get(
                        "predicted_price",
                        market_data.get(
                            "current_price",
                            0,
                        ),
                    )
                ),
                report.get(
                    "summary",
                    "",
                ),
            ),
        )

        saved_row = cursor.fetchone()

        connection.commit()

    except Exception:

        if connection:
            connection.rollback()

        logger.exception(
            "Failed to save analysis."
        )

        return jsonify(
            {
                "success": False,
                "error": (
                    "Analysis completed, but "
                    "saving the report failed."
                ),
                "analysis": report,
            }
        ), 500

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()

    # --------------------------------------------------------
    # RESPONSE
    # --------------------------------------------------------

    report["id"] = (
        saved_row[0]
        if saved_row
        else None
    )

    report["created_at"] = (
        saved_row[1].isoformat()
        if saved_row and saved_row[1]
        else None
    )

    return jsonify(
        {
            "success": True,
            "message": "Analysis completed.",
            "analysis": report,
            "latest_analysis": report,
        }
    ), 200


# ============================================================
# HISTORY
# ============================================================

@app.route(
    "/api/history",
    methods=["GET", "OPTIONS"],
)
@jwt_required(optional=True)
def api_history():

    if request.method == "OPTIONS":
        return "", 204

    user_id = authenticated_user_id()

    if not user_id:
        return jsonify(
            {
                "success": False,
                "authenticated": False,
                "error": "Authentication required.",
            }
        ), 401

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                id,
                token_symbol,
                trend,
                risk_score,
                predicted_price,
                summary,
                created_at
            FROM predictions
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT 100
            """,
            (user_id,),
        )

        rows = cursor.fetchall()

        history = []

        for row in rows:

            history.append(
                {
                    "id": row[0],
                    "token_symbol": row[1],
                    "trend": row[2],
                    "risk_score": _bounded_score(
                        row[3],
                        50,
                    ),
                    "predicted_price": _numeric_value(
                        row[4],
                        0,
                    ),
                    "predicted_price_display": format_usd(
                        row[4]
                    ),
                    "summary": row[5] or "",
                    "created_at": (
                        row[6].isoformat()
                        if row[6]
                        else None
                    ),
                }
            )

        return jsonify(
            {
                "success": True,
                "history": history,
            }
        ), 200

    except Exception:

        logger.exception(
            "History fetch failed."
        )

        return jsonify(
            {
                "success": False,
                "error": "Unable to load history.",
            }
        ), 500

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# ============================================================
# DELETE SINGLE REPORT
# ============================================================

@app.route(
    "/api/history/<int:report_id>",
    methods=["DELETE", "POST", "OPTIONS"],
)
@jwt_required(optional=True)
def delete_history_report(
    report_id: int,
):

    if request.method == "OPTIONS":
        return "", 204

    user_id = authenticated_user_id()

    if not user_id:
        return jsonify(
            {
                "success": False,
                "error": "Authentication required.",
            }
        ), 401

    if report_id <= 0:
        return jsonify(
            {
                "success": False,
                "error": "Invalid report ID.",
            }
        ), 400

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            DELETE FROM predictions
            WHERE id = %s
              AND user_id = %s
            RETURNING id
            """,
            (
                report_id,
                user_id,
            ),
        )

        deleted = cursor.fetchone()

        if not deleted:

            connection.rollback()

            return jsonify(
                {
                    "success": False,
                    "error": "Report not found.",
                }
            ), 404

        connection.commit()

        return jsonify(
            {
                "success": True,
                "message": "Report deleted.",
                "id": report_id,
            }
        ), 200

    except Exception:

        if connection:
            connection.rollback()

        logger.exception(
            "Report deletion failed."
        )

        return jsonify(
            {
                "success": False,
                "error": "Unable to delete report.",
            }
        ), 500

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# ============================================================
# DELETE ALL REPORTS
# ============================================================

@app.route(
    "/api/history",
    methods=["DELETE"],
)
@jwt_required(optional=True)
def delete_all_history():

    user_id = authenticated_user_id()

    if not user_id:
        return jsonify(
            {
                "success": False,
                "error": "Authentication required.",
            }
        ), 401

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            DELETE FROM predictions
            WHERE user_id = %s
            """,
            (user_id,),
        )

        deleted_count = (
            cursor.rowcount
        )

        connection.commit()

        return jsonify(
            {
                "success": True,
                "message": "History cleared.",
                "deleted_count": deleted_count,
            }
        ), 200

    except Exception:

        if connection:
            connection.rollback()

        logger.exception(
            "Delete-all history failed."
        )

        return jsonify(
            {
                "success": False,
                "error": (
                    "Unable to clear history."
                ),
            }
        ), 500

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# ============================================================
# LEGACY DELETE REPORT COMPATIBILITY
# ============================================================

@app.route(
    "/delete-report",
    methods=["POST", "OPTIONS"],
)
@jwt_required(optional=True)
def delete_report_legacy():

    if request.method == "OPTIONS":
        return "", 204

    user_id = authenticated_user_id()

    if not user_id:

        if is_api_request():
            return jsonify(
                {
                    "success": False,
                    "error": "Authentication required.",
                }
            ), 401

        return redirect(
            f"{FRONTEND_URL}/login"
        )

    data = request.get_json(
        silent=True
    ) or request.form.to_dict()

    report_id = _numeric_value(
        data.get(
            "id",
            data.get(
                "report_id",
                0,
            ),
        ),
        0,
    )

    if report_id <= 0:

        return jsonify(
            {
                "success": False,
                "error": "Invalid report ID.",
            }
        ), 400

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            DELETE FROM predictions
            WHERE id = %s
              AND user_id = %s
            RETURNING id
            """,
            (
                int(report_id),
                user_id,
            ),
        )

        deleted = cursor.fetchone()

        if not deleted:

            connection.rollback()

            return jsonify(
                {
                    "success": False,
                    "error": "Report not found.",
                }
            ), 404

        connection.commit()

        return jsonify(
            {
                "success": True,
                "message": "Report deleted.",
                "id": int(report_id),
            }
        ), 200

    except Exception:

        if connection:
            connection.rollback()

        logger.exception(
            "Legacy report deletion failed."
        )

        return jsonify(
            {
                "success": False,
                "error": "Unable to delete report.",
            }
        ), 500

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# ============================================================
# LOGOUT
# ============================================================

@app.route(
    "/api/logout",
    methods=["POST", "GET", "OPTIONS"],
)
@jwt_required(optional=True)
def api_logout():

    if request.method == "OPTIONS":
        return "", 204

    session.pop(
        "user_id",
        None,
    )

    session.clear()

    return jsonify(
        {
            "success": True,
            "message": "Logged out successfully.",
        }
    ), 200


@app.route(
    "/logout",
    methods=["GET", "POST"],
)
@jwt_required(optional=True)
def logout():

    session.clear()

    if is_api_request():

        return jsonify(
            {
                "success": True,
                "message": "Logged out successfully.",
            }
        ), 200

    return redirect(
        f"{FRONTEND_URL}/login"
    )


# ============================================================
# ROOT
# ============================================================

@app.route(
    "/",
    methods=["GET"],
)
def index():

    # If the backend still serves its own landing page,
    # use index.html. Otherwise redirect to the frontend.
    try:

        return render_template(
            "index.html"
        )

    except Exception:

        return redirect(
            FRONTEND_URL
        )


# ============================================================
# 404 API HANDLER
# ============================================================

@app.errorhandler(404)
def handle_not_found(error):

    if is_api_request():

        return jsonify(
            {
                "success": False,
                "error": "Endpoint not found.",
            }
        ), 404

    return error


# ============================================================
# 405 API HANDLER
# ============================================================

@app.errorhandler(405)
def handle_method_not_allowed(error):

    if is_api_request():

        return jsonify(
            {
                "success": False,
                "error": "Method not allowed.",
            }
        ), 405

    return error


# ============================================================
# 500 API HANDLER
# ============================================================

@app.errorhandler(500)
def handle_internal_error(error):

    logger.exception(
        "Unhandled Flask error."
    )

    if is_api_request():

        return jsonify(
            {
                "success": False,
                "error": "Internal server error.",
            }
        ), 500

    return error


# ============================================================
# APPLICATION STARTUP
# ============================================================

if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            "5000",
        )
    )

    host = os.getenv(
        "HOST",
        "0.0.0.0",
    )

    debug = (
        os.getenv(
            "FLASK_DEBUG",
            "false",
        ).lower()
        == "true"
    )

    logger.info(
        "Starting CryptoRisk AI backend on %s:%s",
        host,
        port,
    )

    app.run(
        host=host,
        port=port,
        debug=debug,
    )


# ============================================================
# END OF APP.PY — PART 3 / 3
# ============================================================
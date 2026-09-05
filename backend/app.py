"""
CryptoRisk AI
Premium AI-powered cryptocurrency risk intelligence terminal.

Core responsibilities:
- Google OAuth authentication
- Secure Flask sessions
- PostgreSQL user + prediction storage
- Gemini structured cryptocurrency intelligence
- User-specific analysis history
- Report deletion
"""

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Lock
from typing import Any, Optional

import psycopg2
import psycopg2.extras
import requests
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    get_jwt_identity,
    jwt_required,
)
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    jsonify,
    url_for,
)
from google import genai
from google.genai import types
from werkzeug.security import check_password_hash, generate_password_hash


# ==========================================================
# ENVIRONMENT
# ==========================================================

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

SECRET_KEY = os.getenv("SECRET_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
FRONTEND_URL = os.getenv("FRONTEND_URL", "").rstrip("/")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", SECRET_KEY)


required_environment = {
    "SECRET_KEY": SECRET_KEY,
    "DATABASE_URL": DATABASE_URL,
    "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID,
    "GOOGLE_CLIENT_SECRET": GOOGLE_CLIENT_SECRET,
}


for variable_name, variable_value in required_environment.items():
    if not variable_value:
        raise ValueError(
            f"{variable_name} is missing. "
            "Please add it to your .env file."
        )


# ==========================================================
# LOGGING
# ==========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


# ==========================================================
# MARKET DATA
# ==========================================================

COINGECKO_API_URL = "https://api.coingecko.com/api/v3"
COINGECKO_REQUEST_TIMEOUT = 10
COINGECKO_TICKER_MAP = {
    "btc": "bitcoin",
    "eth": "ethereum",
    "sol": "solana",
    "usdt": "tether",
    "usdc": "usd-coin",
    "bnb": "binancecoin",
    "xrp": "ripple",
    "ada": "cardano",
    "doge": "dogecoin",
}
MARKET_DATA_DEFAULTS = {
    "price": 0.0,
    "price_change_percentage_24h": 0.0,
    "change_24h": 0.0,
    "volume": 0.0,
    "market_cap": 0.0,
    "symbol": "N/A",
    "ticker": "N/A",
    "current_price_usd": 0.0,
    "volume_24h_usd": 0.0,
    "market_cap_usd": 0.0,
    "price_change_percentage_7d": 0.0,
}


def sanitize_market_data(market_data: Any) -> dict[str, Any]:
    """Return a complete dictionary safe for scoring, templates, and prompts."""

    sanitized_data = dict(market_data) if isinstance(market_data, dict) else {}

    for key, default_value in MARKET_DATA_DEFAULTS.items():
        sanitized_data.setdefault(key, default_value)

    for numeric_key in (
        "price",
        "price_change_percentage_24h",
        "change_24h",
        "volume",
        "market_cap",
        "current_price_usd",
        "volume_24h_usd",
        "market_cap_usd",
        "price_change_percentage_7d",
    ):
        try:
            sanitized_data[numeric_key] = float(
                sanitized_data.get(
                    numeric_key,
                    MARKET_DATA_DEFAULTS[numeric_key],
                )
                or 0.0
            )
        except (TypeError, ValueError):
            sanitized_data[numeric_key] = MARKET_DATA_DEFAULTS[numeric_key]

    sanitized_data["price_change_percentage_24h"] = sanitized_data.get(
        "price_change_percentage_24h",
        sanitized_data.get("change_24h", 0.0),
    ) or 0.0
    sanitized_data["change_24h"] = sanitized_data.get(
        "change_24h",
        sanitized_data["price_change_percentage_24h"],
    ) or 0.0
    sanitized_data["symbol"] = sanitized_data.get(
        "symbol",
        sanitized_data.get("ticker", "N/A"),
    ) or "N/A"
    sanitized_data["ticker"] = sanitized_data.get(
        "ticker",
        sanitized_data["symbol"],
    ) or "N/A"

    return sanitized_data


def format_percentage(value: Any) -> str:
    """Format a numeric percentage to exactly two decimal places."""

    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "N/A"


def format_usd(value: Any) -> str:
    """Format USD values using readable K, M, or B notation."""

    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "N/A"

    absolute_amount = abs(amount)

    if absolute_amount >= 1_000_000_000:
        return f"${amount / 1_000_000_000:.2f}B"
    if absolute_amount >= 1_000_000:
        return f"${amount / 1_000_000:.2f}M"
    if absolute_amount >= 1_000:
        return f"${amount / 1_000:.2f}K"

    return f"${amount:,.2f}"


def format_market_data_for_display(
    market_data: dict[str, Any],
) -> dict[str, Any]:
    """Create display-safe market metrics without changing numeric source data."""

    market_data = sanitize_market_data(market_data)

    return {
        **market_data,
        "current_price_display": format_usd(
            market_data.get("current_price_usd")
        ),
        "volume_24h_display": format_usd(
            market_data.get("volume_24h_usd")
        ),
        "market_cap_display": format_usd(
            market_data.get("market_cap_usd")
        ),
        "price_change_percentage_24h_display": format_percentage(
            market_data.get("price_change_percentage_24h")
        ),
        "price_change_percentage_7d_display": format_percentage(
            market_data.get("price_change_percentage_7d")
        ),
    }


def fetch_crypto_market_data(
    ticker: str,
) -> dict[str, Any]:
    """Fetch current CoinGecko market data for an exact ticker symbol."""

    if not isinstance(ticker, str):
        return sanitize_market_data({})

    normalized_ticker = ticker.strip().lower()

    if not re.fullmatch(
        r"[a-z0-9][a-z0-9._-]{0,19}",
        normalized_ticker,
    ):
        return sanitize_market_data({"symbol": ticker.upper()})

    try:
        coin_id = COINGECKO_TICKER_MAP.get(normalized_ticker)

        if not coin_id:
            search_response = requests.get(
                f"{COINGECKO_API_URL}/search",
                params={"query": normalized_ticker},
                timeout=COINGECKO_REQUEST_TIMEOUT,
            )

            if search_response.status_code == 429:
                logger.warning("CoinGecko rate limit reached during ticker search.")
                return sanitize_market_data({"symbol": normalized_ticker.upper()})

            search_response.raise_for_status()
            search_payload = search_response.json()

            if not isinstance(search_payload, dict):
                return sanitize_market_data({"symbol": normalized_ticker.upper()})

            matching_coin = next(
                (
                    coin
                    for coin in search_payload.get("coins", [])
                    if isinstance(coin, dict)
                    and str(coin.get("symbol", "")).lower()
                    == normalized_ticker
                    and coin.get("id")
                ),
                None,
            )

            coin_id = matching_coin["id"] if matching_coin else None

        if not coin_id:
            return sanitize_market_data({"symbol": normalized_ticker.upper()})

        market_response = requests.get(
            f"{COINGECKO_API_URL}/coins/markets",
            params={
                "vs_currency": "usd",
                "ids": coin_id,
                "price_change_percentage": "7d",
            },
            timeout=COINGECKO_REQUEST_TIMEOUT,
        )

        if market_response.status_code == 429:
            logger.warning("CoinGecko rate limit reached during market lookup.")
            return sanitize_market_data({"symbol": normalized_ticker.upper()})

        market_response.raise_for_status()
        market_payload = market_response.json()

        if not isinstance(market_payload, list) or not market_payload:
            return sanitize_market_data({"symbol": normalized_ticker.upper()})

        market_data = market_payload[0]
        required_fields = {
            "current_price": "current_price_usd",
            "total_volume": "volume_24h_usd",
            "price_change_percentage_24h": "price_change_percentage_24h",
            "price_change_percentage_7d_in_currency": "price_change_percentage_7d",
            "market_cap": "market_cap_usd",
        }

        if not isinstance(market_data, dict) or any(
            market_data.get(source_field) is None
            for source_field in required_fields
        ):
            return sanitize_market_data({"symbol": normalized_ticker.upper()})

        return sanitize_market_data({
            "ticker": normalized_ticker.upper(),
            "symbol": normalized_ticker.upper(),
            "coin_id": coin_id,
            "high_24h_usd": market_data.get("high_24h"),
            "low_24h_usd": market_data.get("low_24h"),
            **{
                output_field: float(market_data[source_field])
                for source_field, output_field in required_fields.items()
            },
        })

    except requests.Timeout:
        logger.warning("CoinGecko request timed out for ticker %s.", normalized_ticker)
        return sanitize_market_data({"symbol": normalized_ticker.upper()})
    except requests.RequestException:
        logger.exception(
            "CoinGecko market data request failed for ticker %s.",
            normalized_ticker,
        )
        return sanitize_market_data({"symbol": normalized_ticker.upper()})
    except (ValueError, TypeError, KeyError):
        logger.exception(
            "CoinGecko market data request failed for ticker %s.",
            normalized_ticker,
        )
        return sanitize_market_data({"symbol": normalized_ticker.upper()})


GOPLUS_API_URL = "https://api.gopluslabs.io/api/v1/token_security"


def _goplus_bool(value: Any) -> bool:
    """Normalize GoPlus boolean fields, which are commonly returned as strings."""

    return str(value).strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _goplus_tax_percentage(value: Any) -> float:
    """Normalize GoPlus tax ratios or percentages into a percentage value."""

    tax_value = float(value)

    if 0 <= tax_value <= 1:
        return tax_value * 100

    return tax_value


def fetch_token_security(
    chain_id: str,
    contract_address: str,
) -> Optional[dict[str, Any]]:
    """Fetch and summarize GoPlus token security details."""

    if not isinstance(chain_id, str) or not re.fullmatch(
        r"[0-9]+",
        chain_id.strip(),
    ):
        return None

    if not isinstance(contract_address, str):
        return None

    normalized_chain_id = chain_id.strip()
    normalized_address = contract_address.strip()

    if not normalized_address or len(normalized_address) > 200:
        return None

    try:
        response = requests.get(
            f"{GOPLUS_API_URL}/{normalized_chain_id}",
            params={"contract_addresses": normalized_address},
            timeout=COINGECKO_REQUEST_TIMEOUT,
        )

        if response.status_code == 429:
            logger.warning("GoPlus rate limit reached for token security lookup.")
            return None

        response.raise_for_status()
        payload = response.json()

        if not isinstance(payload, dict) or payload.get("code") != 1:
            return None

        results = payload.get("result")

        if not isinstance(results, dict) or not results:
            return None

        security_data = next(
            (
                value
                for key, value in results.items()
                if str(key).lower() == normalized_address.lower()
                and isinstance(value, dict)
            ),
            None,
        )

        if security_data is None:
            security_data = next(
                (
                    value
                    for value in results.values()
                    if isinstance(value, dict)
                ),
                None,
            )

        if security_data is None:
            return None

        buy_tax = _goplus_tax_percentage(security_data.get("buy_tax", 0))
        sell_tax = _goplus_tax_percentage(security_data.get("sell_tax", 0))
        is_honeypot = _goplus_bool(security_data.get("is_honeypot", 0))
        cannot_sell_all = _goplus_bool(
            security_data.get("cannot_sell_all", 0)
        )

        warnings = []

        if buy_tax > 10:
            warnings.append(
                f"Buy tax is high at {buy_tax:g}% (above 10%)."
            )

        if sell_tax > 10:
            warnings.append(
                f"Sell tax is high at {sell_tax:g}% (above 10%)."
            )

        if is_honeypot:
            warnings.append(
                "GoPlus flags this token as a potential honeypot."
            )

        if cannot_sell_all:
            warnings.append(
                "GoPlus indicates that the token may not be fully sellable."
            )

        return {
            "chain_id": normalized_chain_id,
            "contract_address": normalized_address,
            "is_honeypot": is_honeypot,
            "buy_tax": buy_tax,
            "sell_tax": sell_tax,
            "cannot_sell_all": cannot_sell_all,
            "is_open_source": _goplus_bool(
                security_data.get("is_open_source", 0)
            ),
            "warnings": warnings,
        }

    except (requests.RequestException, ValueError, TypeError, KeyError):
        logger.exception(
            "GoPlus token security request failed for chain %s and address %s.",
            normalized_chain_id,
            normalized_address,
        )
        return None


def _bounded_score(value: float) -> int:
    """Return a score constrained to the public 0-100 range."""

    return max(0, min(100, int(round(value))))


def _numeric_value(data: dict[str, Any], *keys: str) -> float:
    """Read the first usable numeric value from a payload."""

    for key in keys:
        try:
            value = data.get(key)
            if value is not None:
                return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def evaluate_risk_profile(
    market_data: dict[str, Any],
    security_data: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Decompose asset risk into volatility, liquidity, and contract pillars."""

    market_data = sanitize_market_data(market_data)
    security_data = security_data if isinstance(security_data, dict) else {}

    change_7d = abs(_numeric_value(
        market_data,
        "change_7d",
        "price_change_percentage_7d",
    ))
    change_24h = abs(_numeric_value(
        market_data,
        "change_24h",
        "price_change_percentage_24h",
    ))
    high_24h = _numeric_value(market_data, "high_24h_usd", "high_24h")
    low_24h = _numeric_value(market_data, "low_24h_usd", "low_24h")
    current_price = _numeric_value(market_data, "current_price_usd", "price")
    range_percentage = (
        ((high_24h - low_24h) / current_price) * 100
        if current_price > 0 and high_24h >= low_24h > 0
        else change_24h
    )

    volatility_risk = _bounded_score(
        (change_7d * 2.5) + (abs(range_percentage) * 1.5)
    )

    volume = _numeric_value(market_data, "volume_24h_usd", "volume")
    market_cap = _numeric_value(market_data, "market_cap_usd", "market_cap")
    turnover = volume / market_cap if market_cap > 0 else 0.0

    if turnover < 0.02:
        liquidity_risk = _bounded_score(100 - (turnover / 0.02 * 30))
    elif turnover >= 0.10:
        liquidity_risk = _bounded_score(max(0, 30 - (turnover - 0.10) * 100))
    else:
        liquidity_risk = _bounded_score(
            70 - ((turnover - 0.02) / 0.08 * 40)
        )

    ticker = str(
        market_data.get("ticker", market_data.get("symbol", ""))
    ).lower()
    native_l1s = {"btc", "bitcoin", "eth", "ethereum", "sol", "solana"}

    if _goplus_bool(security_data.get("is_honeypot", False)):
        contract_risk = 100
    else:
        buy_tax = _numeric_value(security_data, "buy_tax")
        sell_tax = _numeric_value(security_data, "sell_tax")
        contract_risk = (
            15
            if ticker in native_l1s and not security_data
            else min(100, 15 + (buy_tax + sell_tax) * 4)
        )
        if _goplus_bool(security_data.get("cannot_sell_all", False)):
            contract_risk = max(contract_risk, 90)
        if security_data and not _goplus_bool(
            security_data.get("is_open_source", True)
        ):
            contract_risk += 15

    composite_score = _bounded_score(
        volatility_risk * 0.35
        + liquidity_risk * 0.35
        + contract_risk * 0.30
    )

    return {
        "volatility_risk": volatility_risk,
        "liquidity_risk": liquidity_risk,
        "contract_risk": _bounded_score(contract_risk),
        "composite_score": composite_score,
        "turnover_ratio": turnover,
        "range_percentage": range_percentage,
    }


def calculate_risk_score(
    market_data: dict[str, Any],
    security_data: Optional[dict[str, Any]] = None,
) -> int:
    """Compatibility wrapper returning the decomposed composite score."""

    return evaluate_risk_profile(market_data, security_data)["composite_score"]


def simulate_stress_test(
    asset_change_7d: float,
    btc_change_7d: float,
    shock_pct: float = -10.0,
) -> dict[str, Any]:
    """Estimate asset drawdown under a BTC-linked market shock."""

    try:
        asset_change = float(asset_change_7d)
        btc_change = float(btc_change_7d)
        shock = float(shock_pct)
    except (TypeError, ValueError):
        asset_change, btc_change, shock = 0.0, 0.0, -10.0

    raw_beta = asset_change / btc_change if btc_change else 1.0
    beta = max(0.5, min(3.0, raw_beta))
    expected_drawdown = shock * beta

    return {
        "simulated_shock": shock,
        "beta": round(beta, 2),
        "expected_drawdown": round(expected_drawdown, 2),
        "resilience_label": (
            "Fragile"
            if beta > 1.4
            else "Resilient"
            if beta < 0.9
            else "Moderate"
        ),
    }


# ==========================================================
# FLASK
# ==========================================================

app = Flask(__name__)

CORS(
    app,
    resources={r"/api/*": {"origins": FRONTEND_URL or "*"}},
    supports_credentials=bool(FRONTEND_URL),
)

app.secret_key = SECRET_KEY
app.config["JWT_SECRET_KEY"] = JWT_SECRET_KEY
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = 60 * 60 * 24 * 7
JWTManager(app)

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = bool(FRONTEND_URL)


def frontend_location(path: str = "") -> str:
    """Return a frontend URL when the UI is deployed separately."""

    if FRONTEND_URL:
        return f"{FRONTEND_URL}/{path.lstrip('/')}" if path else FRONTEND_URL

    return url_for("home")


# For production HTTPS:
# app.config["SESSION_COOKIE_SECURE"] = True


# ==========================================================
# GEMINI
# ==========================================================

client = None

if GEMINI_API_KEY:
    client = genai.Client(
        api_key=GEMINI_API_KEY
    )
else:
    logger.warning(
        "GEMINI_API_KEY is not configured."
    )


# ==========================================================
# GOOGLE OAUTH
# ==========================================================

oauth = OAuth(app)

google = oauth.register(
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


# ==========================================================
# DATABASE
# ==========================================================

def get_db():
    """
    Open a PostgreSQL connection.
    """

    try:
        return psycopg2.connect(
            DATABASE_URL,
            cursor_factory=psycopg2.extras.RealDictCursor,
            connect_timeout=5,
        )

    except Exception:
        logger.exception(
            "PostgreSQL connection failed."
        )

        return None


def init_db():
    """
    Create or upgrade required database tables.
    """

    connection = get_db()

    if not connection:
        logger.warning(
            "Database initialization skipped."
        )
        return False

    cursor = connection.cursor()

    try:

        # --------------------------------------------------
        # USERS
        # --------------------------------------------------

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT,
                google_id TEXT UNIQUE,
                name TEXT,
                picture TEXT
            )
            """
        )

        # --------------------------------------------------
        # PREDICTIONS
        # --------------------------------------------------

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS predictions (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                token_symbol TEXT NOT NULL,
                trend TEXT NOT NULL,
                risk_score TEXT NOT NULL,
                predicted_price TEXT,
                summary TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id)
                    REFERENCES users(id)
                    ON DELETE CASCADE
            )
            """
        )

        # --------------------------------------------------
        # COMPATIBILITY COLUMNS
        # --------------------------------------------------

        cursor.execute(
            """
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS google_id TEXT UNIQUE
            """
        )

        cursor.execute(
            """
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS name TEXT
            """
        )

        cursor.execute(
            """
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS picture TEXT
            """
        )

        cursor.execute(
            """
            ALTER TABLE users
            ALTER COLUMN password DROP NOT NULL
            """
        )

        connection.commit()

        logger.info(
            "Database initialized successfully."
        )

        return True

    except Exception:

        connection.rollback()

        logger.exception(
            "Database initialization failed."
        )

        return False

    finally:

        cursor.close()
        connection.close()


# ==========================================================
# GOOGLE AUTHENTICATION
# ==========================================================

@app.route("/auth/google", methods=["GET"])
def google_login():

    if "user_id" in session:
        return redirect(
            frontend_location("dashboard.html")
        )

    redirect_uri = url_for(
        "google_callback",
        _external=True,
    )

    return google.authorize_redirect(
        redirect_uri
    )


@app.route("/auth/google/callback")
def google_callback():

    try:

        token = google.authorize_access_token()

        user_info = token.get("userinfo")

        if not user_info:
            user_info = google.userinfo()

        if not user_info:

            flash(
                "Unable to retrieve your Google account information.",
                "danger",
            )

            return redirect(
                url_for("home")
            )

        google_id = user_info.get("sub")
        email = user_info.get("email")
        name = user_info.get("name")
        picture = user_info.get("picture")

        if not google_id or not email:

            flash(
                "Google did not provide the required account information.",
                "danger",
            )

            return redirect(
                url_for("home")
            )

        email = email.lower().strip()

        username = (
            name.strip()
            if name and name.strip()
            else email.split("@")[0]
        )

        connection = get_db()

        if not connection:

            flash(
                "Database is currently unavailable.",
                "danger",
            )

            return redirect(
                url_for("home")
            )

        cursor = connection.cursor()

        try:

            # --------------------------------------------------
            # FIND BY GOOGLE ID
            # --------------------------------------------------

            cursor.execute(
                """
                SELECT *
                FROM users
                WHERE google_id = %s
                """,
                (google_id,),
            )

            user = cursor.fetchone()

            if user:

                user_id = user["id"]

                cursor.execute(
                    """
                    UPDATE users
                    SET
                        username = %s,
                        name = %s,
                        picture = %s,
                        email = %s
                    WHERE id = %s
                    """,
                    (
                        username,
                        name,
                        picture,
                        email,
                        user_id,
                    ),
                )

            else:

                # --------------------------------------------------
                # FIND BY EMAIL
                # --------------------------------------------------

                cursor.execute(
                    """
                    SELECT *
                    FROM users
                    WHERE email = %s
                    """,
                    (email,),
                )

                existing_user = cursor.fetchone()

                if existing_user:

                    user_id = existing_user["id"]

                    cursor.execute(
                        """
                        UPDATE users
                        SET
                            google_id = %s,
                            username = %s,
                            name = %s,
                            picture = %s
                        WHERE id = %s
                        """,
                        (
                            google_id,
                            username,
                            name,
                            picture,
                            user_id,
                        ),
                    )

                else:

                    # --------------------------------------------------
                    # CREATE USER
                    # --------------------------------------------------

                    cursor.execute(
                        """
                        INSERT INTO users (
                            username,
                            email,
                            password,
                            google_id,
                            name,
                            picture
                        )
                        VALUES (
                            %s,
                            %s,
                            NULL,
                            %s,
                            %s,
                            %s
                        )
                        RETURNING id
                        """,
                        (
                            username,
                            email,
                            google_id,
                            name,
                            picture,
                        ),
                    )

                    new_user = cursor.fetchone()

                    user_id = new_user["id"]

            connection.commit()

            session.clear()

            session["user_id"] = user_id
            session["username"] = username
            session["email"] = email
            session["name"] = name or username
            session["picture"] = picture or ""

            logger.info(
                "Google authentication successful: %s",
                email,
            )

            return redirect(
                frontend_location("dashboard.html")
            )

        except Exception:

            connection.rollback()

            logger.exception(
                "Google user database operation failed."
            )

            flash(
                "Unable to complete Google sign-in.",
                "danger",
            )

            return redirect(
                frontend_location()
            )

        finally:

            cursor.close()
            connection.close()

    except Exception:

        logger.exception(
            "Google OAuth authentication failed."
        )

        flash(
            "Google sign-in failed. Please try again.",
            "danger",
        )

        return redirect(
            frontend_location()
        )


# ==========================================================
# HOME
# ==========================================================

@app.route("/")
def home():

    if "user_id" in session:
        return redirect(
            frontend_location("dashboard.html")
        )

    return render_template("index.html")


# ==========================================================
# COMPATIBILITY ROUTES
# ==========================================================

@app.route("/register")
def register():

    if "user_id" in session:
        return redirect(
            url_for("dashboard")
        )

    return redirect(
        url_for("google_login")
    )


# ==========================================================
# AI PROMPT
# ==========================================================

def build_crypto_prompt(
    market_data: dict[str, Any],
    security_data: dict[str, Any],
    risk_profile: dict[str, Any],
    stress_test: dict[str, Any],
) -> str:
    """Build the forensic quantitative risk-autopsy instruction."""

    market_data = sanitize_market_data(market_data)
    security_data = security_data if isinstance(security_data, dict) else {}

    asset = market_data.get("ticker", "unknown asset")
    current_price = market_data.get("current_price_usd", "not supplied")
    volume_24h = market_data.get("volume_24h_usd", "not supplied")
    volatility = round(float(market_data.get(
        "volatility_percentage",
        market_data.get(
            "price_change_percentage_24h",
            "not supplied",
        ),
    )), 2)
    buy_tax = security_data.get("buy_tax", "not supplied")
    sell_tax = security_data.get("sell_tax", "not supplied")
    is_honeypot = security_data.get("is_honeypot", "not supplied")
    cannot_sell_all = security_data.get("cannot_sell_all", "not supplied")
    is_open_source = security_data.get("is_open_source", "not supplied")
    score = risk_profile["composite_score"]
    radar = {
        "volatility": risk_profile["volatility_risk"],
        "liquidity": risk_profile["liquidity_risk"],
        "contract": risk_profile["contract_risk"],
    }

    return f"""
SYSTEM INSTRUCTION

Act strictly as an elite quantitative risk analyst performing a Risk Autopsy.
Be blunt, forensic, and specific. Do not explain beginner concepts, market
volatility in generic terms, or add financial disclaimers.

LIVE EVIDENCE

Asset: {asset}
Current price USD: {current_price}
24h volume USD: {volume_24h}
24h price change percent: {volatility}
Buy tax percent: {buy_tax}
Sell tax percent: {sell_tax}
Honeypot flag: {is_honeypot}
Cannot sell all flag: {cannot_sell_all}
Open-source flag: {is_open_source}

DECOMPOSED RISK PROFILE

Volatility risk: {radar['volatility']}/100
Liquidity risk: {radar['liquidity']}/100
Contract risk: {radar['contract']}/100
Composite score: {score}/100
Turnover ratio: {risk_profile.get('turnover_ratio', 0):.4f}

DOWNSIDE STRESS TEST

BTC shock: {stress_test['simulated_shock']:.2f}%
Historical beta: {stress_test['beta']:.2f}x
Expected drawdown: {stress_test['expected_drawdown']:.2f}%
Resilience label: {stress_test['resilience_label']}

RULES

- Use only the evidence above and cite exact numerical metrics.
- Repeat the exact injected values for composite score, pillar scores, beta,
    and expected drawdown. Do not round or substitute them differently.
- Card 1 must discuss Momentum & Drawdown Risk using the exact 24h change,
    7d change, and volatility score.
- Card 2 must discuss Liquidity Depth & Slippage Risk using the exact turnover
    ratio and liquidity score ({radar['liquidity']}/100).
- Card 3 must discuss Macro & Contract Sensitivity using the exact beta,
    expected drawdown, composite score ({score}/100), and contract flags.
- Never use fallback values such as 1.00x beta, 50/100 score, or -10.00%
    when the injected values above are present.
- fatal_flaws must contain exactly three bullets, each citing a different
    injected number or score.
- Never say data is unavailable, context is limited, or crypto is volatile.
- Do not invent news, prices, causes, or security findings.

Return ONLY valid JSON with exactly this schema:

{{
    "autopsy_summary": "Exactly two blunt sentences explaining how this asset could harm a holder today.",
    "fatal_flaws": [
        "Exactly one structural risk with an explicit numerical citation.",
        "Exactly one structural risk with an explicit numerical citation.",
        "Exactly one structural risk with an explicit numerical citation."
    ],
    "stress_verdict": "A concise evaluation of the asset under the BTC shock using beta and expected drawdown."
}}
"""


# ==========================================================
# JSON CLEANING
# ==========================================================

def extract_json(text):

    if not text:

        raise ValueError(
            "Gemini returned an empty response."
        )

    cleaned = text.strip()

    cleaned = re.sub(
        r"^```(?:json)?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"\s*```$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = cleaned.strip()

    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")

    if (
        first_brace != -1
        and last_brace != -1
        and last_brace > first_brace
    ):

        cleaned = cleaned[
            first_brace:last_brace + 1
        ]

    return json.loads(cleaned)


# ==========================================================
# NORMALIZE AI REPORT
# ==========================================================

FORBIDDEN_AI_PHRASES = (
    "live price, volume, and liquidity data are unavailable",
    "the available context is limited",
)


def _is_generic_ai_disclaimer(value: str) -> bool:
    """Detect boilerplate that must never reach the risk report."""

    normalized_value = value.lower()
    return any(
        phrase in normalized_value
        for phrase in FORBIDDEN_AI_PHRASES
    )

def normalize_report(
    data: dict[str, Any],
    token_symbol: str,
    market_data: Optional[dict[str, Any]] = None,
    risk_profile: Optional[dict[str, Any]] = None,
    stress_test: Optional[dict[str, Any]] = None,
    security_data: Optional[dict[str, Any]] = None,
):

    if not isinstance(data, dict):

        raise ValueError(
            "Invalid AI response structure."
        )

    allowed_trends = {
        "bullish": "Bullish",
        "bearish": "Bearish",
        "neutral": "Neutral",
    }

    allowed_risks = {
        "low": "Low",
        "medium": "Medium",
        "high": "High",
        "extreme": "Extreme",
    }

    trend_raw = str(
        data.get(
            "trend",
            "Neutral",
        )
    ).strip().lower()

    risk_raw = str(
        data.get(
            "risk_score",
            "Medium",
        )
    ).strip().lower()

    trend = allowed_trends.get(
        trend_raw,
        "Neutral",
    )

    risk_score = allowed_risks.get(
        risk_raw,
        "Medium",
    )

    market_data = sanitize_market_data(market_data)
    risk_profile = risk_profile if isinstance(risk_profile, dict) else {}
    stress_test = stress_test if isinstance(stress_test, dict) else {}
    security_data = security_data if isinstance(security_data, dict) else {}
    current_price = market_data.get("current_price_usd", 0)
    volume_24h = market_data.get("volume_24h_usd", 0)
    change_24h = market_data.get("price_change_percentage_24h", 0)

    composite_score = int(risk_profile.get("composite_score", 50))
    risk_score = (
        "Extreme" if composite_score >= 80
        else "High" if composite_score >= 65
        else "Medium" if composite_score >= 35
        else "Low"
    )

    autopsy_summary = str(
        data.get(
            "autopsy_summary",
            data.get(
                "executive_summary",
                data.get(
                    "summary",
                f"Price is {format_usd(current_price)}, with 24h volume of "
                f"{format_usd(volume_24h)} and a 24h move of "
                f"{format_percentage(change_24h)}.",
                ),
            ),
        )
    ).strip()

    if _is_generic_ai_disclaimer(autopsy_summary):
        autopsy_summary = (
            f"Price is {format_usd(current_price)}, with 24h volume of "
            f"{format_usd(volume_24h)} and a 24h move of "
            f"{format_percentage(change_24h)}."
        )

    market_conditions = str(
        data.get(
            "market_conditions",
            "",
        )
    ).strip()

    if _is_generic_ai_disclaimer(market_conditions):
        market_conditions = ""

    if market_conditions:
        autopsy_summary = f"{autopsy_summary} {market_conditions}".strip()

    stress_verdict = str(
        data.get(
            "stress_verdict",
            data.get(
                "signal_to_remember",
                f"A {stress_test.get('simulated_shock', -10.0):.2f}% BTC shock "
                f"implies a {stress_test.get('expected_drawdown', -10.0):.2f}% "
                f"drawdown at {stress_test.get('beta', 1.0):.2f}x beta.",
            ),
        )
    ).strip()

    if _is_generic_ai_disclaimer(stress_verdict):
        stress_verdict = (
            f"The stress test estimates a {stress_test.get('expected_drawdown', -10.0):.2f}% "
            "drawdown under the modeled BTC shock."
        )

    key_insight = stress_verdict

    raw_factors = data.get("fatal_flaws")
    if raw_factors is None:
        raw_factors = data.get(
            "what_is_driving_risk",
            data.get("top_risk_drivers", data.get("risk_factors", [])),
        )

    if isinstance(raw_factors, str):
        raw_factors = [raw_factors]

    risk_factors = []
    if isinstance(raw_factors, list):
        risk_factors = [
            str(item).strip()
            for item in raw_factors[:3]
            if str(item).strip()
            and not _is_generic_ai_disclaimer(str(item).strip())
        ]

    if not risk_factors:
        risk_factors = [
            f"Price is {format_usd(current_price)} and the 24h move is "
            f"{format_percentage(change_24h)}.",
            f"24h trading volume is {format_usd(volume_24h)}; compare it "
            "with market capitalization when assessing liquidity.",
            f"Composite risk is {composite_score}/100 with liquidity risk at "
            f"{risk_profile.get('liquidity_risk', 0)}/100.",
        ]

    problem_solved = str(
        data.get(
            "problem_solved",
            "CryptoRisk AI organizes complex cryptocurrency risk information into a concise intelligence report.",
        )
    ).strip()

    predicted_price = str(
        data.get(
            "predicted_price",
            format_usd(current_price),
        )
    ).strip()

    # ------------------------------------------------------
    # RISKS
    # ------------------------------------------------------

    raw_risks = data.get(
        "key_risks",
        data.get("fatal_flaws", data.get("top_risk_drivers", [])),
    )

    key_risks = []

    if isinstance(raw_risks, list):

        for item in raw_risks[:3]:

            if isinstance(item, str):
                explanation = item.strip()
                if explanation and not _is_generic_ai_disclaimer(explanation):
                    key_risks.append(
                        {
                            "title": "Quantified risk driver",
                            "explanation": explanation,
                        }
                    )

            elif isinstance(item, dict):

                title = str(
                    item.get(
                        "title",
                        "Risk factor",
                    )
                ).strip()

                explanation = str(
                    item.get(
                        "explanation",
                        "",
                    )
                ).strip()

                if title and explanation:

                    if _is_generic_ai_disclaimer(explanation):
                        continue

                    key_risks.append(
                        {
                            "title": title,
                            "explanation": explanation,
                        }
                    )

    # ------------------------------------------------------
    # SIGNALS
    # ------------------------------------------------------

    raw_signals = data.get(
        "key_signals",
        data.get("signal_to_remember", []),
    )

    if isinstance(raw_signals, str):
        raw_signals = [raw_signals]

    key_signals = []

    if isinstance(raw_signals, list):

        for item in raw_signals[:3]:

            if isinstance(item, str):
                explanation = item.strip()
                if explanation and not _is_generic_ai_disclaimer(explanation):
                    key_signals.append(
                        {
                            "title": "Quantified market signal",
                            "explanation": explanation,
                        }
                    )

            elif isinstance(item, dict):

                title = str(
                    item.get(
                        "title",
                        "Market signal",
                    )
                ).strip()

                explanation = str(
                    item.get(
                        "explanation",
                        "",
                    )
                ).strip()

                if title and explanation:

                    if _is_generic_ai_disclaimer(explanation):
                        continue

                    key_signals.append(
                        {
                            "title": title,
                            "explanation": explanation,
                        }
                    )

    # ------------------------------------------------------
    # WATCH NEXT
    # ------------------------------------------------------

    raw_watch = data.get(
        "watch_next",
        [],
    )

    watch_next = []

    if isinstance(raw_watch, list):

        for item in raw_watch[:3]:

            item_text = str(item).strip()

            if item_text:
                watch_next.append(
                    item_text
                )

    # ------------------------------------------------------
    # FALLBACK RISKS
    # ------------------------------------------------------

    if not key_risks:

        key_risks = [

            {
                "title": "Price movement",
                "explanation":
                    f"The asset moved {format_percentage(change_24h)} over 24 hours "
                    f"at a reference price of {format_usd(current_price)}."
            },

            {
                "title": "Trading liquidity",
                "explanation":
                    f"24h trading volume is {format_usd(volume_24h)}, which should "
                    "be evaluated against market capitalization."
            },

            {
                "title": "Risk score",
                "explanation":
                    f"The scoring engine assigned a risk score of {data.get('risk_score', 'not supplied')}."
            },

        ]

    # ------------------------------------------------------
    # FALLBACK SIGNALS
    # ------------------------------------------------------

    if not key_signals:

        key_signals = [

            {
                "title": "24h direction",
                "explanation":
                    f"The current 24h price change is {format_percentage(change_24h)}."
            },

            {
                "title": "Reference price",
                "explanation":
                    f"The live reference price is {format_usd(current_price)}."
            },

            {
                "title": "Volume context",
                "explanation":
                    f"The latest 24h trading volume is {format_usd(volume_24h)}."
            },

        ]

    # ------------------------------------------------------
    # FALLBACK WATCH ITEMS
    # ------------------------------------------------------

    if not watch_next:

        watch_next = [

            "Major market developments",
            "Changes in the asset's ecosystem",
            "New risk or regulatory information",

        ]

    return {

        "token": token_symbol,

        "risk_score_value": {
            "low": 20,
            "medium": 50,
            "high": 75,
            "extreme": 95,
        }.get(risk_score.lower(), 50),

        "trend": trend,

        "risk": risk_score,

        "price": predicted_price,

        "summary": autopsy_summary,

        "autopsy_summary": autopsy_summary,

        "fatal_flaws": risk_factors[:3],

        "stress_verdict": stress_verdict,

        "risk_profile": risk_profile,

        "stress_test": stress_test,

        "security_data": security_data,

        "key_insight": key_insight,

        "risk_factors": risk_factors,

        "problem_solved": problem_solved,

        "key_risks": key_risks,

        "key_signals": key_signals,

        "watch_next": watch_next,

    }


# ==========================================================
# DASHBOARD
# ==========================================================

def authenticated_user_id() -> Optional[int]:
    """Return the JWT user id first, with Google session fallback."""

    identity = get_jwt_identity()
    if identity is not None:
        return int(identity)

    return session.get("user_id")


def auth_user_payload(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "username": user.get("username", "User"),
        "name": user.get("name") or user.get("username", "User"),
        "email": user.get("email", ""),
        "picture": user.get("picture") or "",
    }


def load_user_payload(user_id: int) -> dict[str, Any]:
    connection = get_db()
    if not connection:
        return {}

    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT id, username, email, name, picture FROM users WHERE id = %s",
            (user_id,),
        )
        user = cursor.fetchone()
        return auth_user_payload(user) if user else {}
    finally:
        cursor.close()
        connection.close()


@app.route("/api/signup", methods=["POST"])
def signup():
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))

    if not username or not email or len(password) < 8:
        return jsonify({
            "success": False,
            "message": "Username and email are required; password must be at least 8 characters.",
        }), 400

    connection = get_db()
    if not connection:
        return jsonify({"success": False, "message": "Database unavailable."}), 503

    cursor = connection.cursor()
    try:
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            return jsonify({"success": False, "message": "An account with that email already exists."}), 409

        cursor.execute(
            """
            INSERT INTO users (username, email, password, name)
            VALUES (%s, %s, %s, %s)
            RETURNING id, username, email, name, picture
            """,
            (username, email, generate_password_hash(password), username),
        )
        user = cursor.fetchone()
        connection.commit()

        token = create_access_token(identity=str(user["id"]))
        session.update({
            "user_id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "name": user.get("name") or user["username"],
            "picture": user.get("picture") or "",
        })
        return jsonify({"success": True, "token": token, "user": auth_user_payload(user)}), 201
    except Exception:
        connection.rollback()
        logger.exception("Signup failed.")
        return jsonify({"success": False, "message": "Unable to create account."}), 500
    finally:
        cursor.close()
        connection.close()


@app.route("/api/login", methods=["POST"])
def login():
    payload = request.get_json(silent=True) or {}
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))

    connection = get_db()
    if not connection:
        return jsonify({"success": False, "message": "Database unavailable."}), 503

    cursor = connection.cursor()
    try:
        cursor.execute(
            "SELECT id, username, email, password, name, picture FROM users WHERE email = %s",
            (email,),
        )
        user = cursor.fetchone()
        if not user or not user.get("password") or not check_password_hash(user["password"], password):
            return jsonify({"success": False, "message": "Invalid email or password."}), 401

        token = create_access_token(identity=str(user["id"]))
        session.update({
            "user_id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "name": user.get("name") or user["username"],
            "picture": user.get("picture") or "",
        })
        return jsonify({"success": True, "token": token, "user": auth_user_payload(user)})
    finally:
        cursor.close()
        connection.close()

@app.route("/api/health")
def health_check():
    return jsonify({"status": "ok"})


@app.route("/api/session")
@jwt_required(optional=True)
def session_info():
    user_id = authenticated_user_id()
    if not user_id:
        return jsonify({"authenticated": False}), 401

    return jsonify({
        "authenticated": True,
        "user": load_user_payload(user_id),
    })

@app.route(
    "/dashboard",
    methods=["GET", "POST"],
)
@app.route(
    "/api/dashboard",
    methods=["GET", "POST"],
)
@jwt_required(optional=True)
def dashboard():

    user_id = authenticated_user_id()
    if not user_id:

        if request.path.startswith("/api/"):
            return jsonify({"success": False, "message": "Authentication required."}), 401

        return redirect(
            frontend_location()
        )

    latest_analysis = None
    risk_score = None

    # ======================================================
    # NEW ANALYSIS
    # ======================================================

    if request.method == "POST":

        request_data = request.get_json(silent=True) or {}
        token_symbol = (
            request_data.get("token_symbol", "")
            if request.is_json
            else request.form.get("token_symbol", "")
        ).strip().upper()

        # --------------------------------------------------
        # VALIDATION
        # --------------------------------------------------

        if not token_symbol:

            flash(
                "Please enter a cryptocurrency symbol.",
                "danger",
            )

            return redirect(
                url_for("dashboard")
            )

        if len(token_symbol) > 15:

            flash(
                "Invalid cryptocurrency symbol.",
                "danger",
            )

            return redirect(
                url_for("dashboard")
            )

        if not re.match(
            r"^[A-Z0-9._-]+$",
            token_symbol,
        ):

            flash(
                "Invalid cryptocurrency symbol.",
                "danger",
            )

            return redirect(
                url_for("dashboard")
            )

        # --------------------------------------------------
        # GEMINI CHECK
        # --------------------------------------------------

        if not client:

            flash(
                "Gemini AI is not configured.",
                "danger",
            )

            return redirect(
                url_for("dashboard")
            )

        # --------------------------------------------------
        # BUILD PROMPT
        # --------------------------------------------------

        market_data = fetch_crypto_market_data(token_symbol) or {
            "ticker": token_symbol,
        }
        market_data = sanitize_market_data(market_data)
        security_data = {}
        risk_profile = evaluate_risk_profile(
            market_data,
            security_data,
        )
        risk_score = risk_profile["composite_score"]
        btc_market_data = fetch_crypto_market_data("BTC")
        stress_test = simulate_stress_test(
            market_data.get("price_change_percentage_7d", 0),
            btc_market_data.get("price_change_percentage_7d", 0),
        )

        prompt = build_crypto_prompt(
            market_data,
            security_data,
            risk_profile,
            stress_test,
        )

        try:

            logger.info(
                "Starting Gemini analysis: %s",
                token_symbol,
            )

            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(
                client.models.generate_content,
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    response_mime_type="application/json",
                ),
            )

            try:
                response = future.result(timeout=45)
            finally:
                executor.shutdown(wait=False, cancel_futures=True)

            raw_result = (
                response.text.strip()
                if response.text
                else ""
            )

            if not raw_result:

                raise ValueError(
                    "Gemini returned an empty response."
                )

            # --------------------------------------------------
            # PARSE JSON
            # --------------------------------------------------

            ai_data = extract_json(
                raw_result
            )

            latest_analysis = normalize_report(
                ai_data,
                token_symbol,
                market_data,
                risk_profile,
                stress_test,
                security_data,
            )
            latest_analysis["security_data"] = security_data
            latest_analysis["risk_score_value"] = risk_score

            # ==================================================
            # SAVE TO POSTGRESQL
            # ==================================================

            connection = get_db()

            if not connection:

                flash(
                    "Analysis generated, but the database is unavailable.",
                    "warning",
                )

            else:

                cursor = connection.cursor()

                try:

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
                        """,
                        (
                            user_id,
                            token_symbol,
                            latest_analysis["trend"],
                            latest_analysis["risk"],
                            latest_analysis["price"],
                            latest_analysis["summary"],
                        ),
                    )

                    connection.commit()

                    logger.info(
                        "Analysis saved: user=%s asset=%s",
                        user_id,
                        token_symbol,
                    )

                except Exception:

                    connection.rollback()

                    logger.exception(
                        "Prediction database insert failed."
                    )

                    flash(
                        "Analysis generated but could not be saved.",
                        "warning",
                    )

                finally:

                    cursor.close()
                    connection.close()

            if (
                request.headers.get("X-Requested-With") == "XMLHttpRequest"
                and not request.path.startswith("/api/")
            ):
                return jsonify({"success": True})

        # ==================================================
        # JSON ERROR
        # ==================================================

        except TimeoutError:

            logger.error("Gemini analysis timed out for %s.", token_symbol)

            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({
                    "success": False,
                    "message": "Analysis timed out. Please try again.",
                }), 504

            flash("Analysis timed out. Please try again.", "danger")

        except json.JSONDecodeError:

            logger.exception(
                "Gemini returned invalid JSON."
            )

            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({
                    "success": False,
                    "message": "AI returned an invalid report. Please try again.",
                }), 502

            flash("AI returned an invalid report. Please try again.", "danger")

        # ==================================================
        # GEMINI QUOTA ERROR
        # ==================================================

        except Exception as error:

            error_text = str(error)

            if (
                "429" in error_text
                or "RESOURCE_EXHAUSTED" in error_text
                or "quota" in error_text.lower()
            ):

                logger.warning(
                    "Gemini quota exceeded for %s.",
                    token_symbol,
                )

                message = "Gemini is temporarily rate-limited. Please wait and try again."

                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return jsonify({"success": False, "message": message}), 429

                flash(message, "warning")

            else:

                logger.exception(
                    "Gemini cryptocurrency analysis failed."
                )

                message = "Unable to generate cryptocurrency analysis. Please try again."

                if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                    return jsonify({"success": False, "message": message}), 502

                flash(message, "danger")

    # ======================================================
    # HISTORY
    # ======================================================

    history = []

    connection = get_db()

    if connection:

        cursor = connection.cursor()

        try:

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
                """,
                (
                    user_id,
                ),
            )

            history = cursor.fetchall()

        except Exception:

            logger.exception(
                "Prediction history retrieval failed."
            )

            flash(
                "Unable to load prediction history.",
                "danger",
            )

        finally:

            cursor.close()
            connection.close()

    if not latest_analysis and history:
        latest_row = history[0]
        latest_analysis = normalize_report(
            {
                "trend": latest_row["trend"],
                "risk_score": latest_row["risk_score"],
                "predicted_price": latest_row["predicted_price"],
                "summary": latest_row["summary"],
            },
            latest_row["token_symbol"],
            fetch_crypto_market_data(latest_row["token_symbol"]) or {},
        )
        latest_analysis["id"] = latest_row["id"]

    if latest_analysis:
        latest_analysis["market_data"] = (
            fetch_crypto_market_data(latest_analysis["token"])
            or {}
        )
        latest_analysis["market_data"] = format_market_data_for_display(
            latest_analysis["market_data"]
        )

        if not latest_analysis.get("risk_profile"):
            latest_analysis["risk_profile"] = evaluate_risk_profile(
                latest_analysis["market_data"],
            )

        if not latest_analysis.get("stress_test"):
            btc_market_data = fetch_crypto_market_data("BTC")
            latest_analysis["stress_test"] = simulate_stress_test(
                latest_analysis["market_data"].get(
                    "price_change_percentage_7d",
                    0,
                ),
                btc_market_data.get("price_change_percentage_7d", 0),
            )

        if risk_score is None:
            risk_score = latest_analysis["risk_profile"]["composite_score"]

        latest_analysis["risk_score_value"] = latest_analysis[
            "risk_profile"
        ]["composite_score"]
        latest_analysis.setdefault("security_data", {})

    if request.path.startswith("/api/"):
        serialized_history = [
            {
                **dict(history_row),
                "created_at": str(history_row.get("created_at", "")),
            }
            for history_row in history
        ]

        return jsonify({
            "success": True,
            "user": load_user_payload(user_id),
            "latest": latest_analysis,
            "history": serialized_history,
        })

    # ======================================================
    # RENDER
    # ======================================================

    return render_template(
        "dashboard.html",
        username=session.get("username", "User"),
        name=session.get("name", "User"),
        email=session.get("email", ""),
        picture=session.get("picture", ""),
        latest=latest_analysis,
        risk_score=risk_score,
        history=history,
    )


# ==========================================================
# DELETE REPORT
# ==========================================================

@app.route(
    "/delete-report/<int:prediction_id>",
    methods=["POST"],
)
@app.route(
    "/api/history/<int:prediction_id>/delete",
    methods=["POST"],
)
@jwt_required(optional=True)
def delete_report(prediction_id):

    user_id = authenticated_user_id()
    if not user_id:

        if request.path.startswith("/api/"):
            return jsonify({"success": False, "message": "Authentication required."}), 401

        return redirect(
            frontend_location()
        )

    connection = get_db()

    if not connection:

        if request.path.startswith("/api/"):
            return jsonify({"success": False, "message": "Database unavailable."}), 503

        flash(
            "Database is currently unavailable.",
            "danger",
        )

        return redirect(
            url_for("dashboard")
        )

    cursor = connection.cursor()

    try:

        cursor.execute(
            """
            DELETE FROM predictions
            WHERE id = %s
            AND user_id = %s
            """,
            (
                prediction_id,
                user_id,
            ),
        )

        if cursor.rowcount == 0:

            connection.rollback()

            flash(
                "Report not found.",
                "warning",
            )

        else:

            connection.commit()

            logger.info(
                "Report deleted: user=%s report=%s",
                user_id,
                prediction_id,
            )

            flash(
                "Analysis report deleted successfully.",
                "success",
            )

    except Exception:

        connection.rollback()

        logger.exception(
            "Prediction deletion failed."
        )

        flash(
            "Unable to delete the report.",
            "danger",
        )

    finally:

        cursor.close()
        connection.close()

    if request.path.startswith("/api/"):
        return jsonify({"success": True})

    return redirect(url_for("dashboard"))


# ==========================================================
# LOGOUT
# ==========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        frontend_location()
    )


# ==========================================================
# DATABASE INITIALIZATION
# ==========================================================

_db_initialized = False

_db_init_lock = Lock()


@app.before_request
def ensure_database_initialized():

    global _db_initialized

    if _db_initialized:
        return

    with _db_init_lock:

        if _db_initialized:
            return

        if init_db():

            _db_initialized = True


# ==========================================================
# APPLICATION ENTRY POINT
# ==========================================================

if __name__ == "__main__":

    mock_market_data = {
        "change_7d": 24.5,
        "volume": 1_500_000,
        "market_cap": 10_000_000,
    }

    mock_security_data = {
        "is_honeypot": False,
        "buy_tax": 4,
        "sell_tax": 8,
    }

    print(
        "Mock risk score:",
        calculate_risk_score(
            mock_market_data,
            mock_security_data,
        ),
    )

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True,
    )
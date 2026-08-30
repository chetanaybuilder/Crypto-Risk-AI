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
from threading import Lock

import psycopg2
import psycopg2.extras
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from google import genai


# ==========================================================
# ENVIRONMENT
# ==========================================================

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")


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
# FLASK
# ==========================================================

app = Flask(__name__)

app.secret_key = SECRET_KEY

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

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

@app.route("/auth/google")
def google_login():

    if "user_id" in session:
        return redirect(
            url_for("dashboard")
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
                url_for("dashboard")
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
                url_for("home")
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
            url_for("home")
        )


# ==========================================================
# HOME
# ==========================================================

@app.route("/")
def home():

    if "user_id" in session:
        return redirect(
            url_for("dashboard")
        )

    return render_template(
        "index.html"
    )


# ==========================================================
# COMPATIBILITY ROUTES
# ==========================================================

@app.route("/login")
def login():

    if "user_id" in session:
        return redirect(
            url_for("dashboard")
        )

    return redirect(
        url_for("google_login")
    )


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

def build_crypto_prompt(token_symbol):

    return f"""
You are the intelligence engine behind CryptoRisk AI.

Your job is to transform cryptocurrency research context
into a clear, professional, educational risk-intelligence
report.

ASSET:
{token_symbol}

IMPORTANT DATA POLICY:

- You do NOT have guaranteed real-time market data.
- Do NOT invent a current price.
- Do NOT claim that a value is live.
- Do NOT fabricate exact statistics.
- If current market data is unavailable, explicitly say so.
- Distinguish analytical reasoning from verified live data.
- This is educational risk intelligence, not financial advice.

CORE OBJECTIVE:

Help a user answer:

"Why should I pay attention to the risk of this
cryptocurrency, and what should I understand before
making an informed decision?"

The report must identify:

1. Overall risk level.
2. Directional market outlook.
3. Important uncertainty.
4. Major downside risks.
5. Important positive/neutral market signals.
6. What developments the user should monitor next.

Return ONLY valid JSON.

Use EXACTLY this schema:

{{
    "trend": "Bullish | Bearish | Neutral",

    "risk_score": "Low | Medium | High | Extreme",

    "predicted_price":
        "Unavailable — live market data not connected.",

    "summary":
        "A concise 2-3 sentence executive intelligence summary.",

    "problem_solved":
        "Explain clearly what user problem CryptoRisk AI solves for this asset.",

    "key_risks": [
        {{
            "title": "Short risk title",
            "explanation": "One concise explanation."
        }},
        {{
            "title": "Short risk title",
            "explanation": "One concise explanation."
        }},
        {{
            "title": "Short risk title",
            "explanation": "One concise explanation."
        }}
    ],

    "key_signals": [
        {{
            "title": "Short signal title",
            "explanation": "One concise explanation."
        }},
        {{
            "title": "Short signal title",
            "explanation": "One concise explanation."
        }},
        {{
            "title": "Short signal title",
            "explanation": "One concise explanation."
        }}
    ],

    "watch_next": [
        "One concise thing to monitor.",
        "One concise thing to monitor.",
        "One concise thing to monitor."
    ]
}}

QUALITY RULES:

- Be analytical rather than promotional.
- Avoid hype.
- Avoid guaranteed predictions.
- Avoid phrases such as "this will go up".
- Use uncertainty when evidence is uncertain.
- Keep explanations understandable.
- Do not overwhelm the user.
- Focus on decision-relevant intelligence.
- Never invent live prices.
- Exactly 3 key risks.
- Exactly 3 key signals.
- Exactly 3 watch-next items.
- Return JSON only.
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

def normalize_report(data, token_symbol):

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

    summary = str(
        data.get(
            "summary",
            "No executive summary was generated.",
        )
    ).strip()

    problem_solved = str(
        data.get(
            "problem_solved",
            "CryptoRisk AI organizes complex cryptocurrency risk information into a concise intelligence report.",
        )
    ).strip()

    predicted_price = str(
        data.get(
            "predicted_price",
            "Unavailable — live market data not connected.",
        )
    ).strip()

    # ------------------------------------------------------
    # RISKS
    # ------------------------------------------------------

    raw_risks = data.get(
        "key_risks",
        [],
    )

    key_risks = []

    if isinstance(raw_risks, list):

        for item in raw_risks[:3]:

            if isinstance(item, dict):

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
        [],
    )

    key_signals = []

    if isinstance(raw_signals, list):

        for item in raw_signals[:3]:

            if isinstance(item, dict):

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
                "title": "Market volatility",
                "explanation":
                    "Cryptocurrency prices can change rapidly, increasing uncertainty."
            },

            {
                "title": "Information uncertainty",
                "explanation":
                    "Available information can change quickly and should be independently verified."
            },

            {
                "title": "External conditions",
                "explanation":
                    "Regulatory, macroeconomic, technological, and market conditions can affect the asset."
            },

        ]

    # ------------------------------------------------------
    # FALLBACK SIGNALS
    # ------------------------------------------------------

    if not key_signals:

        key_signals = [

            {
                "title": "Market direction",
                "explanation":
                    "The current analytical outlook should be treated as an uncertain directional signal."
            },

            {
                "title": "Ecosystem activity",
                "explanation":
                    "Development and ecosystem activity can provide useful context for long-term relevance."
            },

            {
                "title": "Market conditions",
                "explanation":
                    "Broader cryptocurrency market conditions can materially influence individual assets."
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

        "trend": trend,

        "risk": risk_score,

        "price": predicted_price,

        "summary": summary,

        "problem_solved": problem_solved,

        "key_risks": key_risks,

        "key_signals": key_signals,

        "watch_next": watch_next,

    }


# ==========================================================
# DASHBOARD
# ==========================================================

@app.route(
    "/dashboard",
    methods=["GET", "POST"],
)
def dashboard():

    if "user_id" not in session:

        return redirect(
            url_for("home")
        )

    latest_analysis = None

    # ======================================================
    # NEW ANALYSIS
    # ======================================================

    if request.method == "POST":

        token_symbol = (
            request.form
            .get(
                "token_symbol",
                "",
            )
            .strip()
            .upper()
        )

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

        prompt = build_crypto_prompt(
            token_symbol
        )

        try:

            logger.info(
                "Starting Gemini analysis: %s",
                token_symbol,
            )

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )

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
            )

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
                            session["user_id"],
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
                        session["user_id"],
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

        # ==================================================
        # JSON ERROR
        # ==================================================

        except json.JSONDecodeError:

            logger.exception(
                "Gemini returned invalid JSON."
            )

            flash(
                "AI returned an invalid report. Please try again.",
                "danger",
            )

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

                flash(
                    "Gemini free-tier quota is currently exhausted. "
                    "Please wait and try again later.",
                    "warning",
                )

            else:

                logger.exception(
                    "Gemini cryptocurrency analysis failed."
                )

                flash(
                    "Unable to generate cryptocurrency analysis.",
                    "danger",
                )

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
                    session["user_id"],
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

    # ======================================================
    # RENDER
    # ======================================================

    return render_template(
        "dashboard.html",

        username=session.get(
            "username",
            "User",
        ),

        name=session.get(
            "name",
            session.get(
                "username",
                "User",
            ),
        ),

        email=session.get(
            "email",
            "",
        ),

        picture=session.get(
            "picture",
            "",
        ),

        latest=latest_analysis,

        history=history,
    )


# ==========================================================
# DELETE REPORT
# ==========================================================

@app.route(
    "/delete-report/<int:prediction_id>",
    methods=["POST"],
)
def delete_report(prediction_id):

    if "user_id" not in session:

        return redirect(
            url_for("home")
        )

    connection = get_db()

    if not connection:

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
                session["user_id"],
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
                session["user_id"],
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

    return redirect(
        url_for("dashboard")
    )


# ==========================================================
# LOGOUT
# ==========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(
        url_for("home")
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

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True,
    )
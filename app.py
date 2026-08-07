"""Flask application for AI-powered cryptocurrency risk analysis.

The app manages user authentication, stores prediction history in PostgreSQL,
and generates AI-based market insights with Gemini.
"""

from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from google import genai
from dotenv import load_dotenv
import psycopg2
import psycopg2.extras
import os
import logging

# ----------------------------
# Load Environment Variables
# ----------------------------
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SECRET_KEY = os.getenv("SECRET_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

if not SECRET_KEY:
    raise ValueError("SECRET_KEY is missing. Please create a .env file.")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is missing. Please create a .env file.")

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# ----------------------------
# Flask App
# ----------------------------
app = Flask(__name__)
app.secret_key = SECRET_KEY

# Session Security
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# ----------------------------
# Logging
# ----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# ----------------------------
# Database
# ----------------------------

def get_db():
    """Create and return a PostgreSQL database connection with dict-style row access."""
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        return conn
    except Exception:
        logging.exception("Database connection failed")
        return None


def init_db():
    """Initialize the PostgreSQL schema for users and predictions if missing."""
    conn = get_db()
    if not conn:
        logging.warning("Skipping DB init because no DB connection is available.")
        return
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id SERIAL PRIMARY KEY,
        username TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS predictions(
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        token_symbol TEXT NOT NULL,
        trend TEXT NOT NULL,
        risk_score TEXT NOT NULL,
        predicted_price TEXT,
        summary TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """)

    conn.commit()
    cur.close()
    conn.close()


# Defer DB initialization until the app is running to avoid import-time
# connection attempts (useful on hosting platforms without a local Postgres).
# The real initialization will run before the first request is handled.

# ----------------------------
# Helper Functions
# ----------------------------

def validate_password(password):
    """Ensure the password meets the minimum security requirements."""
    return len(password) >= 8


def validate_username(username):
    """Ensure the username meets the minimum length requirement."""
    return len(username) >= 3


# ----------------------------
# Home
# ----------------------------
@app.route("/")
def home():
    """Render the landing page and redirect logged-in users to the dashboard."""

    if "user_id" in session:
        return redirect(url_for("dashboard"))

    return render_template("index.html")


# ----------------------------
# Register
# ----------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    """Handle user registration and create a new account in the database."""

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not username or not email or not password:
            flash("Please fill all fields.", "danger")
            return render_template("register.html")

        if not validate_username(username):
            flash("Username must be at least 3 characters.", "danger")
            return render_template("register.html")

        if not validate_password(password):
            flash("Password must contain at least 8 characters.", "danger")
            return render_template("register.html")

        hashed_password = generate_password_hash(password)

        conn = get_db()
        if not conn:
            flash("Database is currently unreachable. Try again later.", "danger")
            return render_template("register.html")

        try:
            cur = conn.cursor()

            cur.execute(
                """
                INSERT INTO users(username, email, password)
                VALUES(%s, %s, %s)
                """,
                (username, email, hashed_password)
            )

            conn.commit()
            cur.close()

            flash("Account created successfully. Please login.", "success")
            return redirect(url_for("login"))

        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            flash("Email already exists.", "danger")

        except Exception:
            conn.rollback()
            logging.exception("Register Error")
            flash("Something went wrong.", "danger")

        finally:
            conn.close()

    return render_template("register.html")


# ----------------------------
# Login
# ----------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    """Authenticate users and establish their session on successful login."""

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Please fill all fields.", "danger")
            return render_template("login.html")

        conn = get_db()
        if not conn:
            flash("Database is currently unreachable. Try again later.", "danger")
            return render_template("login.html")

        cur = conn.cursor()

        cur.execute(
            "SELECT * FROM users WHERE email=%s",
            (email,)
        )
        user = cur.fetchone()

        cur.close()
        conn.close()

        if user and check_password_hash(user["password"], password):

            session["user_id"] = user["id"]
            session["username"] = user["username"]

            flash(f"Welcome back, {user['username']}!", "success")
            return redirect(url_for("dashboard"))

        flash("Invalid email or password.", "danger")

    return render_template("login.html")

# ----------------------------
# Dashboard
# ----------------------------
@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    """Render the dashboard and generate AI-powered crypto analysis for the user."""

    if "user_id" not in session:
        flash("Please login first.", "warning")
        return redirect(url_for("login"))

    latest_analysis = None

    if request.method == "POST":

        token_symbol = request.form.get("token_symbol", "").strip().upper()

        if not token_symbol:
            flash("Please enter a token symbol.", "danger")
            return redirect(url_for("dashboard"))

        if len(token_symbol) > 15:
            flash("Invalid token symbol.", "danger")
            return redirect(url_for("dashboard"))

        if not client:
            flash("Gemini API is not configured.", "danger")
            return redirect(url_for("dashboard"))

        prompt = f"""
You are an institutional cryptocurrency analyst.

Analyze the cryptocurrency ticker:

{token_symbol}

Respond ONLY in this exact format.

Trend: Bullish/Bearish/Neutral

Risk Score: Low/Medium/High/Extreme

Predicted Price: $0.00

Summary:
Write only two professional sentences explaining the outlook.
"""

        try:

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )

            result = response.text.strip()

            trend = "Unknown"
            risk = "Unknown"
            predicted_price = "N/A"
            summary = ""

            for line in result.split("\n"):

                if line.startswith("Trend:"):
                    trend = line.replace("Trend:", "").strip()

                elif line.startswith("Risk Score:"):
                    risk = line.replace("Risk Score:", "").strip()

                elif line.startswith("Predicted Price:"):
                    predicted_price = line.replace("Predicted Price:", "").strip()

                elif line.startswith("Summary:"):
                    summary = line.replace("Summary:", "").strip()

            if not summary:
                summary = result

            conn = get_db()
            cur = conn.cursor()

            cur.execute(
                """
                INSERT INTO predictions
                (
                    user_id,
                    token_symbol,
                    trend,
                    risk_score,
                    predicted_price,
                    summary
                )
                VALUES(%s, %s, %s, %s, %s, %s)
                """,
                (
                    session["user_id"],
                    token_symbol,
                    trend,
                    risk,
                    predicted_price,
                    summary
                )
            )

            conn.commit()
            cur.close()
            conn.close()

            latest_analysis = {
                "token": token_symbol,
                "trend": trend,
                "risk": risk,
                "price": predicted_price,
                "summary": summary
            }

        except Exception:

            logging.exception("Gemini Error")
            flash("Unable to generate analysis.", "danger")

    conn = get_db()
    history = []
    if conn:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT *
            FROM predictions
            WHERE user_id=%s
            ORDER BY created_at DESC
            """,
            (session["user_id"],)
        )
        history = cur.fetchall()

        cur.close()
        conn.close()

    return render_template(
        "dashboard.html",
        username=session["username"],
        latest=latest_analysis,
        history=history
    )


# ----------------------------
# Logout
# ----------------------------
@app.route("/logout")
def logout():
    """Clear the active session and return the user to the login page."""

    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for("login"))


# ----------------------------
# Run App
# ----------------------------
# Initialize DB on first request using a before_request fallback
# Some Flask builds (or minimal WSGI wrappers) may not expose
# `before_first_request`, so use `before_request` with a lock to
# perform one-time initialization safely.
_db_initialized = False
from threading import Lock
_db_init_lock = Lock()


@app.before_request
def _ensure_db_initialized():
    global _db_initialized
    if _db_initialized:
        return
    with _db_init_lock:
        if _db_initialized:
            return
        try:
            init_db()
            _db_initialized = True
        except Exception:
            logging.exception("Database initialization skipped due to connection error.")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
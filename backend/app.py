"""
CryptoRisk AI Application Factory & Entrypoint.

Configures the Flask WSGI application instance, registers security middleware,
sets up OAuth 2.0 integrations, and mounts domain route blueprints.
"""

import os
import sys
import uuid
from pathlib import Path

from flask import Flask, g, request
from flask_cors import CORS

# Ensure backend directory is prioritized on sys.path for absolute module imports
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Resolve dynamic paths for frontend templates and static assets
ROOT_DIR = BACKEND_DIR.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
template_folder = str(FRONTEND_DIR / "templates") if (FRONTEND_DIR / "templates").exists() else "templates"
static_folder = str(FRONTEND_DIR / "static") if (FRONTEND_DIR / "static").exists() else "static"

from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, IS_PRODUCTION, SECRET_KEY
from extensions import oauth

from routes.auth import bp as auth_bp
from routes.dashboard import bp as dashboard_bp
from routes.health import bp as health_bp
from routes.history import bp as history_bp
from routes.market import bp as market_bp
from routes.risk import bp as risk_bp
from utils.error_handlers import bp as errors_bp

# Initialize Flask application with resolved frontend asset directories
app = Flask(
    __name__,
    template_folder=template_folder,
    static_folder=static_folder,
)
app.secret_key = SECRET_KEY

# Register Google OAuth 2.0 OpenID Connect client
oauth.init_app(app)
oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

# Cross-Origin Resource Sharing for API routes
CORS(
    app,
    resources={r"/api/*": {"origins": "*"}},
    supports_credentials=True,
)


@app.before_request
def attach_request_id():
    """Propagate upstream correlation ID or generate a trace UUID for request lifecycle."""
    g.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())


@app.after_request
def attach_response_headers(response):
    """Expose correlation ID on outbound response headers for client diagnostics."""
    response.headers["X-Request-ID"] = g.get("request_id", "")
    return response


# Domain Blueprint Registrations
app.register_blueprint(auth_bp)
app.register_blueprint(market_bp)
app.register_blueprint(risk_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(history_bp)
app.register_blueprint(health_bp)
app.register_blueprint(errors_bp)

if __name__ == "__main__":
    # Local development server entrypoint; production runs via Gunicorn WSGI
    app.run(debug=not IS_PRODUCTION, port=5000)

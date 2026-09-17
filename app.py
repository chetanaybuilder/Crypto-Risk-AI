"""
CryptoRisk AI Application Factory & Entrypoint.

Configures the Flask WSGI application instance, registers security middleware,
sets up OAuth 2.0 integrations, and mounts domain route blueprints.
"""

import uuid
from flask import Flask, g, request
from flask_cors import CORS

from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, IS_PRODUCTION, SECRET_KEY
from extensions import oauth

from routes.auth import bp as auth_bp
from routes.dashboard import bp as dashboard_bp
from routes.health import bp as health_bp
from routes.history import bp as history_bp
from routes.market import bp as market_bp
from routes.risk import bp as risk_bp
from utils.error_handlers import bp as errors_bp

# Initialize Flask application with static assets
app = Flask(__name__, static_folder="static")
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

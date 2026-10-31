"""
CryptoRisk AI — Local Development Gateway.

Serves as the local development launcher from repository root:
    python app.py
"""

from backend.app import app
from backend.config import IS_PRODUCTION

if __name__ == "__main__":
    app.run(debug=not IS_PRODUCTION, port=5000)

"""
Root Application Gateway Bridge.

Provides zero-downtime deployment compatibility for WSGI hosts (e.g. Render, Heroku)
configured to launch from the repository root via 'gunicorn app:app'.
"""

import os
import sys
from pathlib import Path

# Prioritize backend directory on sys.path
BACKEND_DIR = Path(__file__).resolve().parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from backend.app import app

if __name__ == "__main__":
    from config import IS_PRODUCTION
    app.run(debug=not IS_PRODUCTION, port=5000)

"""
Production WSGI Entrypoint.

Standard WSGI callable for Gunicorn, uWSGI, and containerized deployments.
Usage: gunicorn wsgi:app
"""

import sys
from pathlib import Path

# Prioritize backend directory on sys.path
BACKEND_DIR = Path(__file__).resolve().parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from backend.app import app

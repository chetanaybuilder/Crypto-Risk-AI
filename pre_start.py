"""
Root Pre-Deployment Migration Bridge.

Executes database schema migrations and connectivity checks via backend.pre_start.
Compatible with Render preDeployCommand: "python pre_start.py".
"""

import sys
from pathlib import Path

# Prioritize backend directory on sys.path
BACKEND_DIR = Path(__file__).resolve().parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from pre_start import main

if __name__ == "__main__":
    main()

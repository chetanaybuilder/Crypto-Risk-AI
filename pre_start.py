"""
Pre-Deployment Infrastructure Initialization.

Executed as a standalone pre-deploy step in deployment blueprints (e.g. Render,
Kubernetes init containers) to run idempotent database migrations and verify schema
integrity before web worker processes fork.
"""

import logging
from extensions import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pre_start")


def main():
    """Execute pre-flight schema migrations and connection health validation."""
    logger.info("Running pre-start schema initialization...")
    try:
        init_db()
        logger.info("Pre-start database initialization completed successfully.")
    except Exception as exc:
        logger.exception("Fatal error during pre-start initialization: %s", exc)
        raise exc


if __name__ == "__main__":
    main()

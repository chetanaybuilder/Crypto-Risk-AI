import logging
from extensions import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pre_start")

def main():
    logger.info("Running pre-start initialization...")
    try:
        init_db()
        logger.info("Pre-start initialization completed successfully.")
    except Exception as e:
        logger.error(f"Error during pre-start initialization: {e}")
        raise e

if __name__ == "__main__":
    main()

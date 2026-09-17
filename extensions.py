"""
Infrastructure & Shared State Extensions.

Manages the PostgreSQL threaded connection pool, background task executors,
application in-memory caches, and OAuth client state.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import psycopg2
import psycopg2.extras
import psycopg2.pool
from authlib.integrations.flask_client import OAuth

from config import (
    ANALYSIS_EXECUTOR_WORKERS,
    DATABASE_URL,
    DB_CONNECT_RETRIES,
    DB_CONNECT_RETRY_DELAY,
    DB_POOL_MAX_CONN,
    DB_POOL_MIN_CONN,
    GEMINI_API_KEY,
    GEMINI_EXECUTOR_WORKERS,
    GEMINI_MODEL,
)

__all__ = [
    "oauth",
    "_cache_lock",
    "_market_cache",
    "_market_cap_cache",
    "_history_cache",
    "ANALYSIS_EXECUTOR",
    "GEMINI_EXECUTOR",
    "gemini_client",
    "_gemini_generate",
    "get_db_connection",
    "init_db",
    "logger",
]

logger = logging.getLogger(__name__)

# OAuth Manager
oauth = OAuth()

# Connection pool state
_db_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None
_db_pool_lock = threading.Lock()

# Shared application in-memory caches
_cache_lock = threading.Lock()
_market_cache = {}
_market_cap_cache = {}
_history_cache = {}

# Background execution thread pools
ANALYSIS_EXECUTOR = ThreadPoolExecutor(
    max_workers=ANALYSIS_EXECUTOR_WORKERS,
    thread_name_prefix="analysis",
)

GEMINI_EXECUTOR = ThreadPoolExecutor(
    max_workers=GEMINI_EXECUTOR_WORKERS,
    thread_name_prefix="gemini-worker",
)

# Gemini AI Client Initialization
try:
    from google import genai
except ImportError:
    genai = None

gemini_client = None
if genai and GEMINI_API_KEY:
    try:
        gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        logger.info("Gemini AI client initialized.")
    except Exception as exc:
        logger.error("Failed to initialize Gemini AI client: %s", exc)


def _gemini_generate(prompt: str) -> str:
    """Synchronous wrapper for Gemini generation to run inside thread pools."""
    if gemini_client is None:
        raise RuntimeError("Gemini AI is not configured (missing API key or client library).")

    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
    )
    return response.text


def _validate_db_pool_config() -> None:
    """Validate PostgreSQL connection pool bounds before pool creation."""
    try:
        min_conn = int(DB_POOL_MIN_CONN)
        max_conn = int(DB_POOL_MAX_CONN)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("DB_POOL_MIN_CONN and DB_POOL_MAX_CONN must be valid integers.") from exc

    if min_conn < 1:
        raise RuntimeError("DB_POOL_MIN_CONN must be at least 1.")
    if max_conn < min_conn:
        raise RuntimeError("DB_POOL_MAX_CONN must be greater than or equal to DB_POOL_MIN_CONN.")


def _init_db_pool():
    """Lazily initialize the single shared PostgreSQL connection pool (thread-safe)."""
    global _db_pool

    if _db_pool is not None:
        return _db_pool

    with _db_pool_lock:
        if _db_pool is not None:
            return _db_pool

        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not configured.")

        _validate_db_pool_config()

        try:
            _db_pool = psycopg2.pool.ThreadedConnectionPool(
                int(DB_POOL_MIN_CONN),
                int(DB_POOL_MAX_CONN),
                dsn=DATABASE_URL,
                sslmode="require",
                connect_timeout=10,
            )
            logger.info("PostgreSQL connection pool initialized (min=%s, max=%s).", DB_POOL_MIN_CONN, DB_POOL_MAX_CONN)
            return _db_pool
        except Exception:
            _db_pool = None
            logger.exception("Failed to initialize PostgreSQL connection pool.")
            raise


class _PooledConnection:
    """Thread-safe context wrapper around a pooled psycopg2 connection."""

    def __init__(self, pool, conn):
        self._pool = pool
        self._conn = conn
        self._closed = False

    @property
    def raw_connection(self):
        """Expose raw psycopg2 connection if necessary."""
        return self._conn

    def __enter__(self):
        if self._closed:
            raise RuntimeError("Cannot enter an already-closed database connection.")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is not None:
                self.rollback()
        except Exception:
            logger.debug("Rollback during connection context exit failed.", exc_info=True)
        finally:
            self.close()
        return False

    def _ensure_open(self):
        if self._closed:
            raise RuntimeError("Database connection has already been returned to the pool.")
        if self._conn is None or self._conn.closed:
            raise RuntimeError("Underlying database connection is closed or unavailable.")

    def cursor(self, *args, **kwargs):
        self._ensure_open()
        return self._conn.cursor(*args, **kwargs)

    def commit(self):
        self._ensure_open()
        try:
            return self._conn.commit()
        except Exception:
            logger.exception("Database commit failed.")
            raise

    def rollback(self):
        self._ensure_open()
        try:
            return self._conn.rollback()
        except Exception:
            logger.exception("Database rollback failed.")
            raise

    def close(self):
        """Return the physical connection cleanly to the pool."""
        if self._closed:
            return

        self._closed = True
        conn = self._conn
        pool = self._pool
        self._conn = None
        self._pool = None

        if conn is None or pool is None:
            return

        try:
            if not conn.closed:
                try:
                    conn.rollback()
                except Exception:
                    logger.warning("Could not reset transaction state before returning DB connection.", exc_info=True)
                    try:
                        pool.putconn(conn, close=True)
                    except Exception:
                        pass
                    return
            pool.putconn(conn)
        except Exception:
            logger.debug("Could not return DB connection to pool.", exc_info=True)
            try:
                if not conn.closed:
                    conn.close()
            except Exception:
                pass


def _discard_pooled_connection(pool, conn) -> None:
    """Remove a broken physical connection from the pool."""
    if conn is None:
        return
    try:
        pool.putconn(conn, close=True)
    except Exception:
        logger.debug("Failed to discard broken pooled connection.", exc_info=True)
        try:
            if not conn.closed:
                conn.close()
        except Exception:
            pass


def get_db_connection():
    """Obtain a verified PostgreSQL connection from the shared pool with retry backoff."""
    pool = _init_db_pool()

    try:
        retries = max(1, int(DB_CONNECT_RETRIES))
    except (TypeError, ValueError):
        retries = 1

    try:
        retry_delay = max(0.0, float(DB_CONNECT_RETRY_DELAY))
    except (TypeError, ValueError):
        retry_delay = 0.0

    last_error = None

    for attempt in range(retries):
        conn = None
        try:
            conn = pool.getconn()
            if conn is None:
                raise RuntimeError("PostgreSQL pool returned no connection.")

            if conn.closed:
                _discard_pooled_connection(pool, conn)
                continue

            try:
                conn.rollback()
            except Exception as exc:
                logger.warning("Discarding unhealthy pooled connection: %s", exc)
                _discard_pooled_connection(pool, conn)
                continue

            return _PooledConnection(pool, conn)

        except Exception as exc:
            last_error = exc
            if conn is not None:
                _discard_pooled_connection(pool, conn)

            logger.warning("DB connection attempt %s/%s failed: %s", attempt + 1, retries, exc)
            if attempt < retries - 1:
                sleep_seconds = retry_delay * (attempt + 1)
                if sleep_seconds > 0:
                    time.sleep(sleep_seconds)

    raise RuntimeError(f"Could not obtain a healthy database connection: {last_error}")


def init_db():
    """Idempotently initialize database extensions, schema tables, and indexes."""
    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")

            # Users table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    name TEXT,
                    picture TEXT,
                    password_hash TEXT,
                    google_id TEXT UNIQUE,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )

            # Analyses table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS analyses (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token_symbol TEXT NOT NULL,
                    report JSONB NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                """
            )

            # Ensure UUID migration if historical schema used integer IDs
            cursor.execute(
                """
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_name = 'analyses'
                          AND column_name = 'id'
                          AND data_type = 'integer'
                    ) THEN
                        ALTER TABLE analyses ALTER COLUMN id DROP DEFAULT;
                        ALTER TABLE analyses ALTER COLUMN id SET DATA TYPE UUID USING gen_random_uuid();
                    END IF;
                    ALTER TABLE analyses ALTER COLUMN id SET DEFAULT gen_random_uuid();
                END
                $$;
                """
            )

            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_analyses_user_created ON analyses (user_id, created_at DESC);"
            )

            # Analysis jobs table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_jobs (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    token_symbol TEXT NOT NULL,
                    chain_id TEXT,
                    contract_address TEXT,
                    status TEXT NOT NULL DEFAULT 'queued',
                    progress INTEGER NOT NULL DEFAULT 0,
                    stage TEXT,
                    stage_title TEXT,
                    message TEXT,
                    report JSONB,
                    meta JSONB,
                    error TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    started_at TIMESTAMPTZ,
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    completed_at TIMESTAMPTZ
                );
                """
            )

            cursor.execute(
                """
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1
                        FROM information_schema.columns
                        WHERE table_name = 'analysis_jobs'
                          AND column_name = 'id'
                          AND data_type = 'integer'
                    ) THEN
                        ALTER TABLE analysis_jobs ALTER COLUMN id DROP DEFAULT;
                        ALTER TABLE analysis_jobs ALTER COLUMN id SET DATA TYPE UUID USING gen_random_uuid();
                    END IF;
                    ALTER TABLE analysis_jobs ALTER COLUMN id SET DEFAULT gen_random_uuid();
                END
                $$;
                """
            )

            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_analysis_jobs_user_created ON analysis_jobs (user_id, created_at DESC);"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_analysis_jobs_status ON analysis_jobs (status, updated_at);"
            )
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_analysis_jobs_active_unique
                ON analysis_jobs (user_id, token_symbol)
                WHERE status IN ('queued', 'running', 'saving');
                """
            )

        connection.commit()
        logger.info("Database schema initialized successfully.")

    except Exception as exc:
        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                logger.debug("Database rollback after init failure failed.", exc_info=True)
        logger.exception("Database initialization failed: %s", exc)
        raise
    finally:
        if connection is not None:
            connection.close()
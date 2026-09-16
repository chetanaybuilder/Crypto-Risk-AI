import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import psycopg2
import psycopg2.pool
import psycopg2.extras
from authlib.integrations.flask_client import OAuth

from config import *

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


# ---------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------

oauth = OAuth()


# ---------------------------------------------------------------------------
# Database state
# ---------------------------------------------------------------------------

_db_pool = None
_db_pool_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Shared application caches
# ---------------------------------------------------------------------------

_cache_lock = threading.Lock()

_market_cache = {}
_market_cap_cache = {}
_history_cache = {}


# ---------------------------------------------------------------------------
# Background executors
# ---------------------------------------------------------------------------

ANALYSIS_EXECUTOR = ThreadPoolExecutor(
    max_workers=ANALYSIS_EXECUTOR_WORKERS,
    thread_name_prefix="analysis",
)

GEMINI_EXECUTOR = ThreadPoolExecutor(
    max_workers=GEMINI_EXECUTOR_WORKERS,
    thread_name_prefix="gemini-worker",
)


# ---------------------------------------------------------------------------
# Gemini AI initialization
# ---------------------------------------------------------------------------

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


def _gemini_generate(prompt):
    """
    Synchronous wrapper for Gemini generation to run inside thread pools.
    """
    if gemini_client is None:
        raise RuntimeError("Gemini AI is not configured (missing API key or library).")
        
    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
    )
    
    return response.text


# ---------------------------------------------------------------------------
# Database pool
# ---------------------------------------------------------------------------

def _validate_db_pool_config() -> None:
    """Validate PostgreSQL pool configuration before initialization."""

    try:
        min_conn = int(
            DB_POOL_MIN_CONN
        )

        max_conn = int(
            DB_POOL_MAX_CONN
        )

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise RuntimeError(
            "DB_POOL_MIN_CONN and DB_POOL_MAX_CONN "
            "must be valid integers."
        ) from exc

    if min_conn < 1:
        raise RuntimeError(
            "DB_POOL_MIN_CONN must be at least 1."
        )

    if max_conn < min_conn:
        raise RuntimeError(
            "DB_POOL_MAX_CONN must be greater than "
            "or equal to DB_POOL_MIN_CONN."
        )


def _init_db_pool():
    """
    Lazily initialize the single shared PostgreSQL connection pool.

    The double-check under _db_pool_lock prevents multiple threads from
    creating competing pools during application startup.
    """

    global _db_pool

    if _db_pool is not None:
        return _db_pool

    with _db_pool_lock:

        if _db_pool is not None:
            return _db_pool

        if not DATABASE_URL:
            raise RuntimeError(
                "DATABASE_URL is not configured."
            )

        _validate_db_pool_config()

        try:
            _db_pool = (
                psycopg2.pool.ThreadedConnectionPool(
                    int(DB_POOL_MIN_CONN),
                    int(DB_POOL_MAX_CONN),
                    dsn=DATABASE_URL,
                    sslmode="require",
                    connect_timeout=10,
                )
            )

            logger.info(
                "PostgreSQL connection pool initialized "
                "(min=%s, max=%s).",
                DB_POOL_MIN_CONN,
                DB_POOL_MAX_CONN,
            )

            return _db_pool

        except Exception:
            _db_pool = None

            logger.exception(
                "Failed to initialize PostgreSQL connection pool."
            )

            raise


class _PooledConnection:
    """
    Compatibility wrapper around a psycopg2 pooled connection.

    Existing application code can continue using:

        connection.cursor()
        connection.commit()
        connection.rollback()
        connection.close()

    close() returns the connection to the pool instead of physically
    closing the TCP connection.

    The wrapper is deliberately idempotent so double-close cannot return
    the same physical connection to the pool twice.
    """

    def __init__(
        self,
        pool,
        conn,
    ):
        self._pool = pool
        self._conn = conn
        self._closed = False

    @property
    def raw_connection(self):
        """Expose the underlying psycopg2 connection when necessary."""
        return self._conn

    def __enter__(self):
        if self._closed:
            raise RuntimeError(
                "Cannot enter an already-closed database connection."
            )

        return self

    def __exit__(
        self,
        exc_type,
        exc_val,
        exc_tb,
    ):
        try:
            if exc_type is not None:
                self.rollback()
        except Exception:
            logger.debug(
                "Rollback during connection context exit failed.",
                exc_info=True,
            )

        finally:
            self.close()

        return False

    def _ensure_open(self):
        if self._closed:
            raise RuntimeError(
                "Database connection has already been returned to the pool."
            )

        if self._conn is None:
            raise RuntimeError(
                "Underlying database connection is unavailable."
            )

        if self._conn.closed:
            raise RuntimeError(
                "Underlying database connection is closed."
            )

    def cursor(
        self,
        *args,
        **kwargs,
    ):
        self._ensure_open()

        return self._conn.cursor(
            *args,
            **kwargs,
        )

    def commit(self):
        self._ensure_open()

        try:
            return self._conn.commit()

        except Exception:
            logger.exception(
                "Database commit failed."
            )
            raise

    def rollback(self):
        self._ensure_open()

        try:
            return self._conn.rollback()

        except Exception:
            logger.exception(
                "Database rollback failed."
            )
            raise

    def close(self):
        """
        Return the physical connection to the pool exactly once.

        A rollback is performed before returning it so a transaction that
        was accidentally left open cannot leak into the next request.
        """

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
            # A rollback after a successful commit is harmless.
            # This guarantees a clean transaction state before reuse.
            if not conn.closed:
                try:
                    conn.rollback()
                except Exception:
                    logger.warning(
                        "Could not reset transaction state before "
                        "returning DB connection to pool.",
                        exc_info=True,
                    )

                    # If rollback itself fails, discard the physical
                    # connection instead of returning a potentially
                    # corrupted connection to the pool.
                    try:
                        pool.putconn(
                            conn,
                            close=True,
                        )
                    except Exception:
                        logger.debug(
                            "Failed to discard broken DB connection.",
                            exc_info=True,
                        )

                    return

            pool.putconn(
                conn
            )

        except Exception:
            logger.debug(
                "Could not return DB connection to pool.",
                exc_info=True,
            )

            # Best-effort physical cleanup if returning to the pool fails.
            try:
                if not conn.closed:
                    conn.close()
            except Exception:
                pass


def _discard_pooled_connection(
    pool,
    conn,
) -> None:
    """
    Remove a bad physical connection from the pool.

    Never return a known-broken connection for another request.
    """

    if conn is None:
        return

    try:
        pool.putconn(
            conn,
            close=True,
        )

    except Exception:
        logger.debug(
            "Failed to discard broken pooled connection.",
            exc_info=True,
        )

        try:
            if not conn.closed:
                conn.close()
        except Exception:
            pass


def get_db_connection():
    """
    Obtain a healthy PostgreSQL connection from the shared pool.

    Transient connection failures are retried with linear backoff.

    Returned connections MUST eventually have close() called.
    """

    pool = _init_db_pool()

    try:
        retries = max(
            1,
            int(DB_CONNECT_RETRIES),
        )

    except (
        TypeError,
        ValueError,
    ):
        retries = 1

    try:
        retry_delay = max(
            0.0,
            float(
                DB_CONNECT_RETRY_DELAY
            ),
        )

    except (
        TypeError,
        ValueError,
    ):
        retry_delay = 0.0

    last_error = None

    for attempt in range(
        retries
    ):

        conn = None

        try:
            conn = pool.getconn()

            if conn is None:
                raise RuntimeError(
                    "PostgreSQL pool returned no connection."
                )

            # A closed connection must never be handed to application code.
            if conn.closed:
                _discard_pooled_connection(
                    pool,
                    conn,
                )

                # This is a pool-health event, not an application failure.
                # Try again without sleeping unnecessarily.
                continue

            # Lightweight transaction-state reset.
            #
            # A pooled connection should normally already be clean, but
            # rollback here prevents accidental transaction leakage from
            # older call paths.
            try:
                conn.rollback()
            except Exception as exc:
                logger.warning(
                    "Discarding unhealthy pooled connection: %s",
                    exc,
                )

                _discard_pooled_connection(
                    pool,
                    conn,
                )

                continue

            return _PooledConnection(
                pool,
                conn,
            )

        except Exception as exc:

            last_error = exc

            if conn is not None:
                _discard_pooled_connection(
                    pool,
                    conn,
                )

            logger.warning(
                "DB connection attempt %s/%s failed: %s",
                attempt + 1,
                retries,
                exc,
            )

            if attempt < retries - 1:
                sleep_seconds = (
                    retry_delay
                    * (attempt + 1)
                )

                if sleep_seconds > 0:
                    time.sleep(
                        sleep_seconds
                    )

    raise RuntimeError(
        "Could not obtain a healthy database connection: "
        f"{last_error}"
    )


# ---------------------------------------------------------------------------
# Database initialization
# ---------------------------------------------------------------------------

def init_db():
    """
    Create required tables, indexes and safe schema defaults.

    Safe to call repeatedly because all operations are idempotent.
    """

    connection = None

    try:
        connection = get_db_connection()

        with connection.cursor() as cursor:

            # --------------------------------------------------------------
            # PostgreSQL UUID support
            # --------------------------------------------------------------

            cursor.execute(
                """
                CREATE EXTENSION IF NOT EXISTS pgcrypto;
                """
            )

            # --------------------------------------------------------------
            # USERS
            # --------------------------------------------------------------

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,

                    email TEXT UNIQUE NOT NULL,

                    name TEXT,

                    picture TEXT,

                    password_hash TEXT,

                    google_id TEXT UNIQUE,

                    created_at TIMESTAMPTZ
                        DEFAULT NOW(),

                    updated_at TIMESTAMPTZ
                        DEFAULT NOW()
                );
                """
            )

            # --------------------------------------------------------------
            # ANALYSES
            # --------------------------------------------------------------

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS analyses (
                    id UUID PRIMARY KEY
                        DEFAULT gen_random_uuid(),

                    user_id INTEGER NOT NULL
                        REFERENCES users(id)
                        ON DELETE CASCADE,

                    token_symbol TEXT NOT NULL,

                    report JSONB NOT NULL,

                    created_at TIMESTAMPTZ
                        DEFAULT NOW()
                );
                """
            )

            # IMPORTANT:
            # CREATE TABLE IF NOT EXISTS does NOT modify an existing table.
            # Therefore explicitly repair the UUID default for databases
            # created by an older version of the application.
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
                """
                CREATE INDEX IF NOT EXISTS
                idx_analyses_user_created
                ON analyses (
                    user_id,
                    created_at DESC
                );
                """
            )

            # --------------------------------------------------------------
            # ANALYSIS JOBS
            # --------------------------------------------------------------

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_jobs (
                    id UUID PRIMARY KEY
                        DEFAULT gen_random_uuid(),

                    user_id INTEGER NOT NULL
                        REFERENCES users(id)
                        ON DELETE CASCADE,

                    token_symbol TEXT NOT NULL,

                    chain_id TEXT,

                    contract_address TEXT,

                    status TEXT NOT NULL
                        DEFAULT 'queued',

                    progress INTEGER NOT NULL
                        DEFAULT 0,

                    stage TEXT,

                    stage_title TEXT,

                    message TEXT,

                    report JSONB,

                    meta JSONB,

                    error TEXT,

                    created_at TIMESTAMPTZ
                        DEFAULT NOW(),

                    started_at TIMESTAMPTZ,

                    updated_at TIMESTAMPTZ
                        DEFAULT NOW(),

                    completed_at TIMESTAMPTZ
                );
                """
            )

            # Repair the default for installations created before this
            # default existed.
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
                """
                CREATE INDEX IF NOT EXISTS
                idx_analysis_jobs_user_created
                ON analysis_jobs (
                    user_id,
                    created_at DESC
                );
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_analysis_jobs_status
                ON analysis_jobs (
                    status,
                    updated_at
                );
                """
            )

            # --------------------------------------------------------------
            # ACTIVE JOB DEDUPLICATION
            # --------------------------------------------------------------

            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS
                idx_analysis_jobs_active_unique
                ON analysis_jobs (
                    user_id,
                    token_symbol
                )
                WHERE status IN (
                    'queued',
                    'running',
                    'saving'
                );
                """
            )

        connection.commit()

        logger.info(
            "Database initialized successfully."
        )

    except Exception as exc:

        if connection is not None:
            try:
                connection.rollback()
            except Exception:
                logger.debug(
                    "Database rollback after init failure failed.",
                    exc_info=True,
                )

        logger.exception(
            "Database initialization failed: %s",
            exc,
        )

        raise

    finally:

        if connection is not None:
            connection.close()
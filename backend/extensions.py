import logging
import threading
from threading import Lock
import collections
from concurrent.futures import ThreadPoolExecutor
import psycopg2
import psycopg2.pool
import psycopg2.extras
from config import *

logger = logging.getLogger(__name__)

_db_pool = None
_db_pool_lock = threading.Lock()

_cache_lock = Lock()


ANALYSIS_EXECUTOR = ThreadPoolExecutor(
    max_workers=ANALYSIS_EXECUTOR_WORKERS,
    thread_name_prefix="analysis",
)


_market_cache = {}


_market_cap_cache = {}


_history_cache = {}


GEMINI_EXECUTOR = ThreadPoolExecutor(
    max_workers=GEMINI_EXECUTOR_WORKERS,
    thread_name_prefix="gemini-worker",
)


def _init_db_pool():
    """
    Lazily create a single shared connection pool.

    Fixes:
      - Opening/closing a brand-new TCP connection on every
        single query, which exhausts free-tier connection
        limits under any real concurrency.
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

        _db_pool = psycopg2.pool.ThreadedConnectionPool(
            DB_POOL_MIN_CONN,
            DB_POOL_MAX_CONN,
            dsn=DATABASE_URL,
            sslmode="require",
            connect_timeout=10,
        )

        return _db_pool


class _PooledConnection:
    """
    Thin wrapper so existing call sites can keep calling
    connection.cursor() / connection.commit() / connection.close()
    exactly as before, while the real connection is returned to
    the pool instead of being torn down.
    """

    def __init__(self, pool, conn):
        self._pool = pool
        self._conn = conn

    # FIX (Bug 10): support `with get_db_connection() as conn:` usage.
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            try:
                self.rollback()
            except Exception:
                pass
        self.close()
        return False

    def cursor(self, *args, **kwargs):
        return self._conn.cursor(*args, **kwargs)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        try:
            self._pool.putconn(self._conn)
        except Exception as exc:
            logger.debug(
                "Could not return connection to pool: %s",
                exc,
            )


def get_db_connection():
    """
    Get a pooled PostgreSQL connection, with retry/backoff.

    Fixes:
      - No connection pooling (every call opened a fresh
        connection, which exhausts free-tier connection caps
        under concurrency).
      - No retry against transient failures, which is the
        main cause of "sometimes it fetches, sometimes it
        doesn't" on serverless/auto-suspend Postgres hosts
        (Neon, Supabase) that need a moment to wake up.
    """

    pool = _init_db_pool()

    last_error = None

    for attempt in range(DB_CONNECT_RETRIES):

        try:

            conn = pool.getconn()

            # Detect dead/stale pooled connections instead of
            # handing back a broken one. Don't consume a retry
            # attempt for stale connections — the pool itself
            # is fine, it just handed back a bad connection.
            if conn.closed:
                pool.putconn(conn, close=True)
                # Retry, allowing the loop to consume an attempt
                continue

            return _PooledConnection(pool, conn)

        except Exception as exc:

            last_error = exc

            logger.warning(
                "DB connection attempt %s/%s failed: %s",
                attempt + 1,
                DB_CONNECT_RETRIES,
                exc,
            )

            if attempt < DB_CONNECT_RETRIES - 1:
                time.sleep(
                    DB_CONNECT_RETRY_DELAY * (attempt + 1)
                )

    raise RuntimeError(
        f"Could not obtain a database connection: {last_error}"
    )


def init_db():
    """
    Create all required tables and indexes.
    """

    connection = None

    try:
        connection = get_db_connection()

        with connection.cursor() as cursor:

            # ------------------------------------------------
            # USERS
            # ------------------------------------------------

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

            # ------------------------------------------------
            # ANALYSES
            # ------------------------------------------------

            # FIX (Bug 11): add DEFAULT gen_random_uuid() so INSERTs
            # that omit the id column (like save_analysis) get a UUID
            # automatically instead of a NOT NULL constraint violation.
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

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_analyses_user_created
                ON analyses(
                    user_id,
                    created_at DESC
                );
                """
            )

            # ------------------------------------------------
            # PERSISTENT ANALYSIS JOBS
            # ------------------------------------------------

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis_jobs (
                    id UUID PRIMARY KEY,

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

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_analysis_jobs_user_created
                ON analysis_jobs(
                    user_id,
                    created_at DESC
                );
                """
            )

            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS
                idx_analysis_jobs_status
                ON analysis_jobs(
                    status,
                    updated_at
                );
                """
            )

            # ------------------------------------------------
            # S4 — partial unique index preventing duplicate
            # active (queued/running/saving) jobs per user+symbol.
            # The unique constraint lets create_analysis_job()
            # detect races atomically via IntegrityError instead
            # of relying on a separate SELECT that two concurrent
            # requests could both pass before either INSERTs.
            # ------------------------------------------------
            cursor.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS
                idx_analysis_jobs_active_unique
                ON analysis_jobs (user_id, token_symbol)
                WHERE status IN ('queued', 'running', 'saving');
                """
            )

        connection.commit()

        logger.info(
            "Database initialized successfully."
        )

    except Exception as exc:

        logger.exception(
            "Database initialization failed: %s",
            exc,
        )

        raise

    finally:

        if connection:
            connection.close()



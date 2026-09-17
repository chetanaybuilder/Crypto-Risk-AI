"""
Database Persistence & Job State Repository.

Provides data-access abstractions for user accounts, analysis history serialization,
asynchronous job record lifecycle transitions, and active job deduplication.
"""

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

import psycopg2

from config import MAX_HISTORY_ROWS
from extensions import ANALYSIS_EXECUTOR, get_db_connection
from services.auth_service import hash_password
from utils.helpers import json_safe, normalize_symbol
from utils.math_helpers import clamp

logger = logging.getLogger(__name__)


def row_to_user(row) -> Optional[Dict[str, Any]]:
    """Convert a PostgreSQL user row into a public user dictionary."""
    if not row:
        return None

    return {
        "id": row[0],
        "email": row[1],
        "name": row[2],
        "picture": row[3],
        "created_at": row[6].isoformat() if row[6] else None,
    }


def get_user_by_id(user_id: Any) -> Optional[Dict[str, Any]]:
    """Retrieve user dictionary by primary ID."""
    if not user_id:
        return None

    user_id = str(user_id).strip()
    connection = None

    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, email, name, picture, password_hash, google_id, created_at
                FROM users
                WHERE id = %s
                LIMIT 1
                """,
                (user_id,),
            )
            row = cursor.fetchone()
            return row_to_user(row) if row else None
    finally:
        if connection:
            connection.close()


def get_user_by_email(email: str):
    """Retrieve raw database user row by email (for password verification)."""
    if not email:
        return None

    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, email, name, picture, password_hash, google_id, created_at
                FROM users
                WHERE LOWER(email) = LOWER(%s)
                LIMIT 1
                """,
                (email.strip(),),
            )
            return cursor.fetchone()
    finally:
        if connection:
            connection.close()


def create_local_user(email: str, password: str, name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Create a new local user with bcrypt hashed password."""
    if not email or not password:
        raise ValueError("Email and password are required.")

    email = str(email).strip().lower()
    if "@" not in email:
        raise ValueError("Invalid email address.")

    password_hash = hash_password(password)
    connection = None

    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users (email, name, password_hash)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (
                    email,
                    name.strip() if name else email.split("@")[0],
                    password_hash,
                ),
            )
            user_id = cursor.fetchone()[0]

        connection.commit()
        return get_user_by_id(user_id)

    except psycopg2.IntegrityError:
        if connection:
            connection.rollback()
        raise ValueError("An account with this email already exists.")
    finally:
        if connection:
            connection.close()


def create_or_update_google_user(
    google_id: str, email: str, name: Optional[str], picture: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Insert or update a user authenticated via Google OAuth."""
    if not google_id or not email:
        raise ValueError("Google account information is incomplete.")

    email = str(email).strip().lower()
    connection = None

    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM users WHERE google_id = %s LIMIT 1",
                (google_id,),
            )
            row = cursor.fetchone()

            if row:
                user_id = row[0]
                cursor.execute(
                    """
                    UPDATE users
                    SET email = %s, name = %s, picture = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (email, name, picture, user_id),
                )
            else:
                cursor.execute(
                    "SELECT id FROM users WHERE LOWER(email) = LOWER(%s) LIMIT 1",
                    (email,),
                )
                existing = cursor.fetchone()

                if existing:
                    user_id = existing[0]
                    cursor.execute(
                        """
                        UPDATE users
                        SET google_id = %s, name = %s, picture = %s, updated_at = NOW()
                        WHERE id = %s
                        """,
                        (google_id, name, picture, user_id),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO users (email, name, picture, google_id)
                        VALUES (%s, %s, %s, %s)
                        RETURNING id
                        """,
                        (email, name, picture, google_id),
                    )
                    user_id = cursor.fetchone()[0]

        connection.commit()
        return get_user_by_id(user_id)

    except psycopg2.IntegrityError as exc:
        if connection:
            connection.rollback()
        logger.exception("Google user database conflict: %s", exc)
        raise ValueError("Unable to link Google account.") from exc
    finally:
        if connection:
            connection.close()


def save_analysis(user_id: Any, token_symbol: str, report: Dict[str, Any]) -> str:
    """Save an analysis report to the database."""
    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO analyses (user_id, token_symbol, report)
                VALUES (%s, %s, %s::jsonb)
                RETURNING id
                """,
                (
                    user_id,
                    normalize_symbol(token_symbol),
                    json.dumps(json_safe(report), default=str),
                ),
            )
            analysis_id = cursor.fetchone()[0]

        connection.commit()
        return str(analysis_id)
    finally:
        if connection:
            connection.close()


def get_analysis_by_id(analysis_id: Any, user_id: Any) -> Optional[Dict[str, Any]]:
    """Retrieve an analysis report by ID and user ID."""
    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, token_symbol, report, created_at
                FROM analyses
                WHERE id = %s AND user_id = %s
                LIMIT 1
                """,
                (analysis_id, user_id),
            )
            row = cursor.fetchone()
            if not row:
                return None

            return {
                "id": str(row[0]),
                "token_symbol": row[1],
                "report": row[2] or {},
                "created_at": row[3].isoformat() if row[3] else None,
            }
    finally:
        if connection:
            connection.close()


def get_user_history(user_id: Any, limit: int = MAX_HISTORY_ROWS) -> List[Dict[str, Any]]:
    """Retrieve past analysis reports for a given user."""
    connection = None
    safe_limit = max(1, min(MAX_HISTORY_ROWS, int(limit)))

    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, token_symbol, report, created_at
                FROM analyses
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (user_id, safe_limit),
            )
            rows = cursor.fetchall()

            history = []
            for row in rows:
                report = row[2] or {}
                history.append({
                    "id": str(row[0]),
                    "token_symbol": row[1],
                    "risk_score": report.get("risk_score"),
                    "risk_label": report.get("risk_label"),
                    "created_at": row[3].isoformat() if row[3] else None,
                })
            return history
    finally:
        if connection:
            connection.close()


def delete_analysis(analysis_id: Any, user_id: Any) -> bool:
    """Delete a single analysis by ID for a user."""
    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM analyses WHERE id = %s AND user_id = %s",
                (analysis_id, user_id),
            )
            deleted = cursor.rowcount > 0

        connection.commit()
        return deleted
    finally:
        if connection:
            connection.close()


def delete_all_analyses(user_id: Any) -> int:
    """Delete all stored analyses for a user."""
    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM analyses WHERE user_id = %s", (user_id,))
            count = cursor.rowcount

        connection.commit()
        return count
    finally:
        if connection:
            connection.close()


def row_to_job(row) -> Optional[Dict[str, Any]]:
    """Map a raw database job row to a job dictionary."""
    if not row:
        return None

    return {
        "id": str(row[0]),
        "user_id": row[1],
        "token_symbol": row[2],
        "chain_id": row[3],
        "contract_address": row[4],
        "status": row[5],
        "progress": int(row[6] or 0),
        "stage": row[7],
        "stage_title": row[8],
        "message": row[9],
        "report": row[10] or {},
        "meta": row[11] or {},
        "error": row[12],
        "created_at": row[13].isoformat() if row[13] else None,
        "started_at": row[14].isoformat() if row[14] else None,
        "updated_at": row[15].isoformat() if row[15] else None,
        "completed_at": row[16].isoformat() if row[16] else None,
    }


def create_analysis_job(
    user_id: Any, token_symbol: str, chain_id: Optional[str] = None, contract_address: Optional[str] = None
) -> str:
    """Create a new async analysis job record or return existing active job ID."""
    symbol = normalize_symbol(token_symbol)
    if not symbol:
        raise ValueError("Invalid token symbol.")

    job_id = str(uuid.uuid4())
    connection = None

    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            try:
                cursor.execute(
                    """
                    INSERT INTO analysis_jobs (
                        id, user_id, token_symbol, chain_id, contract_address,
                        status, progress, stage, stage_title, message
                    )
                    VALUES (%s, %s, %s, %s, %s, 'queued', 5, 'queued', 'Preparing analysis', 'Analysis job created.')
                    """,
                    (job_id, user_id, symbol, chain_id, contract_address),
                )
            except Exception as exc:
                error_msg = str(exc)
                if "idx_analysis_jobs_active_unique" not in error_msg:
                    raise

                logger.info(
                    "[JOBS] %s duplicate active job detected for user %s (%s); returning existing job",
                    symbol,
                    user_id,
                    error_msg,
                )
                connection.rollback()

                cursor.execute(
                    """
                    SELECT id FROM analysis_jobs
                    WHERE user_id = %s AND token_symbol = %s AND status IN ('queued', 'running', 'saving')
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (user_id, symbol),
                )
                row = cursor.fetchone()
                if row:
                    return str(row[0])
                raise

        connection.commit()
        return job_id
    finally:
        if connection:
            connection.close()


def get_analysis_job(job_id: str, user_id: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    """Retrieve an analysis job by ID and optional user filter."""
    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            base_query = """
                SELECT
                    id, user_id, token_symbol, chain_id, contract_address,
                    status, progress, stage, stage_title, message,
                    report, meta, error, created_at, started_at, updated_at, completed_at
                FROM analysis_jobs
                WHERE id = %s
            """
            if user_id is not None:
                base_query += " AND user_id = %s LIMIT 1"
                cursor.execute(base_query, (job_id, user_id))
            else:
                base_query += " LIMIT 1"
                cursor.execute(base_query, (job_id,))

            return row_to_job(cursor.fetchone())
    finally:
        if connection:
            connection.close()


def update_analysis_job(
    job_id: str,
    status: Optional[str] = None,
    progress: Optional[int] = None,
    stage: Optional[str] = None,
    stage_title: Optional[str] = None,
    message: Optional[str] = None,
    report: Optional[Dict[str, Any]] = None,
    meta: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    started: bool = False,
    completed: bool = False,
) -> None:
    """Update job fields dynamically."""
    fields = []
    values = []

    if status is not None:
        fields.append("status = %s")
        values.append(status)

    if progress is not None:
        fields.append("progress = %s")
        values.append(int(clamp(progress, 0, 100)))

    if stage is not None:
        fields.append("stage = %s")
        values.append(stage)

    if stage_title is not None:
        fields.append("stage_title = %s")
        values.append(stage_title)

    if message is not None:
        fields.append("message = %s")
        values.append(message)

    if report is not None:
        fields.append("report = %s::jsonb")
        values.append(json.dumps(json_safe(report), default=str))

    if meta is not None:
        fields.append("meta = %s::jsonb")
        values.append(json.dumps(json_safe(meta), default=str))

    if error is not None:
        fields.append("error = %s")
        values.append(str(error)[:2000])

    if started:
        fields.append("started_at = COALESCE(started_at, NOW())")

    if completed:
        fields.append("completed_at = NOW()")

    fields.append("updated_at = NOW()")
    values.append(job_id)

    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE analysis_jobs SET {', '.join(fields)} WHERE id = %s",
                values,
            )
        connection.commit()
    except Exception:
        if connection:
            connection.rollback()
        raise
    finally:
        if connection:
            connection.close()


def cleanup_old_analysis_jobs() -> None:
    """Remove completed or failed analysis jobs older than 24 hours."""
    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM analysis_jobs WHERE created_at < NOW() - INTERVAL '24 hours'"
            )
        connection.commit()
    except Exception as exc:
        logger.warning("Analysis job cleanup failed: %s", exc)
    finally:
        if connection:
            connection.close()


def submit_analysis_job(job_id: str) -> bool:
    """Submit an analysis job to the background execution thread pool."""
    from services.analysis_worker import execute_analysis_job

    try:
        ANALYSIS_EXECUTOR.submit(execute_analysis_job, job_id)
        return True
    except Exception as exc:
        logger.exception("Could not submit analysis job: %s", exc)
        try:
            update_analysis_job(
                job_id,
                status="failed",
                progress=100,
                stage="error",
                stage_title="Unable to start analysis",
                message="Background worker could not start.",
                error=str(exc)[:2000],
                completed=True,
            )
        except Exception:
            pass
        return False
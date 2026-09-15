import json
import uuid
import bcrypt
from utils.helpers import normalize_symbol, json_safe, clamp
import logging
import psycopg2
from config import *
from extensions import get_db_connection, ANALYSIS_EXECUTOR

logger = logging.getLogger(__name__)


def row_to_user(row):
    """
    Convert a PostgreSQL user row into the public user object.

    Expected columns:
        id
        email
        name
        picture
        password_hash
        google_id
        created_at
    """

    if not row:
        return None

    return {
        "id": row[0],
        "email": row[1],
        "name": row[2],
        "picture": row[3],
        "created_at": (
            row[6].isoformat()
            if row[6]
            else None
        ),
    }


def get_user_by_id(
    user_id,
):
    if not user_id:
        return None

    user_id = str(user_id).strip()
    connection = None

    try:
        connection = get_db_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    id,
                    email,
                    name,
                    picture,
                    password_hash,
                    google_id,
                    created_at
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


def get_user_by_email(
    email,
):
    connection = None

    try:
        connection = get_db_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    id,
                    email,
                    name,
                    picture,
                    password_hash,
                    google_id,
                    created_at
                FROM users
                WHERE LOWER(email) = LOWER(%s)
                LIMIT 1
                """,
                (email,),
            )

            return cursor.fetchone()

    finally:

        if connection:
            connection.close()


def create_local_user(
    email,
    password,
    name=None,
):

    if not email or not password:
        raise ValueError(
            "Email and password are required."
        )

    email = (
        str(email)
        .strip()
        .lower()
    )

    if "@" not in email:
        raise ValueError(
            "Invalid email address."
        )

    # FIX: the real `bcrypt` package (imported above) does not have a
    # `generate_password_hash` method — that's Flask-Bcrypt/Werkzeug's
    # API. The correct real-bcrypt call is hashpw(bytes, gensalt()).
    password_hash = bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")

    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO users (
                    email,
                    name,
                    password_hash
                )
                VALUES (
                    %s,
                    %s,
                    %s
                )
                RETURNING id
                """,
                (
                    email,
                    (
                        name.strip()
                        if name
                        else email.split("@")[0]
                    ),
                    password_hash,
                ),
            )

            user_id = cursor.fetchone()[0]

        connection.commit()

        return get_user_by_id(
            user_id
        )

    except psycopg2.IntegrityError:

        if connection:
            connection.rollback()

        raise ValueError(
            "An account with this email already exists."
        )

    finally:

        if connection:
            connection.close()


def create_or_update_google_user(
    google_id,
    email,
    name,
    picture,
):

    if not google_id or not email:
        raise ValueError(
            "Google account information is incomplete."
        )

    email = (
        str(email)
        .strip()
        .lower()
    )

    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            # ------------------------------------------------
            # First try Google ID.
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT id
                FROM users
                WHERE google_id = %s
                LIMIT 1
                """,
                (google_id,),
            )

            row = cursor.fetchone()

            if row:

                user_id = row[0]

                cursor.execute(
                    """
                    UPDATE users
                    SET
                        email = %s,
                        name = %s,
                        picture = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        email,
                        name,
                        picture,
                        user_id,
                    ),
                )

            else:

                # --------------------------------------------
                # Then try matching email.
                # --------------------------------------------

                cursor.execute(
                    """
                    SELECT id
                    FROM users
                    WHERE LOWER(email) = LOWER(%s)
                    LIMIT 1
                    """,
                    (email,),
                )

                existing = cursor.fetchone()

                if existing:

                    user_id = existing[0]

                    cursor.execute(
                        """
                        UPDATE users
                        SET
                            google_id = %s,
                            name = %s,
                            picture = %s,
                            updated_at = NOW()
                        WHERE id = %s
                        """,
                        (
                            google_id,
                            name,
                            picture,
                            user_id,
                        ),
                    )

                else:

                    cursor.execute(
                        """
                        INSERT INTO users (
                            email,
                            name,
                            picture,
                            google_id
                        )
                        VALUES (
                            %s,
                            %s,
                            %s,
                            %s
                        )
                        RETURNING id
                        """,
                        (
                            email,
                            name,
                            picture,
                            google_id,
                        ),
                    )

                    user_id = cursor.fetchone()[0]

        connection.commit()

        return get_user_by_id(
            user_id
        )

    except psycopg2.IntegrityError as exc:

        if connection:
            connection.rollback()

        logger.exception(
            "Google user database conflict: %s",
            exc,
        )

        raise ValueError(
            "Unable to link Google account."
        )

    finally:

        if connection:
            connection.close()


# ============================================================
# ANALYSIS HISTORY
# ============================================================
def save_analysis(
    user_id,
    token_symbol,
    report,
):
    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                INSERT INTO analyses (
                    user_id,
                    token_symbol,
                    report
                )
                VALUES (
                    %s,
                    %s,
                    %s::jsonb
                )
                RETURNING id
                """,
                (
                    user_id,
                    normalize_symbol(
                        token_symbol
                    ),
                    json.dumps(
                        json_safe(report),
                        default=str,
                    ),
                ),
            )

            analysis_id = cursor.fetchone()[0]

        connection.commit()

        return str(analysis_id)

    finally:

        if connection:
            connection.close()


def get_analysis_by_id(
    analysis_id,
    user_id,
):

    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    id,
                    token_symbol,
                    report,
                    created_at
                FROM analyses
                WHERE id = %s
                  AND user_id = %s
                LIMIT 1
                """,
                (
                    analysis_id,
                    user_id,
                ),
            )

            row = cursor.fetchone()

            if not row:
                return None

            return {
                "id": str(row[0]),
                "token_symbol": row[1],
                "report": row[2] or {},
                "created_at": (
                    row[3].isoformat()
                    if row[3]
                    else None
                ),
            }

    finally:

        if connection:
            connection.close()


def get_user_history(
    user_id,
    limit=MAX_HISTORY_ROWS,
):

    connection = None

    safe_limit = max(
        1,
        min(
            MAX_HISTORY_ROWS,
            int(limit),
        ),
    )

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    id,
                    token_symbol,
                    report,
                    created_at
                FROM analyses
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (
                    user_id,
                    safe_limit,
                ),
            )

            rows = cursor.fetchall()

            history = []

            for row in rows:

                report = row[2] or {}

                history.append({
                    "id": str(row[0]),

                    "token_symbol": row[1],

                    "risk_score": report.get(
                        "risk_score"
                    ),

                    "risk_label": report.get(
                        "risk_label"
                    ),

                    "created_at": (
                        row[3].isoformat()
                        if row[3]
                        else None
                    ),
                })

            return history

    finally:

        if connection:
            connection.close()


def delete_analysis(
    analysis_id,
    user_id,
):

    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                DELETE FROM analyses
                WHERE id = %s
                  AND user_id = %s
                """,
                (
                    analysis_id,
                    user_id,
                ),
            )

            deleted = (
                cursor.rowcount > 0
            )

        connection.commit()

        return deleted

    finally:

        if connection:
            connection.close()


def delete_all_analyses(
    user_id,
):

    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                DELETE FROM analyses
                WHERE user_id = %s
                """,
                (user_id,),
            )

            count = cursor.rowcount

        connection.commit()

        return count

    finally:

        if connection:
            connection.close()


def row_to_job(
    row,
):

    if not row:
        return None

    return {
        "id": str(row[0]),

        "user_id": row[1],

        "token_symbol": row[2],

        "chain_id": row[3],

        "contract_address": row[4],

        "status": row[5],

        "progress": int(
            row[6] or 0
        ),

        "stage": row[7],

        "stage_title": row[8],

        "message": row[9],

        "report": row[10] or {},

        "meta": row[11] or {},

        "error": row[12],

        "created_at": (
            row[13].isoformat()
            if row[13]
            else None
        ),

        "started_at": (
            row[14].isoformat()
            if row[14]
            else None
        ),

        "updated_at": (
            row[15].isoformat()
            if row[15]
            else None
        ),

        "completed_at": (
            row[16].isoformat()
            if row[16]
            else None
        ),
    }


def create_analysis_job(
    user_id,
    token_symbol,
    chain_id=None,
    contract_address=None,
):

    symbol = normalize_symbol(
        token_symbol
    )

    if not symbol:
        raise ValueError(
            "Invalid token symbol."
        )

    job_id = str(
        uuid.uuid4()
    )

    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            try:

                cursor.execute(
                    """
                    INSERT INTO analysis_jobs (
                        id,
                        user_id,
                        token_symbol,
                        chain_id,
                        contract_address,
                        status,
                        progress,
                        stage,
                        stage_title,
                        message
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        'queued',
                        5,
                        'queued',
                        'Preparing analysis',
                        'Analysis job created.'
                    )
                    """,
                    (
                        job_id,
                        user_id,
                        symbol,
                        chain_id,
                        contract_address,
                    ),
                )

            except Exception as exc:
                # S4 — unique-index race: another request for the same
                # user+symbol inserted an active job between our SELECT
                # and INSERT. The partial unique index
                # idx_analysis_jobs_active_unique turned the race into
                # an IntegrityError. Look up the existing active job
                # and return its id so the caller treats this as an
                # existing_job: true response.
                error_msg = str(exc)
                if "idx_analysis_jobs_active_unique" not in error_msg:
                    raise

                logger.info(
                    "[JOBS] %s duplicate active job detected for user %s "
                    "(%s); returning existing job",
                    symbol,
                    user_id,
                    error_msg,
                )

                connection.rollback()

                cursor.execute(
                    """
                    SELECT id
                    FROM analysis_jobs
                    WHERE user_id = %s
                      AND token_symbol = %s
                      AND status IN ('queued', 'running', 'saving')
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (user_id, symbol),
                )

                row = cursor.fetchone()

                if row:
                    return str(row[0])

                # Extremely narrow window: the conflicting job completed
                # between our INSERT failure and this SELECT. Fall
                # through to commit the original INSERT by re-raising.
                raise

        connection.commit()

        return job_id

    finally:

        if connection:
            connection.close()


def get_analysis_job(
    job_id,
    user_id=None,
):

    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            base_query = """
                SELECT
                    id,
                    user_id,
                    token_symbol,
                    chain_id,
                    contract_address,
                    status,
                    progress,
                    stage,
                    stage_title,
                    message,
                    report,
                    meta,
                    error,
                    created_at,
                    started_at,
                    updated_at,
                    completed_at
                FROM analysis_jobs
                WHERE id = %s
            """

            if user_id is not None:

                base_query += """
                    AND user_id = %s
                """

                base_query += """
                    LIMIT 1
                """

                cursor.execute(
                    base_query,
                    (
                        job_id,
                        user_id,
                    ),
                )

            else:

                base_query += """
                    LIMIT 1
                """

                cursor.execute(
                    base_query,
                    (job_id,),
                )

            return row_to_job(
                cursor.fetchone()
            )

    finally:

        if connection:
            connection.close()


def update_analysis_job(
    job_id,
    status=None,
    progress=None,
    stage=None,
    stage_title=None,
    message=None,
    report=None,
    meta=None,
    error=None,
    started=False,
    completed=False,
):

    fields = []
    values = []

    if status is not None:

        fields.append(
            "status = %s"
        )

        values.append(
            status
        )

    if progress is not None:

        fields.append(
            "progress = %s"
        )

        values.append(
            int(
                clamp(
                    progress,
                    0,
                    100,
                )
            )
        )

    if stage is not None:

        fields.append(
            "stage = %s"
        )

        values.append(
            stage
        )

    if stage_title is not None:

        fields.append(
            "stage_title = %s"
        )

        values.append(
            stage_title
        )

    if message is not None:

        fields.append(
            "message = %s"
        )

        values.append(
            message
        )

    if report is not None:

        fields.append(
            "report = %s::jsonb"
        )

        values.append(
            json.dumps(
                json_safe(report),
                default=str,
            )
        )

    if meta is not None:

        fields.append(
            "meta = %s::jsonb"
        )

        values.append(
            json.dumps(
                json_safe(meta),
                default=str,
            )
        )

    if error is not None:

        fields.append(
            "error = %s"
        )

        values.append(
            str(error)[:2000]
        )

    if started:

        fields.append(
            "started_at = "
            "COALESCE(started_at, NOW())"
        )

    if completed:

        fields.append(
            "completed_at = NOW()"
        )

    fields.append(
        "updated_at = NOW()"
    )

    values.append(
        job_id
    )

    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                f"""
                UPDATE analysis_jobs
                SET {", ".join(fields)}
                WHERE id = %s
                """,
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


def cleanup_old_analysis_jobs():

    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                DELETE FROM analysis_jobs
                WHERE created_at <
                    NOW() - INTERVAL '24 hours'
                """
            )

        connection.commit()

    except Exception as exc:

        logger.warning(
            "Analysis job cleanup failed: %s",
            exc,
        )

    finally:

        if connection:
            connection.close()


def submit_analysis_job(
    job_id,
):
    # FIX: `execute_analysis_job` was referenced but never imported
    # anywhere in this file, which would raise a NameError as soon as
    # a job got submitted. Importing it lazily here (rather than at
    # module load time) also sidesteps any circular-import issues if
    # that module imports from db_service.
    #
    # >>> Update this import path to wherever execute_analysis_job
    # >>> actually lives in your project (e.g. services.analysis_worker).
    from analysis_worker import execute_analysis_job

    try:

        ANALYSIS_EXECUTOR.submit(
            execute_analysis_job,
            job_id,
        )

        return True

    except Exception as exc:

        logger.exception(
            "Could not submit analysis job: %s",
            exc,
        )

        try:

            update_analysis_job(
                job_id,

                status="failed",

                progress=100,

                stage="error",

                stage_title=(
                    "Unable to start analysis"
                ),

                message=(
                    "Background worker could not start."
                ),

                error=str(exc)[:2000],

                completed=True,
            )

        except Exception:
            pass

        return False
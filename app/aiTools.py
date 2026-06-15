"""
aiTools.py — database connection utilities and schema fetching.

fetch_schema(db: DatabaseConnection) -> str
    Connects to the user's database, runs the appropriate schema introspection
    query for the db_type, and returns a compact AI-ready string like:
        orders (id integer, customer_id integer, total numeric, created_at timestamp)
        customers (id integer, name text, email text)
        ...
    Returns an empty string and logs the error if connection fails.
"""

import logging
from .models import DatabaseConnection

logger = logging.getLogger('app.db')


# ── Schema introspection queries ───────────────────────────────────────────────

# PostgreSQL — includes row counts and FK relationships
_SCHEMA_POSTGRESQL = """
WITH col_info AS (
    SELECT
        c.table_name,
        string_agg(
            c.column_name || ' ' || c.data_type
            || CASE WHEN tc.constraint_type = 'PRIMARY KEY' THEN ' PK' ELSE '' END
            || CASE WHEN fk.column_name IS NOT NULL
               THEN ' FK→' || ccu.table_name || '.' || ccu.column_name
               ELSE '' END,
            ', ' ORDER BY c.ordinal_position
        ) AS cols
    FROM information_schema.columns c
    LEFT JOIN information_schema.key_column_usage kcu
        ON kcu.table_schema = c.table_schema AND kcu.table_name = c.table_name
        AND kcu.column_name = c.column_name
    LEFT JOIN information_schema.table_constraints tc
        ON tc.constraint_name = kcu.constraint_name
        AND tc.constraint_type = 'PRIMARY KEY'
    LEFT JOIN information_schema.referential_constraints rc
        ON rc.constraint_name = kcu.constraint_name
    LEFT JOIN information_schema.key_column_usage fk
        ON fk.constraint_name = kcu.constraint_name AND fk.column_name = c.column_name
    LEFT JOIN information_schema.constraint_column_usage ccu
        ON ccu.constraint_name = rc.unique_constraint_name
    WHERE c.table_schema = 'public'
    GROUP BY c.table_name
),
row_counts AS (
    SELECT relname AS table_name, reltuples::bigint AS approx_rows
    FROM pg_class
    WHERE relkind = 'r'
)
SELECT string_agg(
    ci.table_name || ' (' || COALESCE(rc.approx_rows,0)::text || ' rows): ' || ci.cols,
    E'\\n'
)
FROM col_info ci
LEFT JOIN row_counts rc ON rc.table_name = ci.table_name;
"""

# MySQL — includes row counts from information_schema
_SCHEMA_MYSQL = """
SELECT GROUP_CONCAT(table_summary ORDER BY table_name SEPARATOR '\n') AS ai_ready_schema
FROM (
    SELECT
        CONCAT(
            c.TABLE_NAME, ' (', COALESCE(t.TABLE_ROWS, 0), ' rows): ',
            GROUP_CONCAT(
                CONCAT(c.COLUMN_NAME, ' ', c.DATA_TYPE,
                    IF(c.COLUMN_KEY = 'PRI', ' PK', ''),
                    IF(c.COLUMN_KEY = 'MUL', ' FK', ''))
                ORDER BY c.ORDINAL_POSITION
                SEPARATOR ', '
            )
        ) AS table_summary,
        c.TABLE_NAME
    FROM INFORMATION_SCHEMA.COLUMNS c
    LEFT JOIN INFORMATION_SCHEMA.TABLES t
        ON t.TABLE_NAME = c.TABLE_NAME AND t.TABLE_SCHEMA = c.TABLE_SCHEMA
    WHERE c.TABLE_SCHEMA = DATABASE()
    GROUP BY c.TABLE_NAME, t.TABLE_ROWS
) AS subquery;
"""

# SQL Server
_SCHEMA_MSSQL = """
SELECT STRING_AGG(table_summary, CHAR(10)) AS ai_ready_schema
FROM (
    SELECT
        c.TABLE_NAME + ' (' +
        STRING_AGG(c.COLUMN_NAME + ' ' + c.DATA_TYPE
            + CASE WHEN pk.COLUMN_NAME IS NOT NULL THEN ' PK' ELSE '' END,
            ', ')
        WITHIN GROUP (ORDER BY c.ORDINAL_POSITION)
        + ')' AS table_summary
    FROM INFORMATION_SCHEMA.COLUMNS c
    LEFT JOIN (
        SELECT ku.TABLE_NAME, ku.COLUMN_NAME
        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
            ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
        WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
    ) pk ON pk.TABLE_NAME = c.TABLE_NAME AND pk.COLUMN_NAME = c.COLUMN_NAME
    WHERE c.TABLE_SCHEMA = 'dbo'
    GROUP BY c.TABLE_NAME
) AS subquery;
"""

# SQLite: no information_schema — use sqlite_master + PRAGMA
# We handle this differently (see _fetch_sqlite_schema below)


def _get_connection(db: DatabaseConnection):
    """
    Returns a raw DB-API connection for the given DatabaseConnection record.
    Raises an exception if connection fails or db_type is unsupported.
    """
    db_type = db.db_type

    # Build DSN from either connection_string or individual fields
    if db.connection_string:
        dsn = db.connection_string
    else:
        host     = db.host
        port     = db.port
        db_name  = db.db_name
        user     = db.db_user
        password = db.db_password

    if db_type == 'postgresql':
        import psycopg2
        if db.connection_string:
            conn = psycopg2.connect(db.connection_string)
        else:
            conn = psycopg2.connect(
                host=host, port=port or 5432,
                dbname=db_name, user=user, password=password,
                sslmode='require' if db.use_ssl else 'prefer',
            )
        return conn

    elif db_type == 'mysql':
        import pymysql
        if db.connection_string:
            # pymysql doesn't accept a URL string directly — parse it
            from urllib.parse import urlparse
            p = urlparse(db.connection_string)
            conn = pymysql.connect(
                host=p.hostname, port=p.port or 3306,
                db=p.path.lstrip('/'), user=p.username, password=p.password,
                ssl={'ssl': {}} if db.use_ssl else None,
                cursorclass=pymysql.cursors.Cursor,
            )
        else:
            conn = pymysql.connect(
                host=host, port=int(port or 3306),
                db=db_name, user=user, password=password,
                ssl={'ssl': {}} if db.use_ssl else None,
                cursorclass=pymysql.cursors.Cursor,
            )
        return conn

    elif db_type == 'mssql':
        import pyodbc  # must be installed separately
        if db.connection_string:
            conn = pyodbc.connect(db.connection_string)
        else:
            driver = '{ODBC Driver 18 for SQL Server}'
            conn_str = (
                f'DRIVER={driver};SERVER={host},{port or 1433};'
                f'DATABASE={db_name};UID={user};PWD={password};'
            )
            if db.use_ssl:
                conn_str += 'Encrypt=yes;TrustServerCertificate=no;'
            conn = pyodbc.connect(conn_str)
        return conn

    elif db_type == 'sqlite':
        import sqlite3
        import os
        from django.conf import settings

        # File-based (uploaded CSV/Excel) uses sqlite_path; otherwise connection_string or db_name
        raw_path = getattr(db, 'sqlite_path', '') or db.connection_string or db.db_name

        # sqlite_path may be stored as absolute (old records) or relative to BASE_DIR.
        # If the absolute path doesn't exist, try resolving it relative to BASE_DIR
        # by extracting the portion starting at 'user_data/'.
        if raw_path and not os.path.exists(raw_path):
            # Attempt to remap: find 'user_data/' in the stored path and rebuild
            marker = 'user_data' + os.sep
            idx = raw_path.find(marker)
            if idx == -1:
                marker = 'user_data/'
                idx = raw_path.find(marker)
            if idx != -1:
                relative = raw_path[idx:]  # e.g. "user_data/1/Cars_Dataset_1.db"
                resolved = os.path.join(settings.BASE_DIR, relative)
                if os.path.exists(resolved):
                    raw_path = resolved

        conn = sqlite3.connect(raw_path)
        return conn

    else:
        raise ValueError(f"Unsupported db_type: {db_type}")


def _fetch_sqlite_schema(conn) -> str:
    """
    SQLite schema with:
    - Column names and types
    - Primary key flags
    - Foreign key relationships
    - Row count per table
    - Up to 5 sample distinct values per text column (so the LLM knows real values)
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name;"
    )
    tables = [row[0] for row in cursor.fetchall()]

    lines = []
    for table in tables:
        # Column info
        cursor.execute(f'PRAGMA table_info("{table}");')
        cols = cursor.fetchall()  # cid, name, type, notnull, dflt_value, pk

        # Row count
        try:
            cursor.execute(f'SELECT COUNT(*) FROM "{table}";')
            row_count = cursor.fetchone()[0]
        except Exception:
            row_count = '?'

        # Foreign keys
        cursor.execute(f'PRAGMA foreign_key_list("{table}");')
        fk_rows = cursor.fetchall()  # id, seq, table, from, to, ...
        fk_map = {fk[3]: f'→{fk[2]}.{fk[4]}' for fk in fk_rows}

        col_parts = []
        for col in cols:
            col_name  = col[1]
            col_type  = col[2].lower() or 'text'
            pk_flag   = ' PK' if col[5] else ''
            fk_flag   = f' FK{fk_map[col_name]}' if col_name in fk_map else ''

            # Sample distinct values for text-like columns (not for numeric/blob)
            sample_hint = ''
            if any(t in col_type for t in ('text', 'char', 'varchar', 'string', 'name')):
                try:
                    cursor.execute(
                        f'SELECT DISTINCT "{col_name}" FROM "{table}" '
                        f'WHERE "{col_name}" IS NOT NULL AND "{col_name}" != "" '
                        f'LIMIT 5;'
                    )
                    samples = [str(r[0]) for r in cursor.fetchall() if r[0] is not None]
                    if samples:
                        sample_hint = f' [e.g. {", ".join(samples[:5])}]'
                except Exception:
                    pass

            col_parts.append(f'{col_name} {col_type}{pk_flag}{fk_flag}{sample_hint}')

        lines.append(f'{table} ({row_count} rows): {", ".join(col_parts)}')

    return '\n'.join(lines)


def fetch_schema(db: DatabaseConnection) -> str:
    """
    Main entry point. Connects to the database, runs the appropriate schema
    query, and returns the AI-ready schema string.

    Returns '' on any error (caller decides what to do with that).
    """
    if not db.store_credentials:
        # No credentials stored — can't connect
        return ''

    try:
        conn = _get_connection(db)

        if db.db_type == 'sqlite':
            schema = _fetch_sqlite_schema(conn)
        else:
            query_map = {
                'postgresql': _SCHEMA_POSTGRESQL,
                'mysql':      _SCHEMA_MYSQL,
                'mssql':      _SCHEMA_MSSQL,
            }
            sql = query_map[db.db_type]
            cursor = conn.cursor()
            cursor.execute(sql)
            row = cursor.fetchone()
            schema = row[0] if row and row[0] else ''
            cursor.close()

        conn.close()
        return schema.strip()

    except Exception as e:
        logger.error(f"[SCHEMA FETCH FAILED] db='{db.label}' type={db.db_type} error={e}", exc_info=True)
        return ''


# ── Query executor ─────────────────────────────────────────────────────────────

def execute_query(db: DatabaseConnection, sql: str) -> dict:
    """
    Execute a SQL string against the database and return:
        {
            "columns": ["col1", "col2", ...],
            "rows":    [["val", "val"], ...],
            "error":   ""          # non-empty string if execution failed
        }
    Limits results to 200 rows to avoid overwhelming the LLM context.
    """
    try:
        conn = _get_connection(db)
        cursor = conn.cursor()
        cursor.execute(sql)

        # Fetch column names
        columns = [desc[0] for desc in cursor.description] if cursor.description else []

        raw_rows = cursor.fetchmany(200)
        # Convert every value to a plain Python type (handles Decimal, date, etc.)
        rows = [[str(v) if v is not None else '' for v in row] for row in raw_rows]

        cursor.close()
        conn.close()
        return {"columns": columns, "rows": rows, "error": ""}

    except Exception as e:
        logger.error(f"[EXECUTE FAILED] db='{db.label}' sql='{sql[:120]}' error={e}", exc_info=True)
        return {"columns": [], "rows": [], "error": str(e)}

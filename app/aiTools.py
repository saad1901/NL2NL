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

# PostgreSQL / SQL Server (information_schema, string_agg)
_SCHEMA_POSTGRESQL = """
SELECT string_agg(table_summary, E'\\n') AS ai_ready_schema
FROM (
    SELECT
        table_name || ' (' ||
        string_agg(column_name || ' ' || data_type, ', ' ORDER BY ordinal_position)
        || ')' AS table_summary
    FROM information_schema.columns
    WHERE table_schema = 'public'
    GROUP BY table_name
) AS subquery;
"""

# SQL Server uses NVARCHAR / sys.columns — information_schema works but
# STRING_AGG is available from SQL Server 2017+. We target that.
_SCHEMA_MSSQL = """
SELECT STRING_AGG(table_summary, CHAR(10)) AS ai_ready_schema
FROM (
    SELECT
        c.TABLE_NAME + ' (' +
        STRING_AGG(c.COLUMN_NAME + ' ' + c.DATA_TYPE, ', ')
        WITHIN GROUP (ORDER BY c.ORDINAL_POSITION)
        + ')' AS table_summary
    FROM INFORMATION_SCHEMA.COLUMNS c
    WHERE c.TABLE_SCHEMA = 'dbo'
    GROUP BY c.TABLE_NAME
) AS subquery;
"""

# MySQL uses GROUP_CONCAT instead of string_agg
_SCHEMA_MYSQL = """
SELECT GROUP_CONCAT(table_summary ORDER BY table_name SEPARATOR '\n') AS ai_ready_schema
FROM (
    SELECT
        CONCAT(
            TABLE_NAME, ' (',
            GROUP_CONCAT(
                CONCAT(COLUMN_NAME, ' ', DATA_TYPE)
                ORDER BY ORDINAL_POSITION
                SEPARATOR ', '
            ),
            ')'
        ) AS table_summary,
        TABLE_NAME
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
    GROUP BY TABLE_NAME
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
        # File-based (uploaded CSV/Excel) uses sqlite_path; otherwise connection_string or db_name
        path = getattr(db, 'sqlite_path', '') or db.connection_string or db.db_name
        conn = sqlite3.connect(path)
        return conn

    else:
        raise ValueError(f"Unsupported db_type: {db_type}")


def _fetch_sqlite_schema(conn) -> str:
    """
    SQLite doesn't have information_schema.
    We iterate all user tables and run PRAGMA table_info() for each.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;")
    tables = [row[0] for row in cursor.fetchall()]

    lines = []
    for table in tables:
        cursor.execute(f'PRAGMA table_info("{table}");')
        cols = cursor.fetchall()
        # PRAGMA columns: cid, name, type, notnull, dflt_value, pk
        col_parts = ', '.join(f"{col[1]} {col[2].lower() or 'text'}" for col in cols)
        lines.append(f"{table} ({col_parts})")

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

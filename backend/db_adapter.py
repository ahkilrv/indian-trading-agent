"""Unified database adapter for SQLite (local) and PostgreSQL (production).

All application code targets PostgreSQL syntax (the canonical target).
The adapter auto-translates to SQLite dialect when running locally.
"""

import os
import re
import threading
from contextlib import contextmanager


# Connection pool for PostgreSQL (lazy-initialized, thread-safe)
_pg_pool = None
_pg_pool_lock = threading.Lock()


def _get_pg_pool():
    """Get or create the PostgreSQL connection pool (min=1, max=2)."""
    global _pg_pool
    if _pg_pool is None:
        with _pg_pool_lock:
            if _pg_pool is None:
                import psycopg2
                from psycopg2 import pool
                dsn = os.environ["DATABASE_URL"]
                _pg_pool = pool.ThreadedConnectionPool(1, 2, dsn)
    return _pg_pool


def _is_postgres():
    url = os.environ.get("DATABASE_URL", "")
    return url.startswith("postgresql://") or url.startswith("postgres://")


def _translate(sql: str) -> str:
    """Translate PostgreSQL SQL to SQLite-compatible SQL."""
    if _is_postgres():
        return sql
    sql = sql.replace("%s", "?")
    sql = re.sub(r"\s+RETURNING\s+\S+", "", sql, flags=re.IGNORECASE)
    return sql


class _CursorWrapper:
    def __init__(self, cursor, is_pg: bool):
        self._cursor = cursor
        self._is_pg = is_pg

    def fetchone(self):
        row = self._cursor.fetchone()
        return dict(row) if row else None

    def fetchall(self):
        return [dict(r) for r in self._cursor.fetchall()]


class _SQLiteWrapper:
    def __init__(self, conn):
        self._conn = conn
        self._cursor = None

    def execute(self, sql: str, params=None):
        sql = _translate(sql)
        self._cursor = self._conn.execute(sql, params or ())
        return _CursorWrapper(self._cursor, is_pg=False)

    def executescript(self, sql: str):
        self._conn.executescript(sql)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

    @property
    def lastrowid(self):
        return self._cursor.lastrowid if self._cursor else None


class _PGWrapper:
    def __init__(self, conn):
        self._conn = conn
        self._cursor = None

    def execute(self, sql: str, params=None):
        from psycopg2.extras import RealDictCursor
        if self._cursor:
            try:
                self._cursor.close()
            except Exception:
                pass
        self._cursor = self._conn.cursor(cursor_factory=RealDictCursor)
        self._cursor.execute(sql, params or ())
        return _CursorWrapper(self._cursor, is_pg=True)

    def executescript(self, sql: str):
        for stmt in sql.split(";"):
            stmt = stmt.strip()
            if stmt:
                self.execute(stmt)

    def commit(self):
        self._conn.commit()

    def close(self):
        if self._cursor:
            self._cursor.close()
        self._conn.close()

    @property
    def lastrowid(self):
        return self._cursor.lastrowid if self._cursor else None


def _get_sqlite_path() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if url:
        path = os.path.expanduser(url)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path
    path = os.path.join(os.path.expanduser("~"), ".tradingagents", "trading_agent.db")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


@contextmanager
def get_db():
    if _is_postgres():
        pool = _get_pg_pool()
        conn = pool.getconn()
        try:
            conn.autocommit = False
            yield _PGWrapper(conn)
            conn.commit()
        finally:
            pool.putconn(conn)
    else:
        import sqlite3
        conn = sqlite3.connect(_get_sqlite_path())
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        yield _SQLiteWrapper(conn)
        conn.commit()
        conn.close()

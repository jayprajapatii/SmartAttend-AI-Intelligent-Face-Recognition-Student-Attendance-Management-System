"""
database/db_connector.py

MySQL connection pool for SmartAttend AI.
Provides a single shared pool plus a context-manager cursor so every
model/service can run queries safely without leaking connections.

Usage:
    from database.db_connector import db

    # SELECT
    rows = db.fetch_all("SELECT * FROM students WHERE department_id = %s", (dept_id,))
    row  = db.fetch_one("SELECT * FROM students WHERE student_id = %s", (student_id,))

    # INSERT / UPDATE / DELETE
    new_id = db.execute(
        "INSERT INTO students (full_name, enrollment_number) VALUES (%s, %s)",
        ("Jay Prajapati", "ENR2026001")
    )

    # Manual transaction (multiple statements, all-or-nothing)
    with db.transaction() as cursor:
        cursor.execute("UPDATE students SET is_active = FALSE WHERE student_id = %s", (sid,))
        cursor.execute("INSERT INTO audit_logs (...) VALUES (...)", (...))
"""

import logging
from contextlib import contextmanager

import mysql.connector
from mysql.connector import pooling, Error as MySQLError

import config

logger = logging.getLogger("SmartAttendAI.db")


class Database:
    """Thin wrapper around a mysql-connector-python connection pool."""

    _POOL_NAME = "smartattend_pool"
    _POOL_SIZE = 10

    def __init__(self):
        self._pool = None
        self._connect()

    # ------------------------------------------------------------
    # Pool setup
    # ------------------------------------------------------------
    def _connect(self):
        try:
            self._pool = pooling.MySQLConnectionPool(
                pool_name=self._POOL_NAME,
                pool_size=self._POOL_SIZE,
                pool_reset_session=True,
                host=config.DB_CONFIG["host"],
                port=config.DB_CONFIG["port"],
                database=config.DB_CONFIG["database"],
                user=config.DB_CONFIG["user"],
                password=config.DB_CONFIG["password"],
                autocommit=False,
                charset="utf8mb4",
                collation="utf8mb4_unicode_ci",
            )
            logger.info(
                "MySQL connection pool '%s' created (size=%d) -> %s@%s:%s/%s",
                self._POOL_NAME, self._POOL_SIZE,
                config.DB_CONFIG["user"], config.DB_CONFIG["host"],
                config.DB_CONFIG["port"], config.DB_CONFIG["database"],
            )
        except MySQLError as exc:
            logger.critical("Failed to create MySQL connection pool: %s", exc)
            raise

    def _get_connection(self):
        try:
            return self._pool.get_connection()
        except MySQLError as exc:
            logger.error("Failed to get connection from pool: %s", exc)
            raise

    # ------------------------------------------------------------
    # Cursor context manager (auto commit/rollback/close)
    # ------------------------------------------------------------
    @contextmanager
    def _cursor(self, dictionary: bool = True):
        conn = self._get_connection()
        cursor = conn.cursor(dictionary=dictionary)
        try:
            yield cursor
            conn.commit()
        except MySQLError as exc:
            conn.rollback()
            logger.error("Query failed, rolled back: %s", exc)
            raise
        finally:
            cursor.close()
            conn.close()  # returns connection to the pool

    @contextmanager
    def transaction(self, dictionary: bool = True):
        """
        Explicit multi-statement transaction.
        Commits only if the whole block succeeds; rolls back otherwise.
        """
        conn = self._get_connection()
        cursor = conn.cursor(dictionary=dictionary)
        try:
            yield cursor
            conn.commit()
            logger.debug("Transaction committed.")
        except MySQLError as exc:
            conn.rollback()
            logger.error("Transaction failed, rolled back: %s", exc)
            raise
        finally:
            cursor.close()
            conn.close()

    # ------------------------------------------------------------
    # Convenience query methods
    # ------------------------------------------------------------
    def fetch_all(self, query: str, params: tuple = None) -> list:
        with self._cursor() as cursor:
            cursor.execute(query, params or ())
            return cursor.fetchall()

    def fetch_one(self, query: str, params: tuple = None) -> dict | None:
        with self._cursor() as cursor:
            cursor.execute(query, params or ())
            return cursor.fetchone()

    def execute(self, query: str, params: tuple = None) -> int:
        """
        Run INSERT / UPDATE / DELETE.
        Returns lastrowid (for INSERT) or affected row count otherwise.
        """
        with self._cursor(dictionary=False) as cursor:
            cursor.execute(query, params or ())
            return cursor.lastrowid or cursor.rowcount

    def execute_many(self, query: str, param_list: list) -> int:
        """Bulk insert/update. e.g. bulk student import from Excel."""
        with self._cursor(dictionary=False) as cursor:
            cursor.executemany(query, param_list)
            return cursor.rowcount

    # ------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------
    def is_connected(self) -> bool:
        try:
            with self._cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            return True
        except MySQLError:
            return False


# Singleton instance - import this everywhere instead of instantiating directly
db = Database()
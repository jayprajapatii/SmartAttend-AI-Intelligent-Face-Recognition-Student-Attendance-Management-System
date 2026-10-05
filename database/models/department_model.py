"""
database/models/department_model.py

CRUD operations for the `departments` table.
"""

import logging
from database.db_connector import db

logger = logging.getLogger("SmartAttendAI.models.department")


class DepartmentModel:

    # ------------------------------------------------------------
    # Create
    # ------------------------------------------------------------
    @staticmethod
    def create(department_name: str, department_code: str, head_of_department: str = None) -> int:
        query = """
            INSERT INTO departments (department_name, department_code, head_of_department)
            VALUES (%s, %s, %s)
        """
        dept_id = db.execute(query, (department_name, department_code, head_of_department))
        logger.info("Department created: %s (id=%s)", department_name, dept_id)
        return dept_id

    # ------------------------------------------------------------
    # Read
    # ------------------------------------------------------------
    @staticmethod
    def get_by_id(department_id: int) -> dict | None:
        return db.fetch_one(
            "SELECT * FROM departments WHERE department_id = %s", (department_id,)
        )

    @staticmethod
    def get_by_code(department_code: str) -> dict | None:
        return db.fetch_one(
            "SELECT * FROM departments WHERE department_code = %s", (department_code,)
        )

    @staticmethod
    def get_all() -> list:
        return db.fetch_all("SELECT * FROM departments ORDER BY department_name ASC")

    @staticmethod
    def search(keyword: str) -> list:
        query = """
            SELECT * FROM departments
            WHERE department_name LIKE %s OR department_code LIKE %s
            ORDER BY department_name ASC
        """
        like = f"%{keyword}%"
        return db.fetch_all(query, (like, like))

    @staticmethod
    def get_with_student_count() -> list:
        """Used on the dashboard: department-wise student counts."""
        query = """
            SELECT d.department_id, d.department_name, d.department_code,
                   COUNT(s.student_id) AS student_count
            FROM departments d
            LEFT JOIN students s
                ON s.department_id = d.department_id AND s.is_active = TRUE
            GROUP BY d.department_id, d.department_name, d.department_code
            ORDER BY d.department_name ASC
        """
        return db.fetch_all(query)

    # ------------------------------------------------------------
    # Update
    # ------------------------------------------------------------
    @staticmethod
    def update(department_id: int, **fields) -> int:
        if not fields:
            return 0
        allowed = {"department_name", "department_code", "head_of_department"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return 0

        set_clause = ", ".join(f"{col} = %s" for col in updates)
        params = tuple(updates.values()) + (department_id,)
        query = f"UPDATE departments SET {set_clause} WHERE department_id = %s"
        rows_affected = db.execute(query, params)
        logger.info("Department %s updated: %s", department_id, list(updates.keys()))
        return rows_affected

    # ------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------
    @staticmethod
    def delete(department_id: int) -> int:
        rows_affected = db.execute(
            "DELETE FROM departments WHERE department_id = %s", (department_id,)
        )
        logger.info("Department %s deleted.", department_id)
        return rows_affected
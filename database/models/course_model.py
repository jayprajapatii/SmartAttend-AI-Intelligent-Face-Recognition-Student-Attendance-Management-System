"""
database/models/course_model.py

CRUD operations for the `courses` table.
"""

import logging
from database.db_connector import db

logger = logging.getLogger("SmartAttendAI.models.course")


class CourseModel:

    # ------------------------------------------------------------
    # Create
    # ------------------------------------------------------------
    @staticmethod
    def create(course_name: str, course_code: str, department_id: int, duration_years: int = None) -> int:
        query = """
            INSERT INTO courses (course_name, course_code, department_id, duration_years)
            VALUES (%s, %s, %s, %s)
        """
        course_id = db.execute(query, (course_name, course_code, department_id, duration_years))
        logger.info("Course created: %s (id=%s)", course_name, course_id)
        return course_id

    # ------------------------------------------------------------
    # Read
    # ------------------------------------------------------------
    @staticmethod
    def get_by_id(course_id: int) -> dict | None:
        return db.fetch_one("SELECT * FROM courses WHERE course_id = %s", (course_id,))

    @staticmethod
    def get_by_code(course_code: str) -> dict | None:
        return db.fetch_one("SELECT * FROM courses WHERE course_code = %s", (course_code,))

    @staticmethod
    def get_all() -> list:
        return db.fetch_all("SELECT * FROM courses ORDER BY course_name ASC")

    @staticmethod
    def get_by_department(department_id: int) -> list:
        return db.fetch_all(
            "SELECT * FROM courses WHERE department_id = %s ORDER BY course_name ASC",
            (department_id,),
        )

    @staticmethod
    def search(keyword: str) -> list:
        query = """
            SELECT * FROM courses
            WHERE course_name LIKE %s OR course_code LIKE %s
            ORDER BY course_name ASC
        """
        like = f"%{keyword}%"
        return db.fetch_all(query, (like, like))

    @staticmethod
    def get_with_student_count() -> list:
        query = """
            SELECT c.course_id, c.course_name, c.course_code,
                   COUNT(s.student_id) AS student_count
            FROM courses c
            LEFT JOIN students s ON s.course_id = c.course_id AND s.is_active = TRUE
            GROUP BY c.course_id, c.course_name, c.course_code
            ORDER BY c.course_name ASC
        """
        return db.fetch_all(query)

    # ------------------------------------------------------------
    # Update
    # ------------------------------------------------------------
    @staticmethod
    def update(course_id: int, **fields) -> int:
        if not fields:
            return 0
        allowed = {"course_name", "course_code", "department_id", "duration_years"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return 0

        set_clause = ", ".join(f"{col} = %s" for col in updates)
        params = tuple(updates.values()) + (course_id,)
        query = f"UPDATE courses SET {set_clause} WHERE course_id = %s"
        rows_affected = db.execute(query, params)
        logger.info("Course %s updated: %s", course_id, list(updates.keys()))
        return rows_affected

    # ------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------
    @staticmethod
    def delete(course_id: int) -> int:
        rows_affected = db.execute("DELETE FROM courses WHERE course_id = %s", (course_id,))
        logger.info("Course %s deleted.", course_id)
        return rows_affected
"""
database/models/faculty_model.py

CRUD operations for the `faculty` table, plus faculty<->subject
assignment via the `faculty_subjects` junction table.
"""

import logging
from database.db_connector import db

logger = logging.getLogger("SmartAttendAI.models.faculty")


class FacultyModel:

    # ------------------------------------------------------------
    # Create
    # ------------------------------------------------------------
    @staticmethod
    def create(
        faculty_name: str,
        department_id: int = None,
        email: str = None,
        phone: str = None,
        designation: str = None,
    ) -> int:
        query = """
            INSERT INTO faculty (faculty_name, department_id, email, phone, designation)
            VALUES (%s, %s, %s, %s, %s)
        """
        faculty_id = db.execute(query, (faculty_name, department_id, email, phone, designation))
        logger.info("Faculty created: %s (id=%s)", faculty_name, faculty_id)
        return faculty_id

    # ------------------------------------------------------------
    # Read
    # ------------------------------------------------------------
    @staticmethod
    def get_by_id(faculty_id: int) -> dict | None:
        return db.fetch_one("SELECT * FROM faculty WHERE faculty_id = %s", (faculty_id,))

    @staticmethod
    def get_all(active_only: bool = True) -> list:
        query = "SELECT * FROM faculty"
        if active_only:
            query += " WHERE is_active = TRUE"
        query += " ORDER BY faculty_name ASC"
        return db.fetch_all(query)

    @staticmethod
    def get_by_department(department_id: int) -> list:
        return db.fetch_all(
            "SELECT * FROM faculty WHERE department_id = %s AND is_active = TRUE "
            "ORDER BY faculty_name ASC",
            (department_id,),
        )

    @staticmethod
    def search(keyword: str) -> list:
        query = """
            SELECT * FROM faculty
            WHERE faculty_name LIKE %s OR email LIKE %s
            ORDER BY faculty_name ASC
        """
        like = f"%{keyword}%"
        return db.fetch_all(query, (like, like))

    @staticmethod
    def get_subjects(faculty_id: int) -> list:
        """All subjects currently assigned to this faculty member."""
        query = """
            SELECT s.subject_id, s.subject_name, s.subject_code, s.semester, s.course_id
            FROM subjects s
            INNER JOIN faculty_subjects fs ON fs.subject_id = s.subject_id
            WHERE fs.faculty_id = %s
            ORDER BY s.subject_name ASC
        """
        return db.fetch_all(query, (faculty_id,))

    @staticmethod
    def get_attendance_reports(faculty_id: int, start_date: str, end_date: str) -> list:
        """Attendance records taken by this faculty within a date range."""
        query = """
            SELECT a.attendance_id, a.attendance_date, a.attendance_status,
                   s.full_name AS student_name, s.roll_number,
                   sub.subject_name
            FROM attendance a
            INNER JOIN students s ON s.student_id = a.student_id
            LEFT JOIN subjects sub ON sub.subject_id = a.subject_id
            WHERE a.faculty_id = %s AND a.attendance_date BETWEEN %s AND %s
            ORDER BY a.attendance_date DESC
        """
        return db.fetch_all(query, (faculty_id, start_date, end_date))

    # ------------------------------------------------------------
    # Update
    # ------------------------------------------------------------
    @staticmethod
    def update(faculty_id: int, **fields) -> int:
        if not fields:
            return 0
        allowed = {"faculty_name", "department_id", "email", "phone", "designation", "is_active"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return 0

        set_clause = ", ".join(f"{col} = %s" for col in updates)
        params = tuple(updates.values()) + (faculty_id,)
        query = f"UPDATE faculty SET {set_clause} WHERE faculty_id = %s"
        rows_affected = db.execute(query, params)
        logger.info("Faculty %s updated: %s", faculty_id, list(updates.keys()))
        return rows_affected

    # ------------------------------------------------------------
    # Subject assignment (faculty_subjects junction table)
    # ------------------------------------------------------------
    @staticmethod
    def assign_subject(faculty_id: int, subject_id: int) -> int:
        query = """
            INSERT IGNORE INTO faculty_subjects (faculty_id, subject_id)
            VALUES (%s, %s)
        """
        result = db.execute(query, (faculty_id, subject_id))
        logger.info("Subject %s assigned to faculty %s.", subject_id, faculty_id)
        return result

    @staticmethod
    def unassign_subject(faculty_id: int, subject_id: int) -> int:
        query = """
            DELETE FROM faculty_subjects WHERE faculty_id = %s AND subject_id = %s
        """
        rows_affected = db.execute(query, (faculty_id, subject_id))
        logger.info("Subject %s unassigned from faculty %s.", subject_id, faculty_id)
        return rows_affected

    # ------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------
    @staticmethod
    def delete(faculty_id: int) -> int:
        rows_affected = db.execute("DELETE FROM faculty WHERE faculty_id = %s", (faculty_id,))
        logger.info("Faculty %s deleted.", faculty_id)
        return rows_affected

    @staticmethod
    def soft_delete(faculty_id: int) -> int:
        rows_affected = db.execute(
            "UPDATE faculty SET is_active = FALSE WHERE faculty_id = %s", (faculty_id,)
        )
        logger.info("Faculty %s deactivated.", faculty_id)
        return rows_affected
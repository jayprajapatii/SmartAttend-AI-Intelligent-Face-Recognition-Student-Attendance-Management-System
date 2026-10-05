"""
database/models/student_model.py

CRUD + search operations for the `students` table.
"""

import logging
from database.db_connector import db

logger = logging.getLogger("SmartAttendAI.models.student")


class StudentModel:

    # ------------------------------------------------------------
    # Create
    # ------------------------------------------------------------
    @staticmethod
    def create(
        enrollment_number: str,
        full_name: str,
        gender: str = None,
        date_of_birth: str = None,
        email: str = None,
        phone_number: str = None,
        parent_contact: str = None,
        department_id: int = None,
        course_id: int = None,
        semester: int = None,
        section: str = None,
        roll_number: str = None,
        address: str = None,
        photo_path: str = None,
    ) -> int:
        query = """
            INSERT INTO students (
                enrollment_number, full_name, gender, date_of_birth, email,
                phone_number, parent_contact, department_id, course_id,
                semester, section, roll_number, address, photo_path
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            enrollment_number, full_name, gender, date_of_birth, email,
            phone_number, parent_contact, department_id, course_id,
            semester, section, roll_number, address, photo_path,
        )
        student_id = db.execute(query, params)
        logger.info("Student created: %s (id=%s)", full_name, student_id)
        return student_id

    @staticmethod
    def bulk_create(students: list) -> int:
        """
        Bulk insert for Excel import.
        `students` is a list of tuples matching the column order below.
        """
        query = """
            INSERT INTO students (
                enrollment_number, full_name, gender, date_of_birth, email,
                phone_number, parent_contact, department_id, course_id,
                semester, section, roll_number, address
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        rows_inserted = db.execute_many(query, students)
        logger.info("Bulk import: %s students inserted.", rows_inserted)
        return rows_inserted

    # ------------------------------------------------------------
    # Read
    # ------------------------------------------------------------
    @staticmethod
    def get_by_id(student_id: int) -> dict | None:
        return db.fetch_one(
            "SELECT * FROM students WHERE student_id = %s", (student_id,)
        )

    @staticmethod
    def get_by_enrollment(enrollment_number: str) -> dict | None:
        return db.fetch_one(
            "SELECT * FROM students WHERE enrollment_number = %s", (enrollment_number,)
        )

    @staticmethod
    def get_all(active_only: bool = True) -> list:
        query = "SELECT * FROM students"
        if active_only:
            query += " WHERE is_active = TRUE"
        query += " ORDER BY full_name ASC"
        return db.fetch_all(query)

    @staticmethod
    def get_by_department(department_id: int) -> list:
        return db.fetch_all(
            "SELECT * FROM students WHERE department_id = %s AND is_active = TRUE "
            "ORDER BY full_name ASC",
            (department_id,),
        )

    @staticmethod
    def get_by_course_semester_section(course_id: int, semester: int, section: str) -> list:
        query = """
            SELECT * FROM students
            WHERE course_id = %s AND semester = %s AND section = %s AND is_active = TRUE
            ORDER BY roll_number ASC
        """
        return db.fetch_all(query, (course_id, semester, section))

    @staticmethod
    def search(keyword: str) -> list:
        """Search by ID, roll number, name, or enrollment number."""
        query = """
            SELECT * FROM students
            WHERE full_name LIKE %s
               OR roll_number LIKE %s
               OR enrollment_number LIKE %s
               OR student_id = %s
            ORDER BY full_name ASC
        """
        like = f"%{keyword}%"
        student_id_match = int(keyword) if keyword.isdigit() else -1
        return db.fetch_all(query, (like, like, like, student_id_match))

    @staticmethod
    def count_total(active_only: bool = True) -> int:
        query = "SELECT COUNT(*) AS total FROM students"
        if active_only:
            query += " WHERE is_active = TRUE"
        result = db.fetch_one(query)
        return result["total"] if result else 0

    # ------------------------------------------------------------
    # Update
    # ------------------------------------------------------------
    @staticmethod
    def update(student_id: int, **fields) -> int:
        if not fields:
            return 0
        allowed = {
            "full_name", "gender", "date_of_birth", "email", "phone_number",
            "parent_contact", "department_id", "course_id", "semester",
            "section", "roll_number", "address", "photo_path", "is_active",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return 0

        set_clause = ", ".join(f"{col} = %s" for col in updates)
        params = tuple(updates.values()) + (student_id,)
        query = f"UPDATE students SET {set_clause} WHERE student_id = %s"
        rows_affected = db.execute(query, params)
        logger.info("Student %s updated: %s", student_id, list(updates.keys()))
        return rows_affected

    # ------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------
    @staticmethod
    def delete(student_id: int) -> int:
        """Hard delete. Cascades to face_embeddings & attendance via FK."""
        rows_affected = db.execute(
            "DELETE FROM students WHERE student_id = %s", (student_id,)
        )
        logger.info("Student %s deleted.", student_id)
        return rows_affected

    @staticmethod
    def soft_delete(student_id: int) -> int:
        """Preferred over hard delete - keeps historical attendance records intact."""
        rows_affected = db.execute(
            "UPDATE students SET is_active = FALSE WHERE student_id = %s", (student_id,)
        )
        logger.info("Student %s deactivated.", student_id)
        return rows_affected
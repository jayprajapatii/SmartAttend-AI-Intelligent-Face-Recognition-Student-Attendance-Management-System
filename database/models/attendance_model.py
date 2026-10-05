"""
database/models/attendance_model.py

Core attendance operations: marking attendance (with duplicate/proxy
prevention), daily/weekly/monthly reports, and analytics queries used
by the dashboard and analytics pages.
"""

import logging
from datetime import date, datetime
from database.db_connector import db

logger = logging.getLogger("SmartAttendAI.models.attendance")


class AttendanceModel:

    # ------------------------------------------------------------
    # Mark attendance (with AI verification fields)
    # ------------------------------------------------------------
    @staticmethod
    def mark_attendance(
        student_id: int,
        subject_id: int = None,
        faculty_id: int = None,
        classroom: str = None,
        attendance_status: str = "Present",
        recognition_confidence: float = None,
        liveness_status: bool = False,
        emotion_detected: str = None,
        mask_status: str = None,
        verification_method: str = "Face",
        attendance_date: str = None,
    ) -> dict:
        """
        Marks attendance for a student. Relies on the UNIQUE KEY
        (student_id, subject_id, attendance_date) in the schema to
        prevent duplicate/proxy attendance for the same session.

        Returns: {"success": bool, "already_marked": bool, "attendance_id": int|None}
        """
        attendance_date = attendance_date or date.today().isoformat()
        time_in = datetime.now().strftime("%H:%M:%S")

        if AttendanceModel.is_already_marked(student_id, subject_id, attendance_date):
            logger.warning(
                "Duplicate attendance blocked: student=%s subject=%s date=%s",
                student_id, subject_id, attendance_date,
            )
            return {"success": False, "already_marked": True, "attendance_id": None}

        query = """
            INSERT INTO attendance (
                student_id, subject_id, faculty_id, classroom, attendance_date,
                time_in, attendance_status, recognition_confidence, liveness_status,
                emotion_detected, mask_status, verification_method
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            student_id, subject_id, faculty_id, classroom, attendance_date,
            time_in, attendance_status, recognition_confidence, liveness_status,
            emotion_detected, mask_status, verification_method,
        )
        attendance_id = db.execute(query, params)
        logger.info(
            "Attendance marked: student=%s subject=%s status=%s (id=%s)",
            student_id, subject_id, attendance_status, attendance_id,
        )
        return {"success": True, "already_marked": False, "attendance_id": attendance_id}

    @staticmethod
    def is_already_marked(student_id: int, subject_id: int, attendance_date: str) -> bool:
        query = """
            SELECT attendance_id FROM attendance
            WHERE student_id = %s
              AND attendance_date = %s
              AND (subject_id = %s OR (%s IS NULL AND subject_id IS NULL))
            LIMIT 1
        """
        result = db.fetch_one(query, (student_id, attendance_date, subject_id, subject_id))
        return result is not None

    # ------------------------------------------------------------
    # Read
    # ------------------------------------------------------------
    @staticmethod
    def get_by_id(attendance_id: int) -> dict | None:
        return db.fetch_one("SELECT * FROM attendance WHERE attendance_id = %s", (attendance_id,))

    @staticmethod
    def get_by_student(student_id: int, start_date: str = None, end_date: str = None) -> list:
        query = "SELECT * FROM attendance WHERE student_id = %s"
        params = [student_id]
        if start_date and end_date:
            query += " AND attendance_date BETWEEN %s AND %s"
            params += [start_date, end_date]
        query += " ORDER BY attendance_date DESC, time_in DESC"
        return db.fetch_all(query, tuple(params))

    @staticmethod
    def get_by_date(attendance_date: str, subject_id: int = None) -> list:
        query = """
            SELECT a.*, s.full_name, s.roll_number
            FROM attendance a
            INNER JOIN students s ON s.student_id = a.student_id
            WHERE a.attendance_date = %s
        """
        params = [attendance_date]
        if subject_id:
            query += " AND a.subject_id = %s"
            params.append(subject_id)
        query += " ORDER BY a.time_in ASC"
        return db.fetch_all(query, tuple(params))

    # ------------------------------------------------------------
    # Dashboard stats
    # ------------------------------------------------------------
    @staticmethod
    def get_today_summary() -> dict:
        today = date.today().isoformat()
        query = """
            SELECT
                (SELECT COUNT(*) FROM students WHERE is_active = TRUE) AS total_students,
                COUNT(DISTINCT CASE WHEN a.attendance_status = 'Present' THEN a.student_id END) AS present_today,
                COUNT(DISTINCT CASE WHEN a.attendance_status = 'Late' THEN a.student_id END) AS late_today
            FROM attendance a
            WHERE a.attendance_date = %s
        """
        result = db.fetch_one(query, (today,)) or {}
        total = result.get("total_students", 0) or 0
        present = result.get("present_today", 0) or 0
        late = result.get("late_today", 0) or 0
        return {
            "total_students": total,
            "present_today": present,
            "late_today": late,
            "absent_today": max(total - present - late, 0),
            "attendance_percentage": round((present / total) * 100, 1) if total else 0.0,
        }

    @staticmethod
    def get_recent_activity(limit: int = 10) -> list:
        query = """
            SELECT a.attendance_id, a.attendance_date, a.time_in, a.attendance_status,
                   a.recognition_confidence, s.full_name, s.roll_number
            FROM attendance a
            INNER JOIN students s ON s.student_id = a.student_id
            ORDER BY a.created_at DESC
            LIMIT %s
        """
        return db.fetch_all(query, (limit,))

    # ------------------------------------------------------------
    # Reports (daily / weekly / monthly / subject-wise / faculty-wise)
    # ------------------------------------------------------------
    @staticmethod
    def get_daily_report(target_date: str) -> list:
        return AttendanceModel.get_by_date(target_date)

    @staticmethod
    def get_weekly_report(start_date: str, end_date: str) -> list:
        query = """
            SELECT s.student_id, s.full_name, s.roll_number,
                   COUNT(a.attendance_id) AS days_present
            FROM students s
            LEFT JOIN attendance a
                ON a.student_id = s.student_id
                AND a.attendance_date BETWEEN %s AND %s
                AND a.attendance_status IN ('Present', 'Late')
            WHERE s.is_active = TRUE
            GROUP BY s.student_id, s.full_name, s.roll_number
            ORDER BY s.full_name ASC
        """
        return db.fetch_all(query, (start_date, end_date))

    @staticmethod
    def get_monthly_report(year: int, month: int) -> list:
        query = """
            SELECT s.student_id, s.full_name, s.roll_number,
                   COUNT(a.attendance_id) AS days_present
            FROM students s
            LEFT JOIN attendance a
                ON a.student_id = s.student_id
                AND YEAR(a.attendance_date) = %s
                AND MONTH(a.attendance_date) = %s
                AND a.attendance_status IN ('Present', 'Late')
            WHERE s.is_active = TRUE
            GROUP BY s.student_id, s.full_name, s.roll_number
            ORDER BY s.full_name ASC
        """
        return db.fetch_all(query, (year, month))

    @staticmethod
    def get_subject_wise_report(subject_id: int, start_date: str, end_date: str) -> list:
        query = """
            SELECT s.student_id, s.full_name, s.roll_number,
                   COUNT(a.attendance_id) AS classes_attended
            FROM students s
            LEFT JOIN attendance a
                ON a.student_id = s.student_id
                AND a.subject_id = %s
                AND a.attendance_date BETWEEN %s AND %s
                AND a.attendance_status IN ('Present', 'Late')
            WHERE s.is_active = TRUE
            GROUP BY s.student_id, s.full_name, s.roll_number
            ORDER BY s.full_name ASC
        """
        return db.fetch_all(query, (subject_id, start_date, end_date))

    @staticmethod
    def get_student_attendance_percentage(student_id: int, start_date: str, end_date: str) -> float:
        query = """
            SELECT
                COUNT(*) AS total_sessions,
                SUM(CASE WHEN attendance_status IN ('Present','Late') THEN 1 ELSE 0 END) AS attended
            FROM attendance
            WHERE student_id = %s AND attendance_date BETWEEN %s AND %s
        """
        result = db.fetch_one(query, (student_id, start_date, end_date))
        if not result or not result["total_sessions"]:
            return 0.0
        return round((result["attended"] / result["total_sessions"]) * 100, 1)

    # ------------------------------------------------------------
    # Analytics (trends, heatmap, department-wise)
    # ------------------------------------------------------------
    @staticmethod
    def get_daily_trend(start_date: str, end_date: str) -> list:
        query = """
            SELECT attendance_date,
                   COUNT(DISTINCT CASE WHEN attendance_status IN ('Present','Late') THEN student_id END) AS present_count,
                   COUNT(DISTINCT student_id) AS total_marked
            FROM attendance
            WHERE attendance_date BETWEEN %s AND %s
            GROUP BY attendance_date
            ORDER BY attendance_date ASC
        """
        return db.fetch_all(query, (start_date, end_date))

    @staticmethod
    def get_department_wise_stats(start_date: str, end_date: str) -> list:
        query = """
            SELECT d.department_name,
                   COUNT(DISTINCT CASE WHEN a.attendance_status IN ('Present','Late') THEN a.student_id END) AS present_count,
                   COUNT(DISTINCT s.student_id) AS total_students
            FROM departments d
            LEFT JOIN students s ON s.department_id = d.department_id AND s.is_active = TRUE
            LEFT JOIN attendance a
                ON a.student_id = s.student_id
                AND a.attendance_date BETWEEN %s AND %s
            GROUP BY d.department_id, d.department_name
            ORDER BY d.department_name ASC
        """
        return db.fetch_all(query, (start_date, end_date))

    @staticmethod
    def get_heatmap_data(start_date: str, end_date: str) -> list:
        """Attendance count grouped by date and hour - for heatmap visualization."""
        query = """
            SELECT attendance_date, HOUR(time_in) AS hour_of_day, COUNT(*) AS count
            FROM attendance
            WHERE attendance_date BETWEEN %s AND %s
            GROUP BY attendance_date, HOUR(time_in)
            ORDER BY attendance_date ASC, hour_of_day ASC
        """
        return db.fetch_all(query, (start_date, end_date))

    @staticmethod
    def get_low_attendance_students(threshold_percent: float, start_date: str, end_date: str) -> list:
        """Feeder query for the attendance-prediction / at-risk feature."""
        query = """
            SELECT s.student_id, s.full_name, s.roll_number,
                   COUNT(a.attendance_id) AS total_sessions,
                   SUM(CASE WHEN a.attendance_status IN ('Present','Late') THEN 1 ELSE 0 END) AS attended,
                   ROUND(
                       SUM(CASE WHEN a.attendance_status IN ('Present','Late') THEN 1 ELSE 0 END)
                       / COUNT(a.attendance_id) * 100, 1
                   ) AS attendance_percentage
            FROM students s
            INNER JOIN attendance a ON a.student_id = s.student_id
            WHERE s.is_active = TRUE AND a.attendance_date BETWEEN %s AND %s
            GROUP BY s.student_id, s.full_name, s.roll_number
            HAVING attendance_percentage < %s
            ORDER BY attendance_percentage ASC
        """
        return db.fetch_all(query, (start_date, end_date, threshold_percent))
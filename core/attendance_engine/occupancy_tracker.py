"""
core/attendance_engine/occupancy_tracker.py

Tracks live classroom occupancy during an active recognition session:
who's currently marked present vs. the expected roster, so the UI can
show a real-time "18 / 30 present (60%)" readout without re-querying
the database on every frame.

This is separate from AttendanceModel's historical/reporting queries
(get_today_summary, get_by_date, etc.) - this tracker is specifically
for the live, in-session view while a camera is actively running,
fed directly by AttendanceMarker's events rather than round-tripping
to the DB each update.

Usage:
    from core.attendance_engine.occupancy_tracker import occupancy_tracker

    occupancy_tracker.set_expected_roster(student_ids)  # e.g. all
                                                          # students in
                                                          # this course/section

    # Each time AttendanceMarker marks someone present:
    occupancy_tracker.mark_present(student_id)

    snapshot = occupancy_tracker.get_snapshot()
    print(snapshot.present_count, snapshot.total_count, snapshot.percentage)
"""

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger("SmartAttendAI.core.attendance_engine.occupancy_tracker")


@dataclass
class OccupancySnapshot:
    present_count: int
    total_count: int
    percentage: float
    present_student_ids: set = field(default_factory=set)
    absent_student_ids: set = field(default_factory=set)
    session_duration_sec: float = 0.0


class OccupancyTracker:
    """
    Stateful per-session occupancy tracker. Call set_expected_roster()
    at session start (e.g. all students in the selected course/section,
    or the full active student list for general/unscoped sessions),
    then mark_present() as each recognition event comes in.
    """

    def __init__(self):
        self._expected_roster = set()   # set[student_id]
        self._present = set()           # set[student_id]
        self._session_start = None

    # ------------------------------------------------------------
    # Session setup
    # ------------------------------------------------------------
    def set_expected_roster(self, student_ids: list):
        """
        Defines the full set of students expected to be present this
        session (e.g. everyone enrolled in a course/section, or every
        active student for a general/unscoped session).
        """
        self._expected_roster = set(student_ids)
        self._present = set()
        self._session_start = time.time()
        logger.info("Occupancy tracker session started with %d expected student(s).", len(self._expected_roster))

    def start_unscoped_session(self):
        """
        For sessions with no fixed roster (e.g. a general entrance
        camera, not tied to a specific class list) - occupancy is
        then just a running present-count with no absent side.
        """
        self._expected_roster = set()
        self._present = set()
        self._session_start = time.time()
        logger.info("Occupancy tracker session started (unscoped - no fixed roster).")

    # ------------------------------------------------------------
    # Live updates
    # ------------------------------------------------------------
    def mark_present(self, student_id: int):
        if self._session_start is None:
            self._session_start = time.time()
        is_new = student_id not in self._present
        self._present.add(student_id)
        if is_new:
            logger.debug("Occupancy: student_id=%s marked present (%d/%d).",
                         student_id, len(self._present), len(self._expected_roster) or len(self._present))

    def mark_absent(self, student_id: int):
        """Explicitly revert a student to absent (e.g. an admin correction mid-session)."""
        self._present.discard(student_id)

    def is_present(self, student_id: int) -> bool:
        return student_id in self._present

    # ------------------------------------------------------------
    # Snapshot / stats
    # ------------------------------------------------------------
    def get_snapshot(self) -> OccupancySnapshot:
        if self._expected_roster:
            total = len(self._expected_roster)
            present_ids = self._present & self._expected_roster
            absent_ids = self._expected_roster - self._present
        else:
            # Unscoped session - "total" is just however many unique
            # people have been seen so far; there's no absent concept.
            total = len(self._present)
            present_ids = set(self._present)
            absent_ids = set()

        percentage = round((len(present_ids) / total) * 100, 1) if total else 0.0
        duration = (time.time() - self._session_start) if self._session_start else 0.0

        return OccupancySnapshot(
            present_count=len(present_ids),
            total_count=total,
            percentage=percentage,
            present_student_ids=present_ids,
            absent_student_ids=absent_ids,
            session_duration_sec=round(duration, 1),
        )

    def get_present_ids(self) -> set:
        return set(self._present)

    def get_absent_ids(self) -> set:
        return self._expected_roster - self._present

    def reset(self):
        self._expected_roster = set()
        self._present = set()
        self._session_start = None
        logger.info("Occupancy tracker session reset.")


# Singleton instance - import this everywhere instead of instantiating directly
occupancy_tracker = OccupancyTracker()
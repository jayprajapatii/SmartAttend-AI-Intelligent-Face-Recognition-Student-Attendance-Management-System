"""
ui/pages/face_recognition_page.py

Live Face Recognition attendance-marking screen. This is the core
operational page of the app: point the camera at students, and
attendance gets marked automatically once a face is confidently
matched against the stored dataset.

Uses the `face_recognition` library directly for encoding + matching
(dlib-based). Once core/face_recognition/recognizer.py exists, move
`_load_known_faces()` and `_match_face()` there and import instead -
this page's structure won't need to change.

Pipeline per detected face, each frame:
    1. Detect face locations + compute a 128-d encoding
    2. Compare against all known student encodings (Euclidean distance)
    3. If best match distance <= RECOGNITION_THRESHOLD -> candidate match
    4. Reject if attendance already marked today for that student+subject
    5. Mark attendance, log recognition, speak a confirmation
    6. If no match found -> log as Unknown, save snapshot, raise a
       security alert (Unknown Person Alert feature)

NOTE: SubjectModel hasn't been built yet, so the subject dropdown
queries the `subjects` table directly via db.fetch_all() - swap for
SubjectModel.get_all() once that model exists (same pattern used in
faculty_management_page.py).
"""

import logging
import threading
import time
from datetime import date, datetime
from pathlib import Path
from queue import Queue, Empty

import cv2
import numpy as np
from PIL import Image
import customtkinter as ctk

import config
from database.db_connector import db
from database.models.face_embedding_model import FaceEmbeddingModel
from database.models.attendance_model import AttendanceModel
from database.models.recognition_log_model import RecognitionLogModel
from database.models.security_log_model import SecurityLogModel
from database.models.student_model import StudentModel
from auth.session_manager import session_manager
from utils.asset_manager import assets

logger = logging.getLogger("SmartAttendAI.ui.pages.face_recognition")

try:
    import face_recognition
    FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    FACE_RECOGNITION_AVAILABLE = False
    logger.warning("face_recognition library not installed - recognition page will run in preview-only mode.")

RECOGNITION_INTERVAL_SEC = 0.6   # how often to run the (expensive) recognition pass
UNKNOWN_ALERT_COOLDOWN_SEC = 15  # avoid spamming security_logs for the same unknown face


class FaceRecognitionPage(ctk.CTkFrame):

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)

        self._camera = None
        self._camera_thread = None
        self._running = False
        self._frame_queue = Queue(maxsize=2)

        self._known_encodings = []   # list[np.ndarray]
        self._known_student_ids = [] # parallel list[int]
        self._student_cache = {}     # student_id -> student dict

        self._marked_this_session = set()   # student_ids already confirmed this session (UI feedback)
        self._last_unknown_alert_time = 0
        self._last_recognition_pass = 0

        self._selected_subject_id = None
        self._selected_classroom = ""

        ctk.CTkLabel(
            self, text="Face Recognition Attendance", font=ctk.CTkFont(size=22, weight="bold")
        ).pack(anchor="w", pady=(0, 16))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=0)
        body.grid_rowconfigure(0, weight=1)

        self._build_camera_panel(body)
        self._build_side_panel(body)

        self._load_subjects()
        self.bind("<Destroy>", self._on_destroy)

        if not FACE_RECOGNITION_AVAILABLE:
            self.status_label.configure(
                text="'face_recognition' package not installed - camera preview only, no matching."
            )

    # ------------------------------------------------------------
    # Left: camera preview
    # ------------------------------------------------------------
    def _build_camera_panel(self, parent):
        panel = ctk.CTkFrame(parent, corner_radius=14)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 16))

        self.video_label = ctk.CTkLabel(
            panel, text="Camera preview will appear here.", width=640, height=480,
            fg_color=("#E2E8F0", "#0F172A"),
        )
        self.video_label.pack(padx=16, pady=16, fill="both", expand=True)

        self.status_label = ctk.CTkLabel(
            panel, text="Camera not started.", font=ctk.CTkFont(size=12), text_color=("#64748B", "#94A3B8")
        )
        self.status_label.pack(anchor="w", padx=16, pady=(0, 16))

    # ------------------------------------------------------------
    # Right: session settings + live recognized feed + unknown alerts
    # ------------------------------------------------------------
    def _build_side_panel(self, parent):
        panel = ctk.CTkFrame(parent, width=320, corner_radius=14)
        panel.grid(row=0, column=1, sticky="ns")
        panel.grid_propagate(False)

        ctk.CTkLabel(
            panel, text="Session Setup", font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=16, pady=(16, 6))

        ctk.CTkLabel(panel, text="Subject", font=ctk.CTkFont(size=11), text_color=("#64748B", "#94A3B8")).pack(
            anchor="w", padx=16
        )
        self.subject_var = ctk.StringVar(value="")
        self.subject_menu = ctk.CTkOptionMenu(
            panel, values=["Loading..."], variable=self.subject_var, width=280,
            command=self._on_subject_change,
        )
        self.subject_menu.pack(padx=16, pady=(2, 10))

        ctk.CTkLabel(panel, text="Classroom", font=ctk.CTkFont(size=11), text_color=("#64748B", "#94A3B8")).pack(
            anchor="w", padx=16
        )
        self.classroom_entry = ctk.CTkEntry(panel, width=280, placeholder_text="e.g. Room 204")
        self.classroom_entry.pack(padx=16, pady=(2, 16))

        self.start_button = ctk.CTkButton(panel, text="Start Recognition", width=280, command=self._handle_start)
        self.start_button.pack(padx=16, pady=(0, 6))

        self.stop_button = ctk.CTkButton(
            panel, text="Stop", width=280, fg_color="transparent", border_width=1,
            state="disabled", command=self._handle_stop,
        )
        self.stop_button.pack(padx=16)

        ctk.CTkLabel(
            panel, text="Recognized This Session", font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=16, pady=(24, 6))

        self.recognized_frame = ctk.CTkScrollableFrame(panel, width=290, height=180, fg_color="transparent")
        self.recognized_frame.pack(padx=16, fill="x")

        ctk.CTkLabel(
            panel, text="Unknown Face Alerts", font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=16, pady=(20, 6))

        self.unknown_frame = ctk.CTkScrollableFrame(panel, width=290, height=120, fg_color="transparent")
        self.unknown_frame.pack(padx=16, fill="x", pady=(0, 16))

    # ------------------------------------------------------------
    # Subjects lookup (inline until SubjectModel exists)
    # ------------------------------------------------------------
    def _load_subjects(self):
        try:
            subjects = db.fetch_all("SELECT subject_id, subject_name FROM subjects ORDER BY subject_name ASC")
        except Exception as exc:
            logger.error("Failed to load subjects: %s", exc)
            subjects = []

        self._subject_lookup = {s["subject_name"]: s["subject_id"] for s in subjects}
        names = ["No subject (general attendance)"] + list(self._subject_lookup.keys())
        self.subject_menu.configure(values=names)
        self.subject_var.set(names[0])

    def _on_subject_change(self, name: str):
        self._selected_subject_id = self._subject_lookup.get(name)  # None for "No subject"

    # ------------------------------------------------------------
    # Known face encodings (loaded fresh each session start)
    # ------------------------------------------------------------
    def _load_known_faces(self):
        self._known_encodings = []
        self._known_student_ids = []
        self._student_cache = {}

        try:
            embeddings = FaceEmbeddingModel.get_all_for_matching()
        except Exception as exc:
            logger.error("Failed to load face embeddings: %s", exc)
            embeddings = []

        for row in embeddings:
            try:
                vector = FaceEmbeddingModel.deserialize_vector(row["embedding_vector"])
                self._known_encodings.append(np.array(vector, dtype=np.float64))
                self._known_student_ids.append(row["student_id"])
            except (ValueError, TypeError, KeyError):
                continue

        logger.info(
            "Loaded %d face encodings across %d unique students.",
            len(self._known_encodings), len(set(self._known_student_ids)),
        )

    def _get_student(self, student_id: int) -> dict:
        if student_id not in self._student_cache:
            self._student_cache[student_id] = StudentModel.get_by_id(student_id) or {}
        return self._student_cache[student_id]

    # ------------------------------------------------------------
    # Start / stop session
    # ------------------------------------------------------------
    def _handle_start(self):
        self._selected_classroom = self.classroom_entry.get().strip()
        self._load_known_faces()

        if not self._known_encodings and FACE_RECOGNITION_AVAILABLE:
            self.status_label.configure(
                text="No face data found. Generate a dataset first via Dataset Generator."
            )

        try:
            self._camera = cv2.VideoCapture(config.DEFAULT_CAMERA_INDEX)
            if not self._camera.isOpened():
                raise RuntimeError("Could not open camera. Check camera index / permissions.")
        except Exception as exc:
            logger.error("Failed to open camera: %s", exc)
            self.status_label.configure(text=f"Camera error: {exc}")
            return

        self._running = True
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status_label.configure(text="Recognition running...")

        self._camera_thread = threading.Thread(target=self._camera_loop, daemon=True)
        self._camera_thread.start()
        self.after(30, self._poll_frame_queue)

    def _handle_stop(self):
        self._running = False
        if self._camera:
            self._camera.release()
            self._camera = None
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.status_label.configure(text="Recognition stopped.")

    def _on_destroy(self, _event):
        self._running = False
        if self._camera:
            self._camera.release()

    # ------------------------------------------------------------
    # Background camera loop
    # ------------------------------------------------------------
    def _camera_loop(self):
        while self._running and self._camera is not None:
            ok, frame = self._camera.read()
            if not ok:
                time.sleep(0.05)
                continue

            frame = cv2.flip(frame, 1)
            display_frame = frame.copy()
            status_text = "Scanning..."

            now = time.time()
            run_recognition = (
                FACE_RECOGNITION_AVAILABLE
                and now - self._last_recognition_pass >= RECOGNITION_INTERVAL_SEC
            )

            if run_recognition:
                self._last_recognition_pass = now
                status_text = self._run_recognition_pass(frame, display_frame)

            try:
                self._frame_queue.get_nowait()
            except Empty:
                pass
            self._frame_queue.put((display_frame, status_text))

            time.sleep(0.03)

    def _run_recognition_pass(self, frame, display_frame) -> str:
        rgb_small = cv2.resize(frame, (0, 0), fx=0.5, fy=0.5)
        rgb_small = cv2.cvtColor(rgb_small, cv2.COLOR_BGR2RGB)

        face_locations = face_recognition.face_locations(rgb_small)
        if not face_locations:
            return "No face detected."

        face_encodings = face_recognition.face_encodings(rgb_small, face_locations)
        results = []

        for (top, right, bottom, left), encoding in zip(face_locations, face_encodings):
            # Scale coordinates back up (we ran detection on a half-size frame)
            top, right, bottom, left = top * 2, right * 2, bottom * 2, left * 2
            cv2.rectangle(display_frame, (left, top), (right, bottom), (59, 130, 246), 2)

            student_id, confidence, distance = self._match_face(encoding)

            if student_id is not None:
                label = self._get_student(student_id).get("full_name", "Unknown")
                cv2.putText(display_frame, label, (left, top - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (46, 204, 113), 2)
                self._handle_recognized(student_id, confidence)
                results.append(f"Recognized: {label} ({confidence:.0%})")
            else:
                cv2.putText(display_frame, "Unknown", (left, top - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (231, 76, 60), 2)
                self._handle_unknown(frame, left, top, right, bottom)
                results.append("Unknown face detected")

        return " | ".join(results) if results else "Scanning..."

    def _match_face(self, encoding):
        """Returns (student_id, confidence, distance) or (None, 0, None) if no match."""
        if not self._known_encodings:
            return None, 0.0, None

        distances = face_recognition.face_distance(self._known_encodings, encoding)
        best_idx = int(np.argmin(distances))
        best_distance = float(distances[best_idx])

        if best_distance <= config.RECOGNITION_THRESHOLD:
            confidence = max(0.0, 1.0 - best_distance)
            return self._known_student_ids[best_idx], confidence, best_distance

        return None, 0.0, best_distance

    # ------------------------------------------------------------
    # Recognized face -> mark attendance (runs on background thread;
    # DB calls are thread-safe via the connection pool, UI updates
    # are scheduled back onto the main thread via .after())
    # ------------------------------------------------------------
    def _handle_recognized(self, student_id: int, confidence: float):
        try:
            RecognitionLogModel.log(
                recognition_result="Recognized",
                student_id=student_id,
                confidence_score=confidence,
                liveness_check=False,  # TODO: wire real liveness detection (core/anti_spoofing)
                camera_id=str(config.DEFAULT_CAMERA_INDEX),
            )
        except Exception as exc:
            logger.error("Failed to write recognition log: %s", exc)

        current_user = session_manager.get_current_user()
        faculty_id = current_user["admin_id"] if current_user and current_user.get("role") == "faculty" else None

        try:
            result = AttendanceModel.mark_attendance(
                student_id=student_id,
                subject_id=self._selected_subject_id,
                faculty_id=faculty_id,
                classroom=self._selected_classroom or None,
                recognition_confidence=confidence,
                liveness_status=False,  # TODO: replace once liveness detection is implemented
                verification_method="Face",
            )
        except Exception as exc:
            logger.error("Failed to mark attendance: %s", exc)
            return

        if result["success"] and student_id not in self._marked_this_session:
            self._marked_this_session.add(student_id)
            student = self._get_student(student_id)
            self.after(0, lambda: self._add_recognized_row(student, confidence))
            self._speak_confirmation(student.get("full_name", "Student"))

    def _speak_confirmation(self, name: str):
        message = f"Welcome {name}. Your attendance has been recorded successfully."

        def _say():
            try:
                assets.speak(message)
            except Exception as exc:
                logger.warning("Voice confirmation failed: %s", exc)

        threading.Thread(target=_say, daemon=True).start()

    # ------------------------------------------------------------
    # Unknown face -> security alert (rate-limited per session)
    # ------------------------------------------------------------
    def _handle_unknown(self, frame, left, top, right, bottom):
        now = time.time()
        if now - self._last_unknown_alert_time < UNKNOWN_ALERT_COOLDOWN_SEC:
            return
        self._last_unknown_alert_time = now

        crop = frame[max(top, 0):bottom, max(left, 0):right]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        image_path = config.UNKNOWN_FACES_DIR / f"unknown_{timestamp}.jpg"

        try:
            if crop.size > 0:
                cv2.imwrite(str(image_path), crop)
        except Exception as exc:
            logger.error("Failed to save unknown face snapshot: %s", exc)
            image_path = None

        try:
            RecognitionLogModel.log(
                recognition_result="Unknown",
                captured_image_path=str(image_path) if image_path else None,
                camera_id=str(config.DEFAULT_CAMERA_INDEX),
            )
            SecurityLogModel.log(
                event_type="Unknown Face",
                description="Unrecognized face detected during live attendance session.",
                image_path=str(image_path) if image_path else None,
            )
        except Exception as exc:
            logger.error("Failed to log unknown face event: %s", exc)

        self.after(0, lambda: self._add_unknown_alert(timestamp))

    # ------------------------------------------------------------
    # UI feed updates (main thread)
    # ------------------------------------------------------------
    def _add_recognized_row(self, student: dict, confidence: float):
        row = ctk.CTkFrame(self.recognized_frame, fg_color="transparent")
        row.pack(fill="x", pady=2)
        ctk.CTkLabel(row, text="●", text_color="#2ecc71").pack(side="left", padx=(0, 6))
        ctk.CTkLabel(
            row, text=f"{student.get('full_name', 'Unknown')} - {confidence:.0%}",
            font=ctk.CTkFont(size=12), anchor="w",
        ).pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(
            row, text=datetime.now().strftime("%H:%M:%S"),
            font=ctk.CTkFont(size=10), text_color=("#64748B", "#94A3B8"),
        ).pack(side="right")

    def _add_unknown_alert(self, timestamp: str):
        row = ctk.CTkFrame(self.unknown_frame, fg_color="transparent")
        row.pack(fill="x", pady=2)
        ctk.CTkLabel(row, text="⚠", text_color="#e74c3c").pack(side="left", padx=(0, 6))
        ctk.CTkLabel(
            row, text=f"Unknown face at {timestamp[-6:]}", font=ctk.CTkFont(size=12), anchor="w",
        ).pack(side="left", fill="x", expand=True)

    # ------------------------------------------------------------
    # Frame polling (main thread)
    # ------------------------------------------------------------
    def _poll_frame_queue(self):
        if not self._running:
            return
        try:
            frame, status_text = self._frame_queue.get_nowait()
            self._render_frame(frame)
            self.status_label.configure(text=status_text)
        except Empty:
            pass
        if self._running:
            self.after(30, self._poll_frame_queue)

    def _render_frame(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb)
        ctk_img = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(640, 480))
        self.video_label.configure(image=ctk_img, text="")
        self.video_label.image = ctk_img
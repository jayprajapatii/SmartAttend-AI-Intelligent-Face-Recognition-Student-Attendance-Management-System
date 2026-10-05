"""
ui/pages/dataset_generator_page.py

Responsive Face Dataset Generator page for SmartAttend AI.

Fixes:
- Fits the page into the available application area instead of forcing a
  640x480 layout that can be clipped on smaller windows.
- Uses a scrollable right-side control panel when vertical space is limited.
- Resizes the live camera preview to the actual available area.
- Adds a selected-student photo card and a latest-capture photo card.
- Keeps the existing webcam, face detection, blur rejection, duplicate
  rejection, and dataset-saving logic.
"""

import logging
import threading
import time
from pathlib import Path
from queue import Queue, Empty

import cv2
import numpy as np
from PIL import Image, ImageOps
import customtkinter as ctk
from tkinter import messagebox

import config
from database.models.student_model import StudentModel
from core.face_recognition.embedding_generator import generate_embeddings_for_student
from core.face_detection.face_quality import quality_checker


logger = logging.getLogger("SmartAttendAI.ui.pages.dataset_generator")

BLUR_THRESHOLD_DEFAULT = 25.0
DUPLICATE_SIMILARITY_THRESHOLD = 5.0
CAPTURE_INTERVAL_SECONDS = 0.50


class DatasetGeneratorPage(ctk.CTkFrame):

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)

        self._camera = None
        self._camera_thread = None
        self._capture_running = False
        self._frame_queue = Queue(maxsize=2)

        self._selected_student = None
        self._output_dir = None
        self._captured_count = 0
        self._rejected_blur = 0
        self._rejected_duplicate = 0
        self._last_capture_time = 0
        self._last_saved_gray = None
        self._target_count = 150

        self._last_camera_frame = None
        self._last_render_size = (0, 0)
        self._student_photo_image = None
        self._latest_capture_image = None

        self._face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )

        self._build_page()

        self.bind("<Destroy>", self._on_destroy)
        self.bind("<Configure>", self._on_page_resize)

    # ------------------------------------------------------------
    # Main responsive layout
    # ------------------------------------------------------------
    def _build_page(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Face Dataset Generator",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            header,
            text="Capture high-quality face images for recognition training",
            font=ctk.CTkFont(size=11),
            text_color=("#64748B", "#94A3B8"),
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1, minsize=420)
        body.grid_columnconfigure(1, weight=0, minsize=320)
        body.grid_rowconfigure(0, weight=1)

        self._build_camera_panel(body)
        self._build_controls_panel(body)

    # ------------------------------------------------------------
    # Left: camera and image preview
    # ------------------------------------------------------------
    def _build_camera_panel(self, parent):
        panel = ctk.CTkFrame(parent, corner_radius=14)
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        panel.grid_rowconfigure(1, weight=1)
        panel.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(panel, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 6))
        top.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            top,
            text="Live Camera",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).grid(row=0, column=0, sticky="w")

        self.camera_state_label = ctk.CTkLabel(
            top,
            text="READY",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="#22c55e",
        )
        self.camera_state_label.grid(row=0, column=1, sticky="e")

        self.video_label = ctk.CTkLabel(
            panel,
            text="Camera preview will appear here.\n\nSelect a student and click Start Camera.",
            font=ctk.CTkFont(size=13),
            fg_color=("#E2E8F0", "#0F172A"),
            corner_radius=10,
        )
        self.video_label.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=14,
            pady=(0, 8),
        )

        bottom = ctk.CTkFrame(panel, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 12))
        bottom.grid_columnconfigure(0, weight=1)

        self.face_status_label = ctk.CTkLabel(
            bottom,
            text="Camera is ready.",
            font=ctk.CTkFont(size=12),
            text_color=("#64748B", "#94A3B8"),
            anchor="w",
        )
        self.face_status_label.grid(row=0, column=0, sticky="ew")

        self.capture_hint_label = ctk.CTkLabel(
            bottom,
            text="Face the camera and keep your face inside the detection box.",
            font=ctk.CTkFont(size=10),
            text_color=("#64748B", "#94A3B8"),
            anchor="w",
        )
        self.capture_hint_label.grid(row=1, column=0, sticky="ew", pady=(3, 0))

    # ------------------------------------------------------------
    # Right: scrollable controls
    # ------------------------------------------------------------
    def _build_controls_panel(self, parent):
        panel = ctk.CTkScrollableFrame(
            parent,
            width=320,
            corner_radius=14,
            scrollbar_button_color=("#a3a3a3", "#4b4b4b"),
            scrollbar_button_hover_color=("#737373", "#666666"),
        )
        panel.grid(row=0, column=1, sticky="nsew")
        self.controls_panel = panel

        # Student selection
        self._section_title(panel, "1. Select Student")

        self.student_search_entry = ctk.CTkEntry(
            panel,
            placeholder_text="Search name, roll no., enrollment...",
            height=36,
        )
        self.student_search_entry.pack(fill="x", padx=2, pady=(0, 6))
        self.student_search_entry.bind("<KeyRelease>", self._on_student_search)

        self.student_results_frame = ctk.CTkScrollableFrame(
            panel,
            height=100,
            fg_color="transparent",
            border_width=1,
            border_color=("#d4d4d4", "#3f3f3f"),
        )
        self.student_results_frame.pack(fill="x", padx=2, pady=(0, 6))

        self.selected_student_label = ctk.CTkLabel(
            panel,
            text="No student selected",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#3b82f6",
            wraplength=285,
            justify="left",
            anchor="w",
        )
        self.selected_student_label.pack(fill="x", padx=2, pady=(2, 8))

        # Student photo
        photo_card = ctk.CTkFrame(panel, corner_radius=10)
        photo_card.pack(fill="x", padx=2, pady=(0, 12))

        ctk.CTkLabel(
            photo_card,
            text="Student Photo",
            font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(anchor="w", padx=10, pady=(8, 4))

        self.student_photo_label = ctk.CTkLabel(
            photo_card,
            text="No photo available",
            width=110,
            height=110,
            fg_color=("#F1F5F9", "#1E293B"),
            corner_radius=8,
        )
        self.student_photo_label.pack(padx=10, pady=(0, 8))

        # Capture settings
        self._section_title(panel, "2. Capture Settings")

        self.target_count_var = ctk.IntVar(value=150)

        self.target_count_label = ctk.CTkLabel(
            panel,
            text="Target images: 150",
            font=ctk.CTkFont(size=12),
        )
        self.target_count_label.pack(anchor="w", padx=2)

        self.target_slider = ctk.CTkSlider(
            panel,
            from_=100,
            to=300,
            number_of_steps=20,
            variable=self.target_count_var,
            command=self._on_target_change,
            height=18,
        )
        self.target_slider.pack(fill="x", padx=2, pady=(3, 14))

        # Capture controls
        self._section_title(panel, "3. Capture")

        self.start_button = ctk.CTkButton(
            panel,
            text="Start Camera",
            height=38,
            command=self._handle_start,
        )
        self.start_button.pack(fill="x", padx=2, pady=(0, 6))

        self.stop_button = ctk.CTkButton(
            panel,
            text="Stop Capture",
            height=36,
            fg_color="transparent",
            border_width=1,
            state="disabled",
            command=self._handle_stop,
        )
        self.stop_button.pack(fill="x", padx=2)

        # Progress
        self._section_title(panel, "4. Progress")

        self.progress_bar = ctk.CTkProgressBar(panel, height=10)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", padx=2, pady=(0, 6))

        self.progress_label = ctk.CTkLabel(
            panel,
            text="0 / 150 captured",
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.progress_label.pack(anchor="w", padx=2)

        # Statistics
        stats_frame = ctk.CTkFrame(panel, corner_radius=10)
        stats_frame.pack(fill="x", padx=2, pady=(10, 12))

        self.blur_rejected_label = ctk.CTkLabel(
            stats_frame,
            text="Blurry rejected: 0",
            font=ctk.CTkFont(size=11),
            text_color=("#64748B", "#94A3B8"),
        )
        self.blur_rejected_label.pack(anchor="w", padx=10, pady=(8, 2))

        self.dup_rejected_label = ctk.CTkLabel(
            stats_frame,
            text="Duplicates rejected: 0",
            font=ctk.CTkFont(size=11),
            text_color=("#64748B", "#94A3B8"),
        )
        self.dup_rejected_label.pack(anchor="w", padx=10, pady=(0, 8))

        # Latest captured photo
        latest_card = ctk.CTkFrame(panel, corner_radius=10)
        latest_card.pack(fill="x", padx=2, pady=(0, 14))

        ctk.CTkLabel(
            latest_card,
            text="Latest Captured Photo",
            font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(anchor="w", padx=10, pady=(8, 4))

        self.latest_capture_label = ctk.CTkLabel(
            latest_card,
            text="No image captured yet",
            width=110,
            height=110,
            fg_color=("#F1F5F9", "#1E293B"),
            corner_radius=8,
        )
        self.latest_capture_label.pack(padx=10, pady=(0, 8))

    def _section_title(self, parent, text):
        ctk.CTkLabel(
            parent,
            text=text,
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=2, pady=(6, 6))

    # ------------------------------------------------------------
    # Responsive resizing
    # ------------------------------------------------------------
    def _on_page_resize(self, _event=None):
        if self._last_camera_frame is not None:
            self.after_idle(
                lambda: self._render_frame(self._last_camera_frame, force=True)
            )

    # ------------------------------------------------------------
    # Student search
    # ------------------------------------------------------------
    def _on_student_search(self, _event):
        keyword = self.student_search_entry.get().strip()

        for widget in self.student_results_frame.winfo_children():
            widget.destroy()

        if not keyword:
            return

        try:
            results = StudentModel.search(keyword)[:6]
        except Exception as exc:
            logger.error("Student search failed: %s", exc)
            results = []

        if not results:
            ctk.CTkLabel(
                self.student_results_frame,
                text="No students found.",
                text_color=("#64748B", "#94A3B8"),
            ).pack(anchor="w", padx=5, pady=5)
            return

        for student in results:
            label_text = (
                f"{student['full_name']} "
                f"({student.get('roll_number') or student['enrollment_number']})"
            )
            ctk.CTkButton(
                self.student_results_frame,
                text=label_text,
                anchor="w",
                height=32,
                fg_color="transparent",
                command=lambda s=student: self._select_student(s),
            ).pack(fill="x", pady=1)

    def _select_student(self, student: dict):
        self._selected_student = student

        self.selected_student_label.configure(
            text=(
                f"Selected: {student['full_name']}\n"
                f"Enrollment: {student['enrollment_number']}"
            )
        )

        for widget in self.student_results_frame.winfo_children():
            widget.destroy()

        self.student_search_entry.delete(0, "end")
        self._load_student_photo(student)

    # ------------------------------------------------------------
    # Student / capture photo helpers
    # ------------------------------------------------------------
    def _find_student_photo(self, student):
        possible_keys = (
            "photo_path",
            "profile_photo",
            "profile_image",
            "image_path",
            "photo",
            "image",
        )

        for key in possible_keys:
            value = student.get(key)
            if value:
                candidate = Path(str(value))
                if candidate.exists() and candidate.is_file():
                    return candidate

        enrollment = student.get("enrollment_number")
        if enrollment:
            directory = Path(config.STUDENT_PHOTOS_DIR) / str(enrollment)
            if directory.exists():
                images = sorted(
                    p for p in directory.iterdir()
                    if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
                )
                if images:
                    return images[0]

        return None

    def _load_student_photo(self, student):
        path = self._find_student_photo(student)

        if not path:
            self.student_photo_label.configure(
                image=None,
                text="No photo available",
            )
            self._student_photo_image = None
            return

        try:
            image = Image.open(path).convert("RGB")
            image = ImageOps.contain(image, (110, 110))
            ctk_img = ctk.CTkImage(
                light_image=image,
                dark_image=image,
                size=(110, 110),
            )
            self.student_photo_label.configure(image=ctk_img, text="")
            self.student_photo_label.image = ctk_img
            self._student_photo_image = ctk_img
        except Exception as exc:
            logger.warning("Could not load student photo %s: %s", path, exc)
            self.student_photo_label.configure(
                image=None,
                text="Photo unavailable",
            )
            self._student_photo_image = None

    def _show_latest_capture(self, path):
        try:
            image = Image.open(path).convert("RGB")
            image = ImageOps.contain(image, (110, 110))
            ctk_img = ctk.CTkImage(
                light_image=image,
                dark_image=image,
                size=(110, 110),
            )
            self.latest_capture_label.configure(image=ctk_img, text="")
            self.latest_capture_label.image = ctk_img
            self._latest_capture_image = ctk_img
        except Exception as exc:
            logger.warning("Could not load latest capture preview: %s", exc)

    # ------------------------------------------------------------
    # Target count
    # ------------------------------------------------------------
    def _on_target_change(self, value):
        target = int(float(value))
        self._target_count = target
        self.target_count_label.configure(text=f"Target images: {target}")
        self.progress_label.configure(
            text=f"{self._captured_count} / {target} captured"
        )

    # ------------------------------------------------------------
    # Start / stop capture session
    # ------------------------------------------------------------
    def _handle_start(self):
        if not self._selected_student:
            messagebox.showwarning(
                "No Student Selected",
                "Please search and select a student first.",
            )
            return

        enrollment = self._selected_student["enrollment_number"]
        self._output_dir = Path(config.STUDENT_PHOTOS_DIR) / str(enrollment)
        self._output_dir.mkdir(parents=True, exist_ok=True)

        self._target_count = int(self.target_count_var.get())
        self._captured_count = 0
        self._rejected_blur = 0
        self._rejected_duplicate = 0
        self._last_saved_gray = None
        self._last_capture_time = 0
        self._update_progress_ui()

        try:
            self._camera = cv2.VideoCapture(config.DEFAULT_CAMERA_INDEX)

            # Request a sensible webcam resolution. The preview itself is
            # still resized to whatever space is available in the UI.
            self._camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            self._camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

            if not self._camera.isOpened():
                raise RuntimeError(
                    "Could not open camera. Check camera index / permissions."
                )
        except Exception as exc:
            logger.error("Failed to open camera: %s", exc)
            if self._camera:
                self._camera.release()
                self._camera = None
            messagebox.showerror("Camera Error", str(exc))
            return

        self._capture_running = True
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.student_search_entry.configure(state="disabled")
        self.camera_state_label.configure(
            text="LIVE",
            text_color="#22c55e",
        )
        self.face_status_label.configure(text="Starting camera...")

        self._camera_thread = threading.Thread(
            target=self._camera_loop,
            daemon=True,
        )
        self._camera_thread.start()

        self.after(30, self._poll_frame_queue)
        logger.info("Dataset capture started for %s", enrollment)

    def _handle_stop(self, show_message=True):
        was_running = self._capture_running
        self._capture_running = False

        if self._camera:
            self._camera.release()
            self._camera = None

        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.student_search_entry.configure(state="normal")
        self.camera_state_label.configure(
            text="READY",
            text_color="#22c55e",
        )

        logger.info(
            "Dataset capture stopped. Captured=%s Blur-rejected=%s Duplicate-rejected=%s",
            self._captured_count,
            self._rejected_blur,
            self._rejected_duplicate,
        )

        if show_message and was_running and self._captured_count > 0:
            messagebox.showinfo(
                "Capture Session Ended",
                f"Captured {self._captured_count} images for "
                f"{self._selected_student['full_name']}.\n"
                f"Rejected (blurry): {self._rejected_blur}\n"
                f"Rejected (duplicate): {self._rejected_duplicate}",
            )

    def _on_destroy(self, _event):
        self._capture_running = False
        if self._camera:
            self._camera.release()
            self._camera = None

    # ------------------------------------------------------------
    # Background camera loop
    # ------------------------------------------------------------
    def _camera_loop(self):

        target = int(self._target_count)

        logger.info(
            "Camera loop started. Target=%d",
            target,
        )

        while (
            self._capture_running
            and self._captured_count < target
        ):

        # -----------------------------------------------------
        # Read camera frame
        # -----------------------------------------------------
            if self._camera is None:
                break

            ok, frame = self._camera.read()

            if not ok:
                logger.warning("Camera frame read failed.")
                time.sleep(0.05)
                continue

            # Mirror camera preview
            frame = cv2.flip(frame, 1)

        # -----------------------------------------------------
        # Detect faces
        # -----------------------------------------------------
            faces = self._detect_faces(frame)

            display_frame = frame.copy()

        # -----------------------------------------------------
        # Draw face rectangles
        # -----------------------------------------------------
            for (x, y, w, h) in faces:

                cv2.rectangle(
                    display_frame,
                    (x, y),
                    (x + w, y + h),
                    (59, 130, 246),
                    2,
                )

                cv2.putText(
                    display_frame,
                    "Face detected",
                    (x, max(25, y - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (59, 130, 246),
                    2,
                )

            saved_this_frame = False

        # -----------------------------------------------------
        # Auto capture
        # -----------------------------------------------------
            current_time = time.time()

            if (
                faces
                and
                (current_time - self._last_capture_time)
                >= CAPTURE_INTERVAL_SECONDS
            ):

            # Select largest detected face
                x, y, w, h = max(
                    faces,
                    key=lambda f: f[2] * f[3],
                )

            # -------------------------------------------------
            # Add a small padding around face
            # -------------------------------------------------
                padding = int(min(w, h) * 0.15)

                x1 = max(0, x - padding)
                y1 = max(0, y - padding)

                x2 = min(
                    frame.shape[1],
                    x + w + padding,
                )

                y2 = min(
                    frame.shape[0],
                    y + h + padding,
                )

                face_crop = frame[y1:y2, x1:x2]

                saved_this_frame = self._process_and_save(
                    face_crop
                )

            # IMPORTANT:
            # Only update capture timer when an image was
                # actually accepted.
                if saved_this_frame:
                    self._last_capture_time = current_time

        # -----------------------------------------------------
        # Status
            # -----------------------------------------------------
            if faces:

                status_text = (
                    f"Face detected | "
                    f"Captured: {self._captured_count}/{target} | "
                    f"Blur rejected: {self._rejected_blur} | "
                    f"Duplicate rejected: {self._rejected_duplicate}"
                )

            else:

                status_text = (
                    f"No face detected | "
                    f"Captured: {self._captured_count}/{target}"
                )

        # -----------------------------------------------------
        # Send frame to UI queue
        # -----------------------------------------------------
            try:
                self._frame_queue.get_nowait()
            except Empty:
                pass

            try:
                self._frame_queue.put_nowait(
                    (
                        display_frame,
                        status_text,
                        saved_this_frame,
                    )
                )
            except Exception:
                pass

    # ---------------------------------------------------------
    # Capture completed
    # ---------------------------------------------------------
        if (
            self._capture_running
            and self._captured_count >= target
        ):

            logger.info(
                "Target reached. Captured=%d",
                self._captured_count,
            )

            self.after(
                0,
                self._handle_capture_complete,
            )

    def _detect_faces(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        faces = self._face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(120, 120),
        )

        # OpenCV returns a NumPy array.
        # Convert it to a normal Python list so `if faces:` is safe.
        if faces is None:
            return []

        return [tuple(map(int, face)) for face in faces]

    # ------------------------------------------------------------
    # Capture validation and saving
    # ------------------------------------------------------------
    def _process_and_save(self, face_crop) -> bool:
        """
        Validate the detected face and save it as a dataset image.

        Returns:
            True  -> image saved
            False -> image rejected
        """
        if face_crop is None or face_crop.size == 0:
            return False

        # ---------------------------------------------------------
        # Convert face crop to grayscale
        # ---------------------------------------------------------
        gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)

            # Normalize size for quality comparison
        gray_resized = cv2.resize(
                gray,
                (200, 200),
                interpolation=cv2.INTER_AREA,
            )

        # ---------------------------------------------------------
        # Blur / sharpness check
        # ---------------------------------------------------------
        blur_score = float(
                cv2.Laplacian(
                    gray_resized,
                    cv2.CV_64F,
                ).var()
            )

    # Log occasionally so we can see the actual camera score.
        if self._captured_count < 3:
            logger.info(
                "Face quality check: blur_score=%.2f threshold=%.2f",
                blur_score,
                BLUR_THRESHOLD_DEFAULT,
            )

        if blur_score < BLUR_THRESHOLD_DEFAULT:
            self._rejected_blur += 1

            # Show useful status in UI
            self.after(
                0,
                lambda score=blur_score: self.face_status_label.configure(
                    text=f"Face detected, but image is blurry ({score:.1f}). "
                        f"Keep your face steady."
                ),
            )

            return False

    # ---------------------------------------------------------
    # Duplicate check
    # ---------------------------------------------------------
        if self._last_saved_gray is not None:

            diff = cv2.absdiff(
                gray_resized,
                self._last_saved_gray,
            )

            difference_score = float(np.mean(diff))

            if difference_score < DUPLICATE_SIMILARITY_THRESHOLD:
                self._rejected_duplicate += 1
                return False

    # ---------------------------------------------------------
    # Save this image
    # ---------------------------------------------------------
        self._last_saved_gray = gray_resized.copy()

        self._save_capture(
            face_crop,
            blur_score=blur_score,
        )

        return True
        
    def _save_capture(self, face_crop, blur_score=0.0):
        """
        Save one accepted face image.
        """

        if face_crop is None or face_crop.size == 0:
            return

        next_count = self._captured_count + 1

        filename = (
            self._output_dir
            / f"img_{next_count:03d}.jpg"
        )

        success = cv2.imwrite(
            str(filename),
            face_crop,
            [cv2.IMWRITE_JPEG_QUALITY, 95],
        )

        if not success:
            logger.error(
                "Failed to save face image: %s",
                filename,
            )
            return

        self._captured_count = next_count

        logger.info(
            "Face image saved: %s | blur_score=%.2f | captured=%d",
            filename,
            blur_score,
            self._captured_count,
        )

    # ---------------------------------------------------------
    # Update latest image preview on the main UI thread
    # ---------------------------------------------------------
        self.after(
            0,
            lambda p=filename: self._show_latest_capture(p),
        )

    # ---------------------------------------------------------
    # Update progress immediately
        # ---------------------------------------------------------
        self.after(
            0,
            self._update_progress_ui,
        )

        # TODO once core/face_recognition/embedding_generator.py exists:
        #     embedding = embedding_generator.generate(face_crop)
        #     FaceEmbeddingModel.create(
        #         student_id=self._selected_student["student_id"],
        #         embedding_vector=embedding,
        #         image_path=str(filename),
        #         quality_score=blur_score,
        #     )

    # ------------------------------------------------------------
    # UI polling
    # ------------------------------------------------------------
    def _poll_frame_queue(self):
        if not self._capture_running:
            return

        try:
            frame, status_text, saved = self._frame_queue.get_nowait()
            self._render_frame(frame)
            self.face_status_label.configure(text=status_text)

            if saved:
                self._update_progress_ui()
        except Empty:
            pass

        if self._capture_running:
            self.after(30, self._poll_frame_queue)

    def _render_frame(self, frame, force=False):
        if frame is None:
            return

        self._last_camera_frame = frame

        available_w = self.video_label.winfo_width()
        available_h = self.video_label.winfo_height()

        if available_w <= 20 or available_h <= 20:
            return

        # Keep the camera aspect ratio while fitting the actual UI space.
        frame_h, frame_w = frame.shape[:2]
        scale = min(
            available_w / frame_w,
            available_h / frame_h,
        )

        new_w = max(1, int(frame_w * scale))
        new_h = max(1, int(frame_h * scale))

        render_size = (new_w, new_h)

        if not force and render_size == self._last_render_size:
            # Same size, but the image itself still needs updating.
            pass

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(rgb).resize(
            render_size,
            Image.Resampling.LANCZOS,
        )

        ctk_img = ctk.CTkImage(
            light_image=pil_img,
            dark_image=pil_img,
            size=render_size,
        )

        self.video_label.configure(
            image=ctk_img,
            text="",
        )
        self.video_label.image = ctk_img
        self._last_render_size = render_size

    # ------------------------------------------------------------
    # Progress
    # ------------------------------------------------------------
    def _update_progress_ui(self):
        target = max(1, int(self._target_count))

        self.progress_bar.set(
            min(self._captured_count / target, 1.0)
        )
        self.progress_label.configure(
            text=f"{self._captured_count} / {target} captured"
        )
        self.blur_rejected_label.configure(
            text=f"Blurry rejected: {self._rejected_blur}"
        )
        self.dup_rejected_label.configure(
            text=f"Duplicates rejected: {self._rejected_duplicate}"
        )
        
        
    def _select_best_photo(self, image_dir: Path) -> str | None:
        """Pick the sharpest captured frame."""

        best_path = None
        best_score = -1.0

        if not image_dir or not image_dir.exists():
            return None

        for img_path in image_dir.glob("img_*.jpg"):
            try:
                img = cv2.imread(str(img_path))

                if img is None:
                    continue

                score = quality_checker.blur_score(img)

                if score > best_score:
                    best_score = score
                    best_path = img_path

            except Exception as exc:
                logger.warning(
                    "Could not evaluate image %s: %s",
                    img_path,
                    exc,
                )

        if best_path:
            logger.info(
                "Best profile photo: %s | Score: %.2f",
                best_path,
                best_score,
            )

        return str(best_path) if best_path else None


    def _finish_dataset(self):

        if not self._selected_student:
            logger.warning("No student selected.")
            return

        student_id = self._selected_student.get("student_id")
        image_dir = self._output_dir

        best_photo = self._select_best_photo(image_dir)

        if best_photo and student_id:
            try:
                StudentModel.update(
                    student_id,
                    photo_path=best_photo,
                )

                logger.info(
                    "Profile photo updated for student_id=%s: %s",
                    student_id,
                    best_photo,
                )

                self._show_latest_capture(best_photo)

            except Exception as exc:
                logger.exception(
                    "Could not update profile photo: %s",
                    exc,
                )

        self.face_status_label.configure(
            text="Dataset capture complete. Best photo selected."
        )

        self.camera_state_label.configure(
            text="COMPLETE",
            text_color="#22c55e",
        )

        messagebox.showinfo(
            "Dataset Complete",
            f"Successfully captured {self._captured_count} images "
            f"for {self._selected_student['full_name']}.\n\n"
            f"Blurry rejected: {self._rejected_blur}\n"
            f"Duplicates rejected: {self._rejected_duplicate}\n\n"
            f"Best profile photo updated.",
        )


    def _handle_capture_complete(self):

        logger.info(
            "Dataset target reached: %s images",
            self._captured_count,
        )

        self._handle_stop(show_message=False)

        self._finish_dataset()

    
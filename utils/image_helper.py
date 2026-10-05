"""
utils/image_helper.py

Image conversion and manipulation utilities shared across pages that
move images between OpenCV (BGR numpy arrays), PIL (for CTkImage),
and disk - dataset generator, face recognition, student photo
uploads, report thumbnails.

Usage:
    from utils.image_helper import image_helper

    ctk_img = image_helper.bgr_to_ctk_image(frame_bgr, size=(640, 480))
    pil_img = image_helper.bgr_to_pil(frame_bgr)
    thumb = image_helper.make_thumbnail(image_path, max_size=(150, 150))
"""

import logging
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
import customtkinter as ctk

logger = logging.getLogger("SmartAttendAI.utils.image_helper")

DEFAULT_THUMBNAIL_SIZE = (150, 150)


class ImageHelper:
    """Stateless image conversion/manipulation helpers."""

    # ------------------------------------------------------------
    # OpenCV (BGR) <-> PIL <-> CTkImage conversions
    # ------------------------------------------------------------
    @staticmethod
    def bgr_to_pil(frame_bgr: np.ndarray) -> Image.Image:
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        return Image.fromarray(rgb)

    @staticmethod
    def pil_to_bgr(pil_image: Image.Image) -> np.ndarray:
        rgb = np.array(pil_image.convert("RGB"))
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    @staticmethod
    def bgr_to_ctk_image(frame_bgr: np.ndarray, size: tuple = None) -> ctk.CTkImage:
        """Converts an OpenCV BGR frame directly into a CTkImage ready for a CTkLabel."""
        pil_image = ImageHelper.bgr_to_pil(frame_bgr)
        display_size = size or pil_image.size
        return ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=display_size)

    @staticmethod
    def path_to_ctk_image(path, size: tuple = None) -> ctk.CTkImage | None:
        path = Path(path)
        if not path.exists():
            logger.warning("Image not found: %s", path)
            return None
        try:
            pil_image = Image.open(path).convert("RGBA")
            display_size = size or pil_image.size
            return ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=display_size)
        except Exception as exc:
            logger.error("Failed to load image %s: %s", path, exc)
            return None

    # ------------------------------------------------------------
    # Resizing / thumbnails
    # ------------------------------------------------------------
    @staticmethod
    def resize_keep_aspect(image: np.ndarray, max_width: int = None, max_height: int = None) -> np.ndarray:
        """Resizes an OpenCV image to fit within max_width/max_height while preserving aspect ratio."""
        h, w = image.shape[:2]
        if max_width is None and max_height is None:
            return image

        scale = min(
            (max_width / w) if max_width else float("inf"),
            (max_height / h) if max_height else float("inf"),
        )
        scale = min(scale, 1.0)  # never upscale
        new_size = (int(w * scale), int(h * scale))
        return cv2.resize(image, new_size, interpolation=cv2.INTER_AREA)

    @staticmethod
    def make_thumbnail(source_path, dest_path=None, max_size: tuple = DEFAULT_THUMBNAIL_SIZE):
        """
        Creates a thumbnail from an image file. If dest_path is given,
        saves it there and returns the path; otherwise returns the
        PIL.Image object directly without writing to disk.
        """
        source_path = Path(source_path)
        try:
            image = Image.open(source_path)
            image.thumbnail(max_size, Image.LANCZOS)
        except Exception as exc:
            logger.error("Failed to create thumbnail for %s: %s", source_path, exc)
            return None

        if dest_path:
            dest_path = Path(dest_path)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(dest_path)
            return str(dest_path)

        return image

    # ------------------------------------------------------------
    # Quick quality helpers (thin wrappers - full logic lives in
    # core/face_detection/face_quality.py; these are for generic,
    # non-face image needs, e.g. checking an uploaded student photo)
    # ------------------------------------------------------------
    @staticmethod
    def is_blurry(image_bgr: np.ndarray, threshold: float = 100.0) -> bool:
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY) if len(image_bgr.shape) == 3 else image_bgr
        return cv2.Laplacian(gray, cv2.CV_64F).var() < threshold

    @staticmethod
    def get_dimensions(path) -> tuple:
        """Returns (width, height) without loading the full image into memory where possible."""
        try:
            with Image.open(path) as img:
                return img.size
        except Exception as exc:
            logger.error("Failed to read dimensions for %s: %s", path, exc)
            return (0, 0)

    # ------------------------------------------------------------
    # Encoding for storage/transmission (e.g. saving a snapshot as bytes)
    # ------------------------------------------------------------
    @staticmethod
    def bgr_to_jpeg_bytes(frame_bgr: np.ndarray, quality: int = 90) -> bytes:
        success, buffer = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not success:
            raise RuntimeError("Failed to encode image to JPEG.")
        return buffer.tobytes()

    @staticmethod
    def jpeg_bytes_to_bgr(data: bytes) -> np.ndarray:
        array = np.frombuffer(data, dtype=np.uint8)
        return cv2.imdecode(array, cv2.IMREAD_COLOR)


# Singleton instance - import this everywhere instead of instantiating directly
image_helper = ImageHelper()
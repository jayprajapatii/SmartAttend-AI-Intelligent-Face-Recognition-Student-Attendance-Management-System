"""
utils/file_helper.py

General filesystem utilities: safe filename generation, human-
readable file sizes, directory cleanup, and simple import/export
helpers shared across pages that touch disk (dataset generator,
reports, backups, bulk student import).

Usage:
    from utils.file_helper import file_helper

    safe_name = file_helper.safe_filename("Jay Prajapati's Photo #1.jpg")
    file_helper.ensure_dir(some_path)
    size_str = file_helper.human_readable_size(file_path)
    file_helper.cleanup_old_files(config.UNKNOWN_FACES_DIR, days=30)
"""

import logging
import re
import shutil
import time
from pathlib import Path

logger = logging.getLogger("SmartAttendAI.utils.file_helper")

INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
MAX_FILENAME_LENGTH = 200


class FileHelper:
    """Stateless filesystem helper utilities."""

    # ------------------------------------------------------------
    # Filenames / paths
    # ------------------------------------------------------------
    @staticmethod
    def safe_filename(name: str, fallback: str = "file") -> str:
        """Strips characters that are invalid or risky in filenames across Windows/Linux/macOS."""
        if not name:
            return fallback

        cleaned = INVALID_FILENAME_CHARS.sub("_", name).strip()
        cleaned = re.sub(r"\s+", "_", cleaned)
        cleaned = cleaned.strip("._")

        if not cleaned:
            return fallback

        return cleaned[:MAX_FILENAME_LENGTH]

    @staticmethod
    def ensure_dir(path) -> Path:
        """Creates a directory (and parents) if it doesn't exist. Returns the Path."""
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def unique_path(path) -> Path:
        """
        If `path` already exists, appends a numeric suffix until an
        unused path is found (file.jpg -> file_1.jpg -> file_2.jpg ...).
        Useful when generating a filename from user input that might collide.
        """
        path = Path(path)
        if not path.exists():
            return path

        stem, suffix, parent = path.stem, path.suffix, path.parent
        counter = 1
        while True:
            candidate = parent / f"{stem}_{counter}{suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    # ------------------------------------------------------------
    # Size / info
    # ------------------------------------------------------------
    @staticmethod
    def human_readable_size(path_or_bytes) -> str:
        """Accepts either a file path or a raw byte count."""
        if isinstance(path_or_bytes, (int, float)):
            size_bytes = path_or_bytes
        else:
            path = Path(path_or_bytes)
            size_bytes = path.stat().st_size if path.exists() else 0

        for unit in ("B", "KB", "MB", "GB"):
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}" if unit != "B" else f"{int(size_bytes)} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"

    @staticmethod
    def dir_size_bytes(path) -> int:
        """Total size of all files under a directory, recursively."""
        path = Path(path)
        if not path.exists():
            return 0
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())

    @staticmethod
    def count_files(path, pattern: str = "*") -> int:
        path = Path(path)
        if not path.exists():
            return 0
        return sum(1 for _ in path.glob(pattern) if _.is_file())

    # ------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------
    @staticmethod
    def cleanup_old_files(directory, days: int, pattern: str = "*") -> int:
        """
        Deletes files older than `days` under `directory` (non-recursive
        by default via `pattern`). Returns count deleted. Useful for
        e.g. pruning old unknown-face snapshots or stale report exports.
        """
        directory = Path(directory)
        if not directory.exists():
            return 0

        cutoff = time.time() - (days * 86400)
        deleted = 0

        for file_path in directory.glob(pattern):
            if file_path.is_file() and file_path.stat().st_mtime < cutoff:
                try:
                    file_path.unlink()
                    deleted += 1
                except OSError as exc:
                    logger.warning("Could not delete %s: %s", file_path, exc)

        if deleted:
            logger.info("Cleaned up %d file(s) older than %d days in %s.", deleted, days, directory)
        return deleted

    @staticmethod
    def safe_delete(path) -> bool:
        """Deletes a file or directory tree, logging but not raising on failure."""
        path = Path(path)
        try:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
            return True
        except OSError as exc:
            logger.error("Failed to delete %s: %s", path, exc)
            return False

    @staticmethod
    def copy_file(source, destination) -> bool:
        source, destination = Path(source), Path(destination)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            return True
        except OSError as exc:
            logger.error("Failed to copy %s -> %s: %s", source, destination, exc)
            return False


# Singleton instance - import this everywhere instead of instantiating directly
file_helper = FileHelper()
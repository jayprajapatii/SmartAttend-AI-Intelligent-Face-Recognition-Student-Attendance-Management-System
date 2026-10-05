"""
utils/logger.py

Centralized logging configuration. main.py already sets up root
logging inline (file + console handlers) - this module exists so any
other entry point (tests, a background scheduler script, a CLI tool)
gets the exact same setup without duplicating the boilerplate, and so
individual modules get a consistently-named logger via get_logger()
instead of each hand-writing logging.getLogger("SmartAttendAI.some.path").

Usage:
    from utils.logger import get_logger

    logger = get_logger(__name__)
    logger.info("Something happened.")

    # One-time setup (call once at app startup, e.g. from main.py):
    from utils.logger import configure_logging
    configure_logging()
"""

import logging
import logging.handlers
import sys

import config

APP_LOGGER_PREFIX = "SmartAttendAI"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_LOG_FILE_BYTES = 5 * 1024 * 1024  # 5 MB per file
BACKUP_COUNT = 5                       # keep 5 rotated log files

_configured = False


def configure_logging(log_filename: str = "app.log", level: int = None):
    """
    Sets up the root logger with a rotating file handler and a
    console handler. Idempotent - safe to call multiple times (e.g.
    once from main.py, and again defensively from a script that
    imports app modules directly), only configures once.
    """
    global _configured
    if _configured:
        return

    log_level = level if level is not None else (logging.DEBUG if config.DEBUG else logging.INFO)
    log_path = config.LOGS_DIR / log_filename

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=MAX_LOG_FILE_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Quiet down noisy third-party libraries that log at INFO/DEBUG by default
    for noisy_logger in ("PIL", "matplotlib", "urllib3", "mysql.connector"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    _configured = True
    get_logger(__name__).info("Logging configured (level=%s, file=%s).", logging.getLevelName(log_level), log_path)


def get_logger(module_name: str) -> logging.Logger:
    """
    Returns a logger namespaced under the app prefix, e.g.
    get_logger("ui.pages.dashboard_page") -> "SmartAttendAI.ui.pages.dashboard_page"
    get_logger(__name__) works directly too - __name__ inside the
    package already looks like "ui.pages.dashboard_page" once run as
    part of the app, so this just ensures a consistent prefix even for
    modules that don't naturally have one (e.g. run as __main__).
    """
    if module_name == "__main__":
        module_name = "main"
    if not module_name.startswith(APP_LOGGER_PREFIX):
        module_name = f"{APP_LOGGER_PREFIX}.{module_name}"
    return logging.getLogger(module_name)


def set_level(level: int):
    """Adjusts the root logger's level at runtime, e.g. from a debug toggle in Settings."""
    logging.getLogger().setLevel(level)
    get_logger(__name__).info("Log level changed to %s.", logging.getLevelName(level))
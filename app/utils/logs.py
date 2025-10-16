import logging
import sys


def setup_logger(name: str = "scraper", level: int = logging.INFO) -> logging.Logger:
    """
    Create or retrieve a logger with the given name and configure it to emit
    messages to stdout. Subsequent calls with the same name will return the
    existing logger without attaching additional handlers.

    Args:
        name: The logger name. Defaults to "scraper".
        level: The logging level. Defaults to logging.INFO.

    Returns:
        A configured Logger instance.
    """
    logger = logging.getLogger(name)
    # Only attach a handler if one hasn't been added yet. Without this
    # guard each import of this module would attach additional handlers,
    # resulting in duplicate log lines.
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        fmt = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", "%H:%M:%S")
        handler.setFormatter(fmt)
        logger.addHandler(handler)
        logger.setLevel(level)
    return logger

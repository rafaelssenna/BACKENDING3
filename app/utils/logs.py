"""
Logging utilities for the Helsen IA scraper.

This module provides a helper to configure and retrieve a singleton
logger. We use a single logger across the scraper to emit structured
messages to stdout. If additional handlers or formats are needed in
future it can be extended here. All logs use the same name so that
they can be centrally configured.

Usage::

    from ..utils.logs import setup_logger
    log = setup_logger("scraper")
    log.info("Starting search…")

When using this logger inside async code, avoid awaiting methods on
the logger. The logger is synchronous and thread‑safe by default.
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

_loggers: dict[str, logging.Logger] = {}

def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """Return a configured logger with the given name.

    If a logger with this name already exists, it will be returned.
    Otherwise a new logger will be created with a StreamHandler
    attached to stdout and a simple formatter.

    Args:
        name: The name of the logger. All loggers with the same name share
            handlers and level.
        level: The logging level (default INFO).

    Returns:
        logging.Logger: The configured logger.
    """
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    # Only attach a handler if none are present to avoid duplicate logs
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = False
    _loggers[name] = logger
    return logger

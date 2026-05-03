"""Logging configuration for Instagram Auto Poster."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import structlog


def _colors_supported() -> bool:
    """Return True only when colorama is installed (required by structlog colors)."""
    try:
        import colorama  # noqa: F401
        return True
    except ImportError:
        return False


def setup_logging(log_level: str = "INFO", log_file: Path | None = None) -> None:
    """
    Setup structured logging for the application.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional file path for logging output
    """
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper()),
    )
    
    # Add file handler if specified
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger().addHandler(file_handler)
    
    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="ISO"),
            structlog.dev.ConsoleRenderer(colors=_colors_supported())
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper())
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """
    Get a structured logger instance.
    
    Args:
        name: Logger name (typically __name__)
        
    Returns:
        Configured structlog logger
    """
    return structlog.get_logger(name)


def log_function_call(func_name: str, **kwargs: Any) -> None:
    """
    Log a function call with parameters.
    
    Args:
        func_name: Name of the function being called
        **kwargs: Function parameters to log
    """
    logger = get_logger("function_call")
    logger.info(f"Calling {func_name}", **kwargs)


def log_error(error: Exception, context: dict[str, Any] | None = None) -> None:
    """
    Log an error with context.
    
    Args:
        error: The exception that occurred
        context: Additional context information
    """
    logger = get_logger("error")
    log_data = {
        "error_type": type(error).__name__,
        "error_message": str(error),
    }
    if context:
        log_data.update(context)
    
    logger.error("Error occurred", **log_data)
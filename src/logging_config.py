"""Rich-based logging configuration for the conversion pipeline."""

import logging

from rich.console import Console
from rich.logging import RichHandler

_configured = False


def setup_logging(level: str = "INFO") -> None:
    """Configure logging with Rich handler. Idempotent; only runs once."""
    global _configured
    if _configured:
        return
    console = Console(stderr=True)
    handler = RichHandler(
        console=console,
        show_path=False,
        show_time=True,
        rich_tracebacks=True,
        tracebacks_show_locals=True,
    )
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(name)-15s %(message)s",
        handlers=[handler],
    )
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a logger instance for the given module name."""
    return logging.getLogger(name)

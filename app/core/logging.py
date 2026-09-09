"""Console-only, allowlisted operational logging.

Use fixed event codes only. Arbitrary messages, interpolation arguments, exception
text and stack traces are discarded to avoid logging sensitive payloads.
"""
import logging

_ALLOWED_EVENTS = frozenset({"foundation_ready", "configuration_loaded", "shutdown"})
_HANDLER_MARKER = "_voicepilot_console"


class _SafeEventFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = record.msg if isinstance(record.msg, str) else None
        if event not in _ALLOWED_EVENTS or record.args:
            event = "event_redacted"
        return str(record.levelno) + " " + event


def configure_logging(level: str | int = "INFO") -> logging.Logger:
    """Configure the dedicated application logger without touching root handlers."""
    logger = logging.getLogger("voicepilot")
    logger.setLevel(level)
    logger.propagate = False
    if not any(getattr(handler, _HANDLER_MARKER, False) for handler in logger.handlers):
        handler = logging.StreamHandler()
        setattr(handler, _HANDLER_MARKER, True)
        handler.setFormatter(_SafeEventFormatter())
        logger.addHandler(handler)
    return logger

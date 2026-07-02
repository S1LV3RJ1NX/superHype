"""structlog configuration and a get_logger helper."""

import logging

import structlog

from app.config import settings

_configured = False


class _SuppressHealthzAccess(logging.Filter):
    """Drop uvicorn access-log lines for the liveness probe.

    Probes hit GET /healthz every couple of seconds, which otherwise floods the
    access log and buries real traffic. Uvicorn passes the request path as the
    third positional arg of the access record, so filter on that.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3:
            return "/healthz" not in str(args[2])
        return True


def configure_logging() -> None:
    global _configured
    if _configured:
        return

    logging.getLogger("uvicorn.access").addFilter(_SuppressHealthzAccess())

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    if settings.is_production:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    configure_logging()
    return structlog.get_logger(name)

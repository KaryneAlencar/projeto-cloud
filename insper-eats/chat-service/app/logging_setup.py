"""Saída de logs da aplicação independente do logger interno do Uvicorn."""
import logging
import json
from contextvars import ContextVar
from datetime import datetime, timezone

request_id_context = ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), "level": record.levelname,
                           "logger": record.name, "request_id": request_id_context.get(),
                           "message": record.getMessage()}, ensure_ascii=False)


def configure_logging():
    logger = logging.getLogger("insper-eats-chat")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

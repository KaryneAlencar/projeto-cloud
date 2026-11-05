"""Saída de logs da aplicação independente do logger interno do Uvicorn."""
import logging


def configure_logging():
    logger = logging.getLogger("insper-eats-chat")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

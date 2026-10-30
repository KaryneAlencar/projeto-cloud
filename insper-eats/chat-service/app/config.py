import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    database_url: str
    orders_api_url: str = "http://127.0.0.1:8000"
    orders_timeout: float = 5.0

    @classmethod
    def from_env(cls):
        # Este serviço usa seu próprio arquivo; não carrega o .env do backend.
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        url = os.getenv("CHAT_DATABASE_URL", "")
        if not url:
            raise RuntimeError("Configure CHAT_DATABASE_URL em chat-service/.env")
        if not url.startswith("postgresql+psycopg://"):
            raise RuntimeError("CHAT_DATABASE_URL deve usar postgresql+psycopg://")
        timeout = float(os.getenv("ORDERS_API_TIMEOUT", "5"))
        if timeout <= 0:
            raise RuntimeError("ORDERS_API_TIMEOUT deve ser positivo")
        return cls(url, os.getenv("ORDERS_API_URL", "http://127.0.0.1:8000").rstrip("/"), timeout)

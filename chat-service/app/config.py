import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    database_url: str
    orders_api_url: str = "http://127.0.0.1:8000"
    orders_timeout: float = 5.0
    ai_provider: str = "gemini"
    openai_api_key: str = ""
    openai_model: str = ""
    ai_timeout: float = 120.0
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    cookie_secure: bool = False
    session_days: int = 30
    allowed_origins: tuple[str, ...] = ("http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:8080", "http://localhost:8080")
    cookie_name: str = "insper_eats_session"

    @property
    def ai_configured(self):
        if self.ai_provider == "gemini":
            return bool(self.gemini_api_key and self.gemini_model)
        if self.ai_provider == "openai":
            return bool(self.openai_api_key and self.openai_model)
        return False

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
        provider = os.getenv("AI_PROVIDER", "gemini")
        if provider not in {"gemini", "openai", "commands"}:
            raise RuntimeError("AI_PROVIDER deve ser gemini, openai ou commands")
        ai_timeout = float(os.getenv("AI_TIMEOUT", "120"))
        if not 0 < ai_timeout <= 120:
            raise RuntimeError("AI_TIMEOUT deve ser maior que 0 e no máximo 120 segundos")
        session_days = int(os.getenv("SESSION_DAYS", "30"))
        if not 1 <= session_days <= 365:
            raise RuntimeError("SESSION_DAYS deve estar entre 1 e 365 dias")
        return cls(url, os.getenv("ORDERS_API_URL", "http://127.0.0.1:8000").rstrip("/"), timeout,
                   provider, os.getenv("OPENAI_API_KEY", ""), os.getenv("OPENAI_MODEL", ""),
                   ai_timeout, os.getenv("GEMINI_API_KEY", ""), os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
                   os.getenv("COOKIE_SECURE", "false").lower() == "true",
                   session_days,
                   tuple(origin.strip().rstrip("/") for origin in os.getenv("APP_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:8080,http://localhost:8080").split(",") if origin.strip()),
                   os.getenv("SESSION_COOKIE_NAME", "insper_eats_session"))

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool


def pool_setting(name, default, minimum):
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} deve ser um número inteiro") from exc
    if value < minimum:
        raise RuntimeError(f"{name} deve ser no mínimo {minimum}")
    return value


def connect_database(url):
    # Pool explícito: no máximo DB_POOL_SIZE + DB_MAX_OVERFLOW conexões por processo.
    # pool_timeout curto: com o pool cheio a requisição recebe 503 em vez de ficar na fila.
    engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5},
                           pool_size=pool_setting("DB_POOL_SIZE", 5, 1),
                           max_overflow=pool_setting("DB_MAX_OVERFLOW", 10, 0),
                           pool_timeout=5)
    return engine, sessionmaker(engine, expire_on_commit=False)


def connect_health(url):
    """Conexão dedicada do /health, fora do pool: responde mesmo com o pool ocupado."""
    return create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 2})

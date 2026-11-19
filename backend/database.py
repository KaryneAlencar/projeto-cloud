
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlmodel import Session, create_engine

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path)

DATABASE_URL = os.environ["DATABASE_URL"]

# Prazos explícitos: sem eles, um RDS em failover prende cada requisição até o
# timeout de TCP. O pool é dimensionado por variável porque API e worker têm
# perfis diferentes e a soma das réplicas não pode passar do max_connections.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
    max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "5")),
    pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "5")),
    connect_args={
        "connect_timeout": 5,
        "options": "-c lock_timeout=10000 -c statement_timeout=20000"
    }
)

def get_session():
    with Session(engine) as session:
        yield session

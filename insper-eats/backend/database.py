
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlmodel import Session, create_engine

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path)

DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True
)

def get_session():
    with Session(engine) as session:
        yield session

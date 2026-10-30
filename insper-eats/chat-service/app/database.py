from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def connect_database(url):
    engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 5})
    return engine, sessionmaker(engine, expire_on_commit=False)

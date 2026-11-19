"""Inicializa o PostgreSQL do Insper Eats. Roda uma vez, na task db-init.

Como administrador do RDS:
  - cria (ou atualiza a senha de) insper_app e insper_chat;
  - cria o banco exclusivo do chat;
  - concede a cada usuário apenas o próprio banco.

Depois, como insper_app, cria as tabelas da API para que API e worker não
disputem a criação ao subir juntos, e insere o catálogo inicial se a tabela de
produtos estiver vazia.

As senhas vêm das URLs guardadas no Secrets Manager; nada é impresso.
Pode ser executado quantas vezes for preciso.
"""
import json
import os
import sys
from decimal import Decimal
from urllib.parse import unquote, urlsplit

import psycopg
from psycopg import sql


def split_url(url):
    """Devolve (usuario, senha, banco, conninfo libpq) de uma URL SQLAlchemy."""
    libpq_url = "postgresql://" + url.split("://", 1)[1]
    parts = urlsplit(libpq_url)
    if not (parts.username and parts.password and parts.path.strip("/")):
        raise SystemExit("URL de banco sem usuario, senha ou nome do banco.")
    return unquote(parts.username), unquote(parts.password), parts.path.strip("/"), libpq_url


def admin_connect(dbname):
    return psycopg.connect(
        host=os.environ["DB_HOST"],
        port=os.environ.get("DB_PORT", "5432"),
        dbname=dbname,
        user=os.environ["MASTER_USERNAME"],
        password=os.environ["MASTER_PASSWORD"],
        sslmode=os.environ.get("DB_SSLMODE", "require"),
        connect_timeout=10,
        autocommit=True,
    )


def ensure_role(conn, user, password):
    exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (user,)).fetchone()
    action = sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}") if exists else sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD {}")
    conn.execute(action.format(sql.Identifier(user), sql.Literal(password)))


def ensure_database(conn, dbname):
    if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)).fetchone():
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))


def grant_database(admin_db, dbname, user):
    """O banco fica acessível só ao seu usuário, que pode criar tabelas em public."""
    with admin_connect(admin_db) as conn:
        conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(dbname)))
        conn.execute(sql.SQL("GRANT CONNECT, TEMPORARY ON DATABASE {} TO {}").format(
            sql.Identifier(dbname), sql.Identifier(user)))
    with admin_connect(dbname) as conn:
        conn.execute(sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(sql.Identifier(user)))


def check_login(label, libpq_url, user):
    with psycopg.connect(libpq_url, connect_timeout=10) as conn:
        current = conn.execute("SELECT current_user").fetchone()[0]
    if current != user:
        raise SystemExit(f"Login de {label} retornou um usuario inesperado.")
    print(f"CONEXAO_{label}_OK", flush=True)


def seed_catalog(engine, product_model):
    """Catálogo inicial: só em banco novo, para nunca duplicar nem repor estoque."""
    from sqlmodel import Session, select

    products = json.loads(os.environ.get("SEED_PRODUCTS") or "[]")
    with Session(engine) as session:
        if not products or session.exec(select(product_model).limit(1)).first():
            print("CATALOGO_INICIAL_IGNORADO", flush=True)
            return
        for product in products:
            session.add(product_model(nome=product["nome"], preco=Decimal(str(product["preco"])),
                                      estoque=int(product["estoque"])))
        session.commit()
    print(f"CATALOGO_INICIAL_INSERIDO {len(products)}", flush=True)


def main():
    admin_db = os.environ["DB_NAME"]
    app_user, app_password, app_db, app_url = split_url(os.environ["DATABASE_URL"])
    chat_user, chat_password, chat_db, chat_url = split_url(os.environ["CHAT_DATABASE_URL"])

    with admin_connect(admin_db) as conn:
        ensure_role(conn, app_user, app_password)
        ensure_role(conn, chat_user, chat_password)
        ensure_database(conn, app_db)
        ensure_database(conn, chat_db)

    grant_database(admin_db, app_db, app_user)
    print("USUARIO_INSPER_APP_CONFIGURADO", flush=True)
    grant_database(admin_db, chat_db, chat_user)
    print("USUARIO_INSPER_CHAT_CONFIGURADO", flush=True)

    check_login("APP", app_url, app_user)
    check_login("CHAT", chat_url, chat_user)

    if os.environ.get("CREATE_APP_SCHEMA", "true").lower() == "true":
        # Mesmo código que a API executa ao iniciar (backend/main.py).
        from sqlmodel import SQLModel

        import models  # noqa: F401  registra as tabelas
        from database import engine

        SQLModel.metadata.create_all(engine)
        print("TABELAS_API_CRIADAS", flush=True)
        seed_catalog(engine, models.Produto)

    print("DB_INIT_CONCLUIDO", flush=True)


if __name__ == "__main__":
    try:
        main()
    except psycopg.Error as error:
        # Só a classe e o SQLSTATE: mensagens do driver podem conter a URL.
        print(f"DB_INIT_FALHOU {type(error).__name__} sqlstate={error.sqlstate}", file=sys.stderr, flush=True)
        sys.exit(1)

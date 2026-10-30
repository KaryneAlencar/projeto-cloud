from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id():
    return str(uuid4())


def now():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "chat_conversa"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    atualizada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    estado: Mapped[str] = mapped_column(String(32), default="aberta")
    # Snapshot de preparação. Nunca escreve em tabelas de pedidos ou estoque.
    compra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    chave_idempotencia: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    pedido_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Message(Base):
    __tablename__ = "chat_mensagem"
    sequencia: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(36), unique=True, default=new_id)
    conversa_id: Mapped[str] = mapped_column(ForeignKey("chat_conversa.id"), index=True)
    papel: Mapped[str] = mapped_column(String(16))
    conteudo: Mapped[str] = mapped_column(Text)
    criada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MessageRequest(Base):
    __tablename__ = "chat_requisicao"
    __table_args__ = (UniqueConstraint("conversa_id", "mensagem_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversa_id: Mapped[str] = mapped_column(ForeignKey("chat_conversa.id"), index=True)
    mensagem_id: Mapped[str] = mapped_column(String(36))
    conteudo: Mapped[str] = mapped_column(Text)
    resposta: Mapped[dict] = mapped_column(JSON)

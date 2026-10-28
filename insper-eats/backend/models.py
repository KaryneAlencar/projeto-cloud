
from decimal import Decimal
from sqlmodel import SQLModel, Field
from datetime import datetime, timezone
from sqlalchemy import UniqueConstraint


class ProdutoBase(SQLModel):
    nome: str = Field(min_length=2, max_length=100)
    preco: Decimal = Field(
        gt=0,
        max_digits=10,
        decimal_places=2
    )
    estoque: int = Field(default=0, ge=0)


class Produto(ProdutoBase, table=True):
    id: int | None = Field(
        default=None,
        primary_key=True
    )


class ProdutoCreate(ProdutoBase):
    pass


class ProdutoPublic(ProdutoBase):
    id: int

class Pedido(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "chave_idempotencia",
            name="uq_pedido_chave"
        ),
    )

    id: int | None = Field(
        default=None, primary_key=True
    )
    cliente: str
    local_entrega: str
    status: str = Field(default="recebido")
    total: Decimal = Field(
        default=Decimal("0.00"),
        max_digits=12,
        decimal_places=2
    )
    chave_idempotencia: str = Field(max_length=64)
    hash_requisicao: str = Field(max_length=64)
    criado_em: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class ItemPedido(SQLModel, table=True):
    id: int | None = Field(
        default=None, primary_key=True
    )
    pedido_id: int = Field(foreign_key="pedido.id")
    produto_id: int = Field(foreign_key="produto.id")
    quantidade: int
    preco_unitario: Decimal = Field(
        max_digits=10, decimal_places=2
    )
    subtotal: Decimal = Field(
        max_digits=12, decimal_places=2
    )


class ItemPedidoCreate(SQLModel):
    produto_id: int = Field(gt=0)
    quantidade: int = Field(gt=0)


class PedidoCreate(SQLModel):
    cliente: str = Field(min_length=2)
    local_entrega: str = Field(min_length=3)
    chave_idempotencia: str = Field(
        min_length=8, max_length=64
    )
    itens: list[ItemPedidoCreate] = Field(min_length=1)


class ItemPedidoPublic(SQLModel):
    produto_id: int
    quantidade: int
    preco_unitario: Decimal
    subtotal: Decimal


class PedidoPublic(SQLModel):
    id: int
    cliente: str
    local_entrega: str
    status: str
    total: Decimal
    criado_em: datetime
    itens: list[ItemPedidoPublic]


class EventoOutbox(SQLModel, table=True):
    id: int | None = Field(
        default=None,
        primary_key=True
    )
    pedido_id: int = Field(
        foreign_key="pedido.id",
        index=True
    )
    tipo: str = Field(default="pedido.criado")
    publicado: bool = Field(
        default=False,
        index=True
    )

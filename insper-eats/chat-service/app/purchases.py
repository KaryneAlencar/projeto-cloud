from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from .models import new_id


class SelectionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    produto_id: StrictInt = Field(gt=0)
    quantidade: StrictInt = Field(gt=0, le=10000)


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    itens: list[SelectionItem] = Field(min_length=1, max_length=50)
    cliente: str | None
    local_entrega: str | None


class Delivery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cliente: str | None
    local_entrega: str | None


def prepare(conversation, selection, orders):
    if conversation.estado == "confirmando":
        raise ValueError("Há uma confirmação pendente. Repita a confirmação antes de alterar a compra.")
    products = {p.id: p for p in orders.products()}
    if len({i.produto_id for i in selection.itens}) != len(selection.itens):
        raise ValueError("Produto repetido na seleção.")
    items, total = [], Decimal("0.00")
    for item in selection.itens:
        p = products.get(item.produto_id)
        if p is None:
            raise ValueError(f"Produto ID {item.produto_id} não existe no catálogo atual. Consulte listar_produtos e use o ID retornado para o produto solicitado.")
        if item.quantidade > p.estoque:
            raise ValueError(f"Estoque insuficiente para {p.nome}: {p.estoque} disponíveis.")
        total += p.preco * item.quantidade
        items.append({"produto_id": p.id, "nome": p.nome, "quantidade": item.quantidade, "preco_unitario": float(p.preco)})
    old = conversation.compra or {}
    carry = old if old.get("status") == "preparando" else {}
    conversation.compra = {"id": new_id(), "status": "preparando", "itens": items, "total": float(total),
                           "cliente": (selection.cliente if selection.cliente is not None else carry.get("cliente", "")).strip(),
                           "local_entrega": (selection.local_entrega if selection.local_entrega is not None else carry.get("local_entrega", "")).strip()}
    conversation.chave_idempotencia = conversation.compra["id"]
    conversation.estado = "preparando"
    conversation.pedido_id = None
    return conversation.compra


def delivery(conversation, data):
    if not conversation.compra or conversation.compra["status"] != "preparando":
        raise ValueError("Prepare uma seleção antes de informar os dados de entrega.")
    purchase = dict(conversation.compra)
    for field in ("cliente", "local_entrega"):
        if getattr(data, field) is not None:
            purchase[field] = getattr(data, field).strip()
    purchase["id"] = new_id()
    conversation.compra = purchase
    conversation.chave_idempotencia = purchase["id"]
    return purchase


import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session, select
from sqlalchemy.exc import IntegrityError

from database import get_session
from models import (
    Produto,
    Pedido,
    ItemPedido,
    PedidoCreate,
    PedidoPublic,
    EventoOutbox
)


router = APIRouter(prefix="/pedidos", tags=["Pedidos"])


def detalhes_pedido(session: Session, pedido: Pedido):
    itens = session.exec(
        select(ItemPedido).where(
            ItemPedido.pedido_id == pedido.id
        )
    ).all()

    return {
        "id": pedido.id,
        "cliente": pedido.cliente,
        "local_entrega": pedido.local_entrega,
        "status": pedido.status,
        "total": pedido.total,
        "criado_em": pedido.criado_em,
        "itens": itens
    }


@router.post(
    "",
    response_model=PedidoPublic,
    status_code=201
)
def criar_pedido(
    dados: PedidoCreate,
    response: Response,
    session: Session = Depends(get_session)
):
    ids = [item.produto_id for item in dados.itens]

    if len(ids) != len(set(ids)):
        raise HTTPException(
            status_code=400,
            detail="Produto repetido no pedido"
        )

    conteudo = {
        "cliente": dados.cliente,
        "local_entrega": dados.local_entrega,
        "itens": sorted(
            [item.model_dump() for item in dados.itens],
            key=lambda item: item["produto_id"]
        )
    }

    hash_requisicao = hashlib.sha256(
        json.dumps(
            conteudo, sort_keys=True
        ).encode("utf-8")
    ).hexdigest()

    def verificar_repeticao(pedido):
        if pedido.hash_requisicao != hash_requisicao:
            raise HTTPException(
                status_code=409,
                detail="Chave utilizada para outro pedido"
            )
        response.status_code = 200
        return detalhes_pedido(session, pedido)

    existente = session.exec(
        select(Pedido).where(
            Pedido.chave_idempotencia ==
            dados.chave_idempotencia
        )
    ).first()

    if existente:
        return verificar_repeticao(existente)

    pedido = Pedido(
        cliente=dados.cliente,
        local_entrega=dados.local_entrega,
        chave_idempotencia=dados.chave_idempotencia,
        hash_requisicao=hash_requisicao
    )

    try:
        session.add(pedido)
        session.flush()

        total = 0

        for item in sorted(
            dados.itens,
            key=lambda item: item.produto_id
        ):
            produto = session.exec(
                select(Produto)
                .where(Produto.id == item.produto_id)
                .with_for_update()
            ).first()

            if produto is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Produto {item.produto_id} não encontrado"
                )

            if produto.estoque < item.quantidade:
                raise HTTPException(
                    status_code=409,
                    detail=f"Estoque insuficiente: {produto.nome}"
                )

            subtotal = produto.preco * item.quantidade
            total += subtotal

            produto.estoque -= item.quantidade

            session.add(ItemPedido(
                pedido_id=pedido.id,
                produto_id=produto.id,
                quantidade=item.quantidade,
                preco_unitario=produto.preco,
                subtotal=subtotal
            ))


        pedido.total = total

        evento = EventoOutbox(
            pedido_id=pedido.id,
            tipo="pedido.criado"
        )

        session.add(evento)

        session.commit()
        session.refresh(pedido)


    except IntegrityError:
        session.rollback()

        existente = session.exec(
            select(Pedido).where(
                Pedido.chave_idempotencia ==
                dados.chave_idempotencia
            )
        ).first()

        if existente:
            return verificar_repeticao(existente)

        raise HTTPException(
            status_code=409,
            detail="Conflito ao registrar pedido"
        )

    except Exception:
        session.rollback()
        raise

    return detalhes_pedido(session, pedido)


@router.get(
    "/{pedido_id}",
    response_model=PedidoPublic
)
def consultar_pedido(
    pedido_id: int,
    session: Session = Depends(get_session)
):
    pedido = session.get(Pedido, pedido_id)

    if pedido is None:
        raise HTTPException(
            status_code=404,
            detail="Pedido não encontrado"
        )

    return detalhes_pedido(session, pedido)

from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select

from .models import CheckoutAttempt, Message, new_id, now
from .orders import OrdersError


def confirm_purchase(sessions, conversation_id, purchase_id, orders, find, snapshot):
    review_required = False
    # Fase 1: commit local ANTES do efeito externo. A seleção fica congelada.
    with sessions.begin() as session:
        conversation = find(session, conversation_id, lock=True)
        purchase = conversation.compra
        if not purchase or purchase["id"] != purchase_id:
            raise HTTPException(409, "A seleção mudou. Atualize a conversa e confira o resumo antes de confirmar.")
        attempt = session.get(CheckoutAttempt, purchase_id)
        if attempt and attempt.status == "confirmado":
            return snapshot(session, conversation)
        if attempt and attempt.status == "recusado":
            raise HTTPException(attempt.erro["status"], attempt.erro["detail"])
        if not attempt:
            if purchase["status"] != "preparando" or len(purchase["cliente"].strip()) < 2 or len(purchase["local_entrega"].strip()) < 3:
                raise HTTPException(422, "Prepare a seleção e informe nome e local de entrega antes de confirmar.")
            if conversation.chave_idempotencia != purchase_id:
                raise HTTPException(409, "Seleção sem chave válida. Prepare uma nova seleção.")
            products = {p.id: p for p in orders.products()}
            total, items, changed = Decimal("0.00"), [], False
            for item in purchase["itens"]:
                product = products.get(item["produto_id"])
                if not product or product.estoque < item["quantidade"]:
                    raise HTTPException(409, "Produto indisponível ou estoque insuficiente. Revise a seleção.")
                changed |= product.preco != Decimal(str(item["preco_unitario"]))
                total += product.preco * item["quantidade"]
                items.append({**item, "preco_unitario": float(product.preco)})
            if changed:
                updated = {**purchase, "id": new_id(), "itens": items, "total": float(total)}
                conversation.compra = updated
                conversation.chave_idempotencia = updated["id"]
                session.add(Message(conversa_id=conversation.id, papel="assistente", conteudo="Os preços mudaram. Atualizei o resumo; revise e confirme novamente."))
                review_required = True
            else:
                payload = {"cliente": purchase["cliente"], "local_entrega": purchase["local_entrega"],
                           "chave_idempotencia": conversation.chave_idempotencia,
                           "itens": [{"produto_id": i["produto_id"], "quantidade": i["quantidade"]} for i in purchase["itens"]]}
                session.add(CheckoutAttempt(compra_id=purchase_id, conversa_id=conversation.id, payload=payload))
                conversation.estado = "confirmando"
                conversation.compra = {**purchase, "status": "confirmando"}
            conversation.atualizada_em = now()

    if review_required:
        with sessions() as session:
            return snapshot(session, find(session, conversation_id))

    failure = None
    # Fase 2: serializa confirmações concorrentes, inclusive entre processos/abas.
    # O payload já está salvo. Timeout/queda não permite editar nem gerar outra chave.
    with sessions.begin() as session:
        conversation = find(session, conversation_id, lock=True)
        attempt = session.scalar(select(CheckoutAttempt).where(CheckoutAttempt.compra_id == purchase_id).with_for_update())
        if attempt.status == "confirmado":
            return snapshot(session, conversation)
        if attempt.status == "recusado":
            raise HTTPException(attempt.erro["status"], attempt.erro["detail"])
        try:
            order = orders.create_order(attempt.payload)
        except OrdersError as exc:
            failure = exc
            if exc.definitive:
                attempt.status = "recusado"
                attempt.erro = {"status": exc.status, "detail": exc.detail}
                conversation.estado = "preparando"
                # Nova versão permite revisar/repetir uma compra realmente recusada.
                replacement_id = new_id()
                conversation.compra = {**conversation.compra, "id": replacement_id, "status": "preparando"}
                conversation.chave_idempotencia = replacement_id
            # Em resultado incerto, mantém confirmando + payload original persistido.
        else:
            attempt.status = "confirmado"
            attempt.resposta = order.model_dump(mode="json")
            conversation.estado = "confirmado"
            conversation.pedido_id = order.id
            prices = {i.produto_id: i.preco_unitario for i in order.itens}
            conversation.compra = {**conversation.compra, "status": "confirmado", "pedido_id": str(order.id),
                                   "pedido_status": order.status, "total": float(order.total),
                                   "itens": [{**i, "preco_unitario": float(prices.get(i["produto_id"], i["preco_unitario"]))} for i in conversation.compra["itens"]]}
            session.add(Message(conversa_id=conversation.id, papel="assistente", conteudo=f"Pedido #{order.id} registrado. Status: {order.status}. Total: R$ {order.total:.2f}."))
        conversation.atualizada_em = now()
        session.flush()
        result = snapshot(session, conversation)
    if failure:
        raise failure
    return result

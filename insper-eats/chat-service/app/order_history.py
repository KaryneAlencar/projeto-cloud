from sqlalchemy import select

from .models import CheckoutAttempt, Conversation


def list_conversation_orders(session, conversation_id, orders):
    """Pedidos vinculados a esta conversa; status atualizado pela API de pedidos."""
    attempts = session.scalars(select(CheckoutAttempt).where(
        CheckoutAttempt.conversa_id == str(conversation_id),
        CheckoutAttempt.status == "confirmado",
    ).order_by(CheckoutAttempt.criada_em.desc())).all()
    ids = []
    for attempt in attempts:
        if attempt.resposta and type(attempt.resposta.get("id")) is int:
            ids.append(attempt.resposta["id"])
    conversation = session.get(Conversation, str(conversation_id))
    if conversation and conversation.pedido_id and conversation.pedido_id not in ids:
        ids.insert(0, conversation.pedido_id)
    results = []
    for order_id in dict.fromkeys(ids):
        order = orders.order(order_id)
        results.append({"pedido_id": order.id, "status": order.status, "total": float(order.total)})
    return {"escopo": "pedidos registrados nesta conversa", "pedidos": results}

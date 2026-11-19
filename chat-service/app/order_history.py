from sqlalchemy import select

from .models import CheckoutAttempt, Conversation, ConversationAccess
from .orders import OrdersError


def conversation_order_ids(session, conversation_id):
    """Somente leitura local: IDs dos pedidos registrados nesta conversa."""
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
    return list(dict.fromkeys(ids))


def fetch_orders(order_ids, orders, scope):
    """Chamadas HTTP em série: quem chama NÃO deve estar com uma sessão do banco aberta."""
    results = []
    for order_id in order_ids:
        order = orders.order(order_id)
        results.append({"pedido_id": order.id, "status": order.status, "total": float(order.total)})
    return {"escopo": scope, "pedidos": results}


CONVERSATION_SCOPE = "pedidos registrados nesta conversa"
BROWSER_SCOPE = "pedidos deste navegador"


def owned_order_ids(session, owner):
    cids = session.scalars(select(ConversationAccess.conversa_id).where(ConversationAccess.sessao_hash == owner)).all()
    if not cids:
        return []
    attempts = session.scalars(select(CheckoutAttempt).where(CheckoutAttempt.conversa_id.in_(cids), CheckoutAttempt.status == "confirmado").order_by(CheckoutAttempt.criada_em.desc())).all()
    ids = [attempt.resposta["id"] for attempt in attempts if attempt.resposta and type(attempt.resposta.get("id")) is int]
    ids += list(session.scalars(select(Conversation.pedido_id).where(Conversation.id.in_(cids), Conversation.pedido_id.is_not(None))).all())
    return list(dict.fromkeys(ids))


def list_browser_orders(session, owner, orders):
    # Usado dentro da transação da mensagem (ferramenta da IA); os endpoints HTTP
    # leem os IDs, fecham a sessão e só então chamam fetch_orders.
    return fetch_orders(owned_order_ids(session, owner), orders, BROWSER_SCOPE)


class OwnedOrdersClient:
    """Mantém catálogo público e restringe consulta de pedidos à sessão atual."""
    def __init__(self, session, owner, orders):
        self.session, self.owner, self.orders = session, owner, orders

    def products(self):
        return self.orders.products()

    def order(self, order_id):
        if order_id not in owned_order_ids(self.session, self.owner):
            raise OrdersError(404, "Pedido não encontrado nesta sessão.")
        return self.orders.order(order_id)

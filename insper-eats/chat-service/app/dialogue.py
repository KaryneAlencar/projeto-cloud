"""Roteamento explícito provisório; será substituído pelo agente de IA."""
import re
import unicodedata
from decimal import Decimal

from .models import new_id


def normalized(text):
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if not unicodedata.combining(c))


def reply(conversation, text, orders):
    content = normalized(text)
    if content in {"cancelar", "cancela", "cancelar compra"}:
        if conversation.compra and conversation.compra["status"] == "confirmado":
            return "Esse pedido já foi registrado. Não é possível cancelá-lo pelo chat."
        conversation.compra = None
        conversation.chave_idempotencia = None
        conversation.estado = "aberta"
        return "Seleção cancelada. Nenhum pedido foi criado."

    match = re.fullmatch(r"(?:consultar\s+)?pedido\s*#?\s*(\d+)", content)
    if match:
        order = orders.order(int(match[1]))
        return f"Pedido #{order.id}: {order.status}. Total: R$ {order.total:.2f}."

    if any(term in content for term in ("cardapio", "catalogo", "disponive", "preco")):
        products = orders.products()
        if not products:
            return "O catálogo está vazio no momento. Nenhum produto foi inventado."
        return "Catálogo real:\n" + "\n".join(
            f"{p.nome} (ID {p.id}) · R$ {p.preco:.2f} · estoque {p.estoque}" for p in products
        ) + '\n\nPara preparar uma seleção, envie “Quero 2 brownies” ou “Selecionar 1:2, 2:1” (ID:quantidade).'

    if content.startswith("selecionar ") or content.startswith("quero "):
        products = orders.products()
        by_id = {p.id: p for p in products}
        selection = []
        if content.startswith("selecionar "):
            parts = content.removeprefix("selecionar ").split(",")
            if not all(re.fullmatch(r"\s*\d+\s*:\s*\d+\s*", part) for part in parts):
                return 'Use “Selecionar 1:2, 2:1”, com ID:quantidade.'
            for part in parts:
                pid, quantity = map(int, part.split(":"))
                if pid not in by_id:
                    return f"Produto {pid} não encontrado no catálogo real."
                selection.append((by_id[pid], quantity))
        else:
            match = re.fullmatch(r"quero\s+(\d+)\s+(.+?)[.!]?", content)
            if not match:
                return 'Informe uma quantidade: “Quero 2 brownies”. Para vários produtos, use “Selecionar ID:quantidade, ID:quantidade”.'
            quantity, name = int(match[1]), match[2].strip()
            matches = [p for p in products if normalized(p.nome).rstrip("s") == name.rstrip("s")]
            if len(matches) != 1:
                return 'Não identifiquei um único produto. Consulte o cardápio e use “Selecionar ID:quantidade”.'
            selection.append((matches[0], quantity))
        if len({p.id for p, _ in selection}) != len(selection):
            return "Informe cada produto apenas uma vez."
        for product, quantity in selection:
            if quantity < 1 or quantity > product.estoque:
                return f"Quantidade indisponível para {product.nome}. Estoque atual: {product.estoque}."
        purchase_id = new_id()
        conversation.compra = {
            "id": purchase_id, "status": "preparando", "cliente": "", "local_entrega": "",
            "itens": [{"produto_id": p.id, "nome": p.nome, "quantidade": q, "preco_unitario": float(p.preco)} for p, q in selection],
            "total": float(sum((p.preco * q for p, q in selection), Decimal("0.00"))),
        }
        conversation.chave_idempotencia = purchase_id
        conversation.estado = "preparando"
        return 'Seleção salva, sem reservar estoque. Envie “Meu nome é Ana” e “Entrega: sala 512, prédio 2”. Uma nova seleção substitui a anterior. Revise o resumo e use o botão Confirmar pedido para comprar.'

    name = re.match(r"^(?:meu nome é|meu nome e|nome:)\s*(.*)$", text, re.I)
    address = re.match(r"^entrega:\s*(.*)$", text, re.I)
    if name or address:
        if not conversation.compra:
            return "Selecione os produtos antes de informar os dados de entrega."
        value = (name or address)[1].strip()
        if len(value) < (2 if name else 3):
            return "Informe um nome ou local de entrega válido."
        purchase = dict(conversation.compra)
        purchase["cliente" if name else "local_entrega"] = value
        # Qualquer alteração cria uma versão e chave próprias para a futura confirmação.
        purchase["id"] = new_id()
        conversation.compra = purchase
        conversation.chave_idempotencia = purchase["id"]
        return "Informação salva. Confira o resumo da seleção. Use o botão Confirmar pedido após revisar os dados."

    return 'Esta etapa ainda não usa IA. Posso consultar o catálogo real (“Ver o cardápio”), preparar uma seleção (“Quero 2 brownies”) ou consultar um pedido (“Pedido 4”).'

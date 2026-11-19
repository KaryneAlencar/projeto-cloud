"""Roteamento por comandos explícitos, sem chamada à IA: modo AI_PROVIDER=commands e
reserva do modo gemini quando todos os modelos estão indisponíveis (AI_FALLBACK_COMMANDS)."""
import re
import unicodedata
from decimal import Decimal

from .models import new_id
from .orders import OrdersError


def normalized(text):
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if not unicodedata.combining(c))


NUMBERS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5,
           "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10}
# Palavras entre a quantidade e o nome: "quero 2 dos brownies", "quero 3 unidades de café".
FILLERS = {"o", "a", "os", "as", "de", "do", "da", "dos", "das", "unidade", "unidades"}
WANT = re.compile(rf"quero\s+(\d+|{'|'.join(NUMBERS)})\s+(.+)")


def word_forms(word):
    """A palavra e seus possíveis singulares; plural e singular compartilham uma forma."""
    forms = {word}
    if word.endswith("s") and len(word) > 2:
        forms.add(word[:-1])                                  # brownies/brownie, cafes/cafe
        if word.endswith(("oes", "aes")):
            forms.add(word[:-3] + "ao")                       # paes/pao, limoes/limao
        if word.endswith(("res", "zes", "ses")):
            forms.add(word[:-2])                              # sabores/sabor
        if word.endswith("ns"):
            forms.add(word[:-2] + "m")                        # folhagens/folhagem
        if word.endswith(("ais", "eis", "ois")):
            forms.add(word[:-2] + "l")                        # pasteis/pastel
    return forms


def same_word(a, b):
    return bool(word_forms(a) & word_forms(b))


def find_product(name, products):
    """Produto único correspondente ao nome digitado; None se não houver ou for ambíguo."""
    wanted = re.findall(r"[a-z0-9]+", name)
    while wanted and wanted[0] in FILLERS:
        wanted.pop(0)
    if not wanted:
        return None
    named = [(p, re.findall(r"[a-z0-9]+", normalized(p.nome))) for p in products]
    # 1) Nome completo, tolerando plural. 2) Único produto cujo nome contém todas as palavras.
    exact = [p for p, words in named if len(words) == len(wanted) and all(map(same_word, words, wanted))]
    partial = [p for p, words in named if all(any(same_word(w, word) for word in words) for w in wanted)]
    for matches in (exact, partial):
        if matches:
            return matches[0] if len(matches) == 1 else None
    return None


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
        try:
            order = orders.order(int(match[1]))
        except OrdersError as exc:
            if exc.status != 404:
                raise
            return "Não encontrei esse pedido nesta sessão."
        return f"Pedido #{order.id}: {order.status}. Total: R$ {order.total:.2f}."

    if any(term in content for term in ("cardapio", "catalogo", "disponive", "preco")):
        products = orders.products()
        if not products:
            return "O catálogo está vazio no momento. Nenhum produto foi inventado."
        available = [p for p in products if p.estoque > 0]
        if not available:
            return "Não temos produtos disponíveis no momento."
        return "Nosso cardápio:\n" + "\n".join(
            f"- **{p.nome}** · R$ {p.preco:.2f}" for p in available
        ) + '\n\nO que você gostaria de pedir?'

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
            match = WANT.fullmatch(re.sub(r"(?:,?\s*por favor)?\s*[.!?]*$", "", content))
            if not match:
                return 'Informe a quantidade e um produto por vez: “Quero 2 brownies”.'
            quantity = NUMBERS[match[1]] if match[1] in NUMBERS else int(match[1])
            product = find_product(match[2], products)
            if product is None:
                return 'Não identifiquei um único produto. Consulte o cardápio (“Ver o cardápio”) e use o nome como aparece nele: “Quero 2 brownies”.'
            selection.append((product, quantity))
        if len({p.id for p, _ in selection}) != len(selection):
            return "Informe cada produto apenas uma vez."
        for product, quantity in selection:
            if quantity < 1 or quantity > product.estoque:
                return f"Não temos a quantidade solicitada de {product.nome} disponível. Quer escolher uma quantidade menor?"
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
        if conversation.compra["status"] != "preparando":
            if conversation.compra["status"] == "confirmando":
                return "Há uma confirmação pendente. Use Repetir confirmação antes de alterar os dados."
            return "Esse pedido já foi registrado e não pode mais ser alterado. Faça uma nova seleção para outro pedido."
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

    return 'Posso mostrar o cardápio (“Ver o cardápio”), preparar um pedido (“Quero 2 brownies”) ou consultar um pedido (“Pedido 4”).'

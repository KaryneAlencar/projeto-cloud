import json
import logging
from decimal import Decimal
from http.client import HTTPException as HTTPClientError
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field, ValidationError

from .logging_setup import request_id_context

logger = logging.getLogger("insper-eats-chat")

NOT_REGISTERED = "Não foi possível registrar o pedido agora. Nada foi cobrado nem reservado; tente novamente em instantes."


class Product(BaseModel):
    id: int = Field(gt=0)
    nome: str
    preco: Decimal = Field(gt=0)
    estoque: int = Field(ge=0)


class OrderItem(BaseModel):
    produto_id: int
    quantidade: int
    preco_unitario: Decimal
    subtotal: Decimal


class Order(BaseModel):
    id: int = Field(gt=0)
    status: str
    total: Decimal
    itens: list[OrderItem]


class OrdersError(Exception):
    def __init__(self, status, detail, definitive=False, rejected_without_effect=False):
        self.status = status
        self.detail = detail
        # definitive: a API recusou ESTE pedido (dados/estoque); exige nova seleção.
        self.definitive = definitive
        # rejected_without_effect: recusa antes de qualquer efeito (credencial interna);
        # o mesmo pedido pode ser reenviado com a mesma chave de idempotência.
        self.rejected_without_effect = rejected_without_effect


class OrdersClient:
    def __init__(self, base_url, timeout=5, internal_token=""):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.internal_token = internal_token

    def _get(self, path, body=None):
        try:
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }

            if self.internal_token:
                headers["X-Internal-Token"] = self.internal_token

            request_id = request_id_context.get()
            if request_id and request_id != "-":
                headers["X-Request-ID"] = request_id

            req = Request(
                self.base_url + path,
                data=json.dumps(body).encode() if body is not None else None,
                headers=headers,
            )

            with urlopen(req, timeout=self.timeout) as response:
                return json.load(response)

        except HTTPError as exc:
            if body is not None and exc.code in {400, 404, 409, 422}:
                raise OrdersError(
                    exc.code,
                    "A API recusou o pedido. Confira produtos e estoque e prepare uma nova seleção.",
                    definitive=True,
                ) from exc

            if exc.code in {401, 403}:
                # Token interno ausente/errado: o backend recusa antes de criar qualquer coisa.
                logger.error("orders_auth_failure status=%s method=%s path=%s", exc.code, "POST" if body is not None else "GET", path)
                if body is not None:
                    raise OrdersError(502, NOT_REGISTERED, rejected_without_effect=True) from exc

            if exc.code == 404:
                raise OrdersError(
                    404,
                    "Pedido não encontrado na API de pedidos.",
                ) from exc

            if body is not None:
                # Resultado incerto: o pedido pode ter sido criado antes da falha.
                raise OrdersError(
                    502,
                    "A API de pedidos não confirmou o registro do pedido. Repita a confirmação para recuperar o mesmo pedido.",
                ) from exc

            raise OrdersError(
                502,
                "A API de pedidos não conseguiu atender à consulta.",
            ) from exc

        except (URLError, TimeoutError, OSError, HTTPClientError) as exc:
            raise OrdersError(
                503,
                "A API de pedidos está indisponível. Tente novamente.",
            ) from exc

        except (ValueError, UnicodeError) as exc:
            raise OrdersError(
                502,
                "A API de pedidos retornou dados inválidos.",
            ) from exc

    def products(self):
        try:
            data = self._get("/produtos")
            if not isinstance(data, list):
                raise ValueError("Catálogo inválido")
            return [Product.model_validate(item) for item in data]
        except (ValidationError, ValueError) as exc:
            raise OrdersError(502, "A API retornou um catálogo incompatível.") from exc

    def order(self, order_id):
        try:
            return Order.model_validate(self._get(f"/pedidos/{order_id}"))
        except ValidationError as exc:
            raise OrdersError(502, "A API retornou um pedido incompatível.") from exc

    def create_order(self, payload):
        try:
            return Order.model_validate(self._get("/pedidos", payload))
        except ValidationError as exc:
            # Resposta inválida pode ocorrer DEPOIS de a API persistir a compra.
            raise OrdersError(
                502,
                "Resposta de compra inválida. Repita a confirmação para recuperar o mesmo pedido.",
            ) from exc

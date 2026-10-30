import json
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field, ValidationError


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
    def __init__(self, status, detail):
        self.status = status
        self.detail = detail


class OrdersClient:
    def __init__(self, base_url, timeout=5):
        self.base_url, self.timeout = base_url.rstrip("/"), timeout

    def _get(self, path):
        try:
            req = Request(self.base_url + path, headers={"Accept": "application/json"})
            with urlopen(req, timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code == 404:
                raise OrdersError(404, "Pedido não encontrado na API de pedidos.") from exc
            raise OrdersError(502, "A API de pedidos não conseguiu atender à consulta.") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise OrdersError(503, "A API de pedidos está indisponível. Tente novamente.") from exc
        except (ValueError, UnicodeError) as exc:
            raise OrdersError(502, "A API de pedidos retornou dados inválidos.") from exc

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

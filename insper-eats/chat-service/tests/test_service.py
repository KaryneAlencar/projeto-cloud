"""Integração real com PostgreSQL em schema temporário; API de pedidos simulada."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.main import create_app
from app.models import Base, Conversation
from app.orders import Order, OrdersClient, OrdersError, Product


class FakeOrders:
    fail = False

    def products(self):
        if self.fail:
            raise OrdersError(503, "API temporariamente indisponível")
        return [Product(id=10, nome="Brownie", preco=Decimal("8.10"), estoque=3)]

    def order(self, order_id):
        if order_id != 7:
            raise OrdersError(404, "Pedido não encontrado")
        return Order(id=7, status="recebido", total="8.10", itens=[])


@unittest.skipUnless(os.getenv("CHAT_TEST_DATABASE_URL"), "Configure CHAT_TEST_DATABASE_URL para PostgreSQL")
class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.url = os.environ["CHAT_TEST_DATABASE_URL"]
        self.schema = "chat_test_" + uuid4().hex
        self.admin = create_engine(self.url)
        with self.admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.fake = FakeOrders()
        self.engine = self.new_engine()
        self.client = TestClient(create_app(Settings(self.url), engine=self.engine, orders=self.fake))
        self.client.__enter__()

    def new_engine(self):
        return create_engine(self.url, connect_args={"options": f"-csearch_path={self.schema}"})

    def tearDown(self):
        self.client.__exit__(None, None, None)
        with self.admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        self.admin.dispose()

    def conversation(self):
        response = self.client.post("/chat/conversas", json={})
        self.assertEqual(response.status_code, 201)
        return response.json()["id"]

    def send(self, cid, content, mid=None):
        return self.client.post(f"/chat/conversas/{cid}/mensagens", json={"conteudo": content, "mensagem_id": mid or str(uuid4())})

    def test_health_catalog_and_order(self):
        self.assertEqual(self.client.get("/health").json()["banco"], "ok")
        self.assertEqual(self.client.get("/chat/produtos").json()[0]["id"], 10)
        self.assertEqual(self.client.get("/chat/pedidos/7").json()["status"], "recebido")
        self.assertEqual(self.client.get("/chat/pedidos/999").status_code, 404)
        self.assertEqual(self.client.get("/chat/pedidos/0").status_code, 422)
        result = self.send(self.conversation(), "Ver o cardápio").json()
        self.assertIn("8.10", result["mensagens"][-1]["conteudo"])

    def test_persistence_restart_and_idempotency_key(self):
        cid = self.conversation()
        result = self.send(cid, "Quero 2 brownies").json()
        self.assertEqual(result["compra"]["total"], 16.2)
        result = self.send(cid, "Meu nome é Ana").json()
        result = self.send(cid, "Entrega: sala 512").json()
        with Session(self.engine) as session:
            stored = session.get(Conversation, cid)
            self.assertEqual(stored.chave_idempotencia, result["compra"]["id"])
        restarted = TestClient(create_app(Settings(self.url), engine=self.new_engine(), orders=self.fake))
        with restarted:
            restored = restarted.get(f"/chat/conversas/{cid}").json()
        self.assertEqual(restored, result)
        self.assertEqual(self.client.post(f"/chat/conversas/{cid}/confirmar").status_code, 501)

    def test_duplicate_concurrent_message(self):
        cid, mid = self.conversation(), str(uuid4())
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: self.send(cid, "Quero 1 brownie", mid), range(2)))
        self.assertTrue(all(r.status_code == 200 for r in results))
        self.assertEqual(results[0].json(), results[1].json())
        self.assertEqual(len(results[0].json()["mensagens"]), 3)
        self.assertEqual(self.send(cid, "Outro conteúdo", mid).status_code, 409)

    def test_dependency_failure_rollback_and_retry(self):
        cid, mid = self.conversation(), str(uuid4())
        self.fake.fail = True
        self.assertEqual(self.send(cid, "Ver o cardápio", mid).status_code, 503)
        self.assertEqual(len(self.client.get(f"/chat/conversas/{cid}").json()["mensagens"]), 1)
        self.fake.fail = False
        self.assertEqual(self.send(cid, "Ver o cardápio", mid).status_code, 200)

    def test_stock_cancel_and_isolation(self):
        cid, other = self.conversation(), self.conversation()
        self.assertIsNone(self.send(cid, "Quero 4 brownies").json()["compra"])
        self.assertIsNotNone(self.send(cid, "Selecionar 10:2").json()["compra"])
        self.assertIsNone(self.client.get(f"/chat/conversas/{other}").json()["compra"])
        self.assertIsNone(self.send(cid, "cancelar").json()["compra"])
        with Session(self.engine) as session:
            self.assertIsNone(session.get(Conversation, cid).chave_idempotencia)
        self.assertEqual(self.send(cid, "  ").status_code, 422)


class OrdersClientTests(unittest.TestCase):
    def test_timeout(self):
        with patch("app.orders.urlopen", side_effect=TimeoutError):
            with self.assertRaises(OrdersError) as error:
                OrdersClient("http://localhost:8000").products()
        self.assertEqual(error.exception.status, 503)

    def test_malformed_catalog(self):
        with patch.object(OrdersClient, "_get", return_value={"invalid": True}):
            with self.assertRaises(OrdersError) as error:
                OrdersClient("http://localhost:8000").products()
        self.assertEqual(error.exception.status, 502)


if __name__ == "__main__":
    unittest.main()

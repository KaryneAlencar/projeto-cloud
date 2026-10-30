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

    def __init__(self):
        self.created = {}
        self.calls = []
        self.timeout_once = False
        self.reject = False
        self.price = Decimal("8.10")

    def products(self):
        if self.fail:
            raise OrdersError(503, "API temporariamente indisponível")
        return [Product(id=10, nome="Brownie", preco=self.price, estoque=3)]

    def create_order(self, payload):
        self.calls.append(dict(payload))
        if self.reject:
            raise OrdersError(409, "Estoque insuficiente", definitive=True)
        key = payload["chave_idempotencia"]
        if key not in self.created:
            self.created[key] = Order(id=100 + len(self.created), status="recebido", total="16.20",
                                      itens=[{"produto_id": 10, "quantidade": 2, "preco_unitario": "8.10", "subtotal": "16.20"}])
        if self.timeout_once:
            self.timeout_once = False
            raise OrdersError(503, "Resposta perdida após criar pedido")
        return self.created[key]

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
        self.client = TestClient(create_app(Settings(self.url, ai_provider="commands"), engine=self.engine, orders=self.fake))
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
        restarted = TestClient(create_app(Settings(self.url, ai_provider="commands"), engine=self.new_engine(), orders=self.fake))
        with restarted:
            restored = restarted.get(f"/chat/conversas/{cid}").json()
        self.assertEqual(restored, result)
        self.assertEqual(self.client.post(f"/chat/conversas/{cid}/confirmar").status_code, 422)

    def prepared(self):
        cid = self.conversation()
        self.send(cid, "Quero 2 brownies")
        self.send(cid, "Meu nome é Ana")
        result = self.send(cid, "Entrega: sala 512").json()
        return cid, result["compra"]["id"]

    def confirm(self, cid, purchase_id):
        return self.client.post(f"/chat/conversas/{cid}/confirmar", json={"compra_id": purchase_id})

    def test_confirmation_is_explicit_and_concurrent_safe(self):
        cid, purchase_id = self.prepared()
        self.assertEqual(len(self.fake.created), 0)
        self.send(cid, "sim, pode confirmar")
        self.assertEqual(len(self.fake.created), 0)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: self.confirm(cid, purchase_id), range(2)))
        self.assertTrue(all(r.status_code == 200 for r in results))
        self.assertEqual(len(self.fake.created), 1)
        self.assertEqual(len(self.fake.calls), 1)
        self.assertEqual(results[0].json()["compra"]["pedido_id"], results[1].json()["compra"]["pedido_id"])

    def test_lost_response_restart_and_retry_frozen_payload(self):
        cid, purchase_id = self.prepared()
        self.fake.timeout_once = True
        self.assertEqual(self.confirm(cid, purchase_id).status_code, 503)
        self.assertEqual(len(self.fake.created), 1)
        pending = self.client.get(f"/chat/conversas/{cid}").json()
        self.assertEqual(pending["compra"]["status"], "confirmando")
        self.assertEqual(self.send(cid, "cancelar").status_code, 409)
        restarted = TestClient(create_app(Settings(self.url, ai_provider="commands"), engine=self.new_engine(), orders=self.fake))
        with restarted:
            result = restarted.post(f"/chat/conversas/{cid}/confirmar", json={"compra_id": purchase_id})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["compra"]["status"], "confirmado")
        self.assertEqual(len(self.fake.created), 1)
        self.assertEqual(self.fake.calls[0], self.fake.calls[1])

    def test_changed_selection_stale_confirmation_and_missing_data(self):
        cid = self.conversation()
        old = self.send(cid, "Quero 2 brownies").json()["compra"]["id"]
        self.assertEqual(self.confirm(cid, old).status_code, 422)
        self.send(cid, "Meu nome é Ana")
        self.assertEqual(self.confirm(cid, old).status_code, 409)
        self.assertEqual(len(self.fake.calls), 0)

    def test_price_change_requires_second_explicit_confirmation(self):
        cid, purchase_id = self.prepared()
        self.fake.price = Decimal("9.00")
        result = self.confirm(cid, purchase_id)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["compra"]["total"], 18)
        self.assertNotEqual(result.json()["compra"]["id"], purchase_id)
        self.assertEqual(len(self.fake.calls), 0)
        self.assertEqual(self.confirm(cid, purchase_id).status_code, 409)

    def test_rejected_order_can_be_revised(self):
        cid, purchase_id = self.prepared()
        self.fake.reject = True
        self.assertEqual(self.confirm(cid, purchase_id).status_code, 409)
        self.assertEqual(len(self.fake.created), 0)
        self.assertEqual(self.send(cid, "cancelar").status_code, 200)

    def test_duplicate_message_does_not_resurrect_old_purchase(self):
        cid = self.conversation()
        mid = str(uuid4())
        self.send(cid, "Quero 2 brownies", mid)
        self.send(cid, "Meu nome é Ana")
        purchase_id = self.send(cid, "Entrega: sala 512").json()["compra"]["id"]
        self.confirm(cid, purchase_id)
        replay = self.send(cid, "Quero 2 brownies", mid)
        self.assertEqual(replay.json()["compra"]["status"], "confirmado")

    def test_ai_tools_use_real_catalog_and_never_checkout(self):
        import json
        class ScriptedAI:
            def __init__(self):
                self.step = 0
            def generate(inner, items, timeout):
                inner.step += 1
                if inner.step == 1:
                    return [{"type": "function_call", "call_id": "catalog", "name": "listar_produtos", "arguments": "{}"}]
                if inner.step == 2:
                    self.assertIn('Brownie', items[-1]["output"])
                    return [{"type": "function_call", "call_id": "prepare", "name": "preparar_compra", "arguments": json.dumps({"itens": [{"produto_id": 10, "quantidade": 2}], "cliente": "Ana", "local_entrega": "Sala 512"})}]
                return [{"type": "message", "content": [{"type": "output_text", "text": "Confira seu resumo e confirme pelo botão."}]}]
        ai_client = TestClient(create_app(Settings(self.url), engine=self.new_engine(), orders=self.fake, ai=ScriptedAI()))
        with ai_client:
            cid = ai_client.post('/chat/conversas', json={}).json()['id']
            result = ai_client.post(f'/chat/conversas/{cid}/mensagens', json={"conteudo": "Dois brownies pra Ana, sala 512", "mensagem_id": str(uuid4())})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['compra']['total'], 16.2)
            self.assertEqual(len(self.fake.created), 0)

    def test_ai_failure_rolls_back_prepared_state(self):
        import json
        from app.ai import AIError
        class FailingAI:
            step = 0
            def generate(inner, items, timeout):
                inner.step += 1
                if inner.step == 1:
                    return [{"type": "function_call", "call_id": "prepare", "name": "preparar_compra", "arguments": json.dumps({"itens": [{"produto_id": 10, "quantidade": 2}], "cliente": None, "local_entrega": None})}]
                raise AIError("Falha simulada")
        ai_client = TestClient(create_app(Settings(self.url), engine=self.new_engine(), orders=self.fake, ai=FailingAI()))
        with ai_client:
            cid = ai_client.post('/chat/conversas', json={}).json()['id']
            result = ai_client.post(f'/chat/conversas/{cid}/mensagens', json={"conteudo": "Dois brownies", "mensagem_id": str(uuid4())})
            self.assertEqual(result.status_code, 503)
            current = ai_client.get(f'/chat/conversas/{cid}').json()
            self.assertIsNone(current['compra'])
            self.assertEqual(len(current['mensagens']), 1)

    def test_ai_recovers_invalid_fields_and_wrong_product_id_in_same_turn(self):
        import json
        class RecoveringAI:
            step = 0
            def generate(inner, items, timeout):
                inner.step += 1
                step = inner.step
                if step == 1:
                    name, args = 'listar_produtos', {}
                elif step == 2:
                    name, args = 'preparar_compra', {"itens": [{"produto_id": 10}], "cliente": "Ana", "local_entrega": "Sala 512"}
                elif step == 3:
                    failure = json.loads(items[-1]['output'])
                    self.assertEqual(failure['campos'][0]['campo'], 'itens.0.quantidade')
                    self.assertNotIn('input', str(failure))
                    name, args = 'preparar_compra', {"itens": [{"produto_id": 999, "quantidade": 2}], "cliente": "Ana", "local_entrega": "Sala 512"}
                elif step == 4:
                    self.assertIn('Produto ID 999', json.loads(items[-1]['output'])['erro'])
                    name, args = 'preparar_compra', {"itens": [{"produto_id": 10, "quantidade": 2}], "cliente": "Ana", "local_entrega": "Sala 512"}
                else:
                    return [{"type": "message", "content": [{"type": "output_text", "text": "Confira o resumo de R$ 16,20 e confirme pelo botão."}]}]
                return [{"type": "function_call", "call_id": f'call-{step}', "name": name, "arguments": json.dumps(args)}]
        with TestClient(create_app(Settings(self.url), engine=self.new_engine(), orders=self.fake, ai=RecoveringAI())) as client:
            cid = client.post('/chat/conversas', json={}).json()['id']
            result = client.post(f'/chat/conversas/{cid}/mensagens', json={"conteudo": "Quero 2 brownies. Meu nome é Ana, entrega sala 512", "mensagem_id": str(uuid4())})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['compra']['total'], 16.2)
            self.assertEqual(len(self.fake.created), 0)

    def test_gemini_native_loop_prepares_but_does_not_buy(self):
        import io
        import json
        def response(parts):
            return io.BytesIO(json.dumps({"candidates": [{"finishReason": "STOP", "content": {"role": "model", "parts": parts}}]}).encode())
        responses = [
            response([{"functionCall": {"name": "listar_produtos", "args": {}, "id": "catalog"}, "thoughtSignature": "signature-one"}]),
            response([{"functionCall": {"name": "preparar_compra", "args": {"itens": [{"produto_id": 10, "quantidade": 2}], "cliente": "Ana", "local_entrega": "Sala 512"}, "id": "prepare"}}]),
            response([{"text": "Confira o resumo e confirme pelo botão."}]),
        ]
        settings = Settings(self.url, ai_provider="gemini", gemini_api_key="test-key")
        with patch("app.gemini.urlopen", side_effect=responses) as transport:
            with TestClient(create_app(settings, engine=self.new_engine(), orders=self.fake)) as client:
                cid = client.post('/chat/conversas', json={}).json()['id']
                result = client.post(f'/chat/conversas/{cid}/mensagens', json={"conteudo": "Quero dois brownies para Ana, sala 512", "mensagem_id": str(uuid4())})
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json()['compra']['total'], 16.2)
                self.assertEqual(len(self.fake.created), 0)
                self.assertEqual(client.get('/health').json()['modo'], 'gemini')
                self.assertTrue(client.get('/health').json()['ia_configurada'])
        self.assertEqual(transport.call_count, 3)

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
    def test_post_uses_original_idempotency_payload(self):
        import io
        import json
        payload = {"cliente": "Ana", "local_entrega": "Sala 512", "chave_idempotencia": str(uuid4()), "itens": [{"produto_id": 10, "quantidade": 2}]}
        with patch("app.orders.urlopen", return_value=io.BytesIO(b'{"id":7,"status":"recebido","total":"16.20","itens":[]}')) as transport:
            result = OrdersClient("http://localhost:8000").create_order(payload)
        req = transport.call_args.args[0]
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(json.loads(req.data), payload)
        self.assertEqual(result.id, 7)

    def test_openai_request_and_missing_configuration(self):
        import io
        import json
        from app.ai import AIError, OpenAIResponses, TOOLS
        with self.assertRaises(AIError):
            OpenAIResponses(Settings("unused")).generate([], 1)
        output = b'{"status":"completed","output":[{"type":"message","content":[{"type":"output_text","text":"Oi"}]}]}'
        settings = Settings("unused", openai_api_key="test-key", openai_model="test-model")
        with patch("app.ai.urlopen", return_value=io.BytesIO(output)) as transport:
            result = OpenAIResponses(settings).generate([], 1)
        payload = json.loads(transport.call_args.args[0].data)
        self.assertFalse(payload["store"])
        self.assertTrue(all(tool["strict"] for tool in payload["tools"]))
        self.assertNotIn("confirmar", [tool["name"] for tool in TOOLS])
        self.assertEqual(result[0]["type"], "message")

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

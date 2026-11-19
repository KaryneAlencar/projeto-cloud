"""Cadeia de modelos do adaptador Gemini e variações do comando "quero" (sem rede, sem banco)."""
import io
import json
import unittest
from decimal import Decimal
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from unittest.mock import patch

from app.ai import AIError, respond
from app.config import Settings
from app.dialogue import reply
from app.gemini import MODEL_SLICE, SKIP_SIGNATURE, GeminiGenerateContent
from app.orders import Product

CHAIN = ("primary", "second", "third")


def ok(parts):
    return lambda: io.BytesIO(json.dumps({"candidates": [{"finishReason": "STOP", "content": {"role": "model", "parts": parts}}]}).encode())


def http(code):
    def fail():
        raise HTTPError("https://example.test", code, "error", {}, None)
    return fail


def timeout():
    raise TimeoutError("timed out")


class Transport:
    """Substitui urlopen: roteiro por modelo, relógio falso e registro das chamadas."""

    def __init__(self, script, default=http(503)):
        self.script = {model: list(steps) for model, steps in script.items()}
        self.default = default
        self.calls = []      # (modelo, prazo recebido)
        self.payloads = []
        self.now = 0.0

    def __call__(self, request, timeout):
        model = request.full_url.rsplit("/", 1)[1].removesuffix(":generateContent")
        self.calls.append((model, round(timeout, 3)))
        self.payloads.append(json.loads(request.data))
        steps = self.script.get(model)
        step = steps.pop(0) if steps else self.default
        if step is globals()["timeout"]:
            self.now += timeout  # O timeout consome todo o prazo concedido à tentativa.
        return step()

    def sleep(self, seconds):
        self.now += seconds

    def models(self):
        return [model for model, _ in self.calls]


class ModelChainTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings("unused", gemini_api_key="test-only-key", gemini_model=CHAIN[0], gemini_fallback_models=CHAIN[1:])
        self.provider = GeminiGenerateContent(self.settings)

    def run_with(self, transport, call):
        with patch("app.gemini.urlopen", side_effect=transport), patch("app.gemini.time.sleep", side_effect=transport.sleep), \
                patch("app.gemini.time.monotonic", side_effect=lambda: transport.now):
            return call()

    def generate(self, transport, items=None, budget=45):
        return self.run_with(transport, lambda: self.provider.generate(items if items is not None else [{"role": "user", "content": "Oi"}], budget))

    def test_switches_model_on_unavailability(self):
        cases = {
            "503": ([http(503), http(503)], ["primary", "primary", "second"]),  # 1 repetição no mesmo modelo
            "429": ([http(429)], ["primary", "second"]),                       # cota: troca sem repetir
            "404": ([http(404)], ["primary", "second"]),                       # modelo inexistente/aposentado
            "timeout": ([timeout], ["primary", "second"]),
            "transporte": ([lambda: (_ for _ in ()).throw(URLError(ConnectionResetError()))], ["primary", "second"]),
        }
        for name, (failures, expected) in cases.items():
            with self.subTest(name):
                transport = Transport({"primary": failures, "second": [ok([{"text": "Olá"}])]})
                with self.assertLogs("insper-eats-chat", level="INFO") as logs:
                    output = self.generate(transport)
                self.assertEqual(transport.models(), expected)
                self.assertEqual(output[-1]["content"][0]["text"], "Olá")
                self.assertEqual(output[0]["model"], "second")
                self.assertTrue(any("ai_model_used model=second fallback=true" in line for line in logs.output))
                self.assertTrue(any("ai_model_failed model=primary" in line for line in logs.output))
                # Os logs não levam conteúdo da conversa nem a chave.
                self.assertFalse(any("Oi" in line.split("insper-eats-chat:", 1)[1] or "test-only-key" in line for line in logs.output))

    def test_primary_success_is_logged_without_fallback(self):
        transport = Transport({"primary": [ok([{"text": "Olá"}])]})
        with self.assertLogs("insper-eats-chat", level="INFO") as logs:
            self.generate(transport)
        self.assertEqual(transport.models(), ["primary"])
        self.assertTrue(any("ai_model_used model=primary fallback=false" in line for line in logs.output))

    def test_key_permission_and_blocked_content_do_not_switch_model(self):
        blocked = lambda: io.BytesIO(json.dumps({"candidates": [{"finishReason": "SAFETY", "content": {"role": "model", "parts": []}}]}).encode())
        for step, code in ((http(401), "gemini_http_401"), (http(403), "gemini_http_403"), (http(400), "gemini_http_400"), (blocked, "gemini_blocked")):
            with self.subTest(code):
                transport = Transport({"primary": [step]}, default=ok([{"text": "não deveria ser chamado"}]))
                with self.assertRaises(AIError) as captured:
                    self.generate(transport)
                self.assertEqual(captured.exception.code, code)
                self.assertFalse(captured.exception.unavailable)
                self.assertEqual(transport.models(), ["primary"])

    def test_chain_fits_in_round_budget(self):
        # Todos estouram o tempo: 15 s + 15 s + o restante, sem passar dos 45 s da rodada.
        transport = Transport({}, default=timeout)
        with self.assertRaises(AIError) as captured:
            self.generate(transport, budget=45)
        self.assertEqual(transport.calls, [("primary", MODEL_SLICE), ("second", MODEL_SLICE), ("third", 15.0)])
        self.assertEqual(transport.now, 45)
        self.assertEqual(captured.exception.code, "gemini_timeout")
        self.assertTrue(captured.exception.unavailable)
        # Orçamento curto: quem não cabe não é tentado; o último recebe o que sobrou.
        transport = Transport({}, default=timeout)
        with self.assertRaises(AIError):
            self.generate(transport, budget=20)
        self.assertEqual(transport.calls, [("primary", 15.0), ("second", 5.0)])
        # 503 persistente em todos: uma repetição por modelo e erro do primeiro modelo tentado.
        transport = Transport({"second": [http(429)]})
        with self.assertRaises(AIError) as captured:
            self.generate(transport)
        self.assertEqual(transport.models(), ["primary", "primary", "second", "third", "third"])
        self.assertEqual(captured.exception.code, "gemini_http_503")

    def cycle(self, transport):
        """Um respond completo (catálogo -> texto) usando o adaptador real."""
        conversation = SimpleNamespace(id="chain-test", compra=None)
        orders = SimpleNamespace(products=lambda: [])
        return self.run_with(transport, lambda: respond(conversation, [], "Ver o cardápio", orders, self.provider, 120))

    def test_model_that_answered_is_pinned_for_the_rest_of_the_cycle(self):
        call = [{"functionCall": {"name": "listar_produtos", "args": {}, "id": "c1"}, "thoughtSignature": "signature-of-second"}]
        transport = Transport({"primary": [http(429)], "second": [ok(call), ok([{"text": "Cardápio vazio."}])]},
                              default=ok([{"text": "o principal não deveria voltar no meio do ciclo"}]))
        self.assertEqual(self.cycle(transport), "Cardápio vazio.")
        # Rodada 1: principal fora, reserva responde. Rodada 2: direto na reserva, sem voltar ao principal.
        self.assertEqual(transport.models(), ["primary", "second", "second"])
        # O mesmo modelo recebe de volta a própria assinatura, intacta.
        self.assertEqual(transport.payloads[-1]["contents"][-2], {"role": "model", "parts": call})

    def test_pinned_model_failing_mid_cycle_switches_with_neutral_signature(self):
        call = [{"functionCall": {"name": "listar_produtos", "args": {}, "id": "c1"}, "thoughtSignature": "signature-of-primary"},
                {"text": "nota", "thoughtSignature": "text-signature"}]
        transport = Transport({"primary": [ok(call), http(429)], "second": [ok([{"text": "Cardápio vazio."}])]})
        self.assertEqual(self.cycle(transport), "Cardápio vazio.")
        self.assertEqual(transport.models(), ["primary", "primary", "second"])
        # Tentativa no modelo fixado: assinatura original. No outro modelo: valor neutro documentado.
        self.assertEqual(transport.payloads[1]["contents"][-2]["parts"], call)
        foreign = transport.payloads[2]["contents"][-2]["parts"]
        self.assertEqual(foreign[0]["thoughtSignature"], SKIP_SIGNATURE)
        self.assertEqual(foreign[0]["functionCall"], call[0]["functionCall"])
        self.assertNotIn("thoughtSignature", foreign[1])

    def test_history_rejected_by_other_model_counts_as_unavailable(self):
        call = [{"functionCall": {"name": "listar_produtos", "args": {}, "id": "c1"}}]
        # O modelo fixado cai e as reservas recusam (400) o histórico iniciado por ele.
        transport = Transport({"primary": [ok(call), http(429)]}, default=http(400))
        with self.assertRaises(AIError) as captured:
            self.cycle(transport)
        self.assertEqual(transport.models(), ["primary", "primary", "second", "third"])
        self.assertEqual(captured.exception.code, "gemini_http_429")
        self.assertTrue(captured.exception.unavailable)


class WantCommandTests(unittest.TestCase):
    def products(self, *names):
        catalog = [Product(id=index, nome=name, preco=Decimal("5.00"), estoque=20) for index, name in enumerate(names, 1)]
        return SimpleNamespace(products=lambda: catalog)

    def want(self, text, *names):
        conversation = SimpleNamespace(compra=None, chave_idempotencia=None, estado="aberta")
        answer = reply(conversation, text, self.products(*names))
        if conversation.compra is None:
            return answer
        item = conversation.compra["itens"][0]
        return item["nome"], item["quantidade"]

    def test_articles_number_words_and_plurals(self):
        catalog = ("Brownie", "Café", "Pão de Queijo", "Suco de Laranja")
        for text, expected in {
            "Quero 2 brownies": ("Brownie", 2),
            "quero um brownie": ("Brownie", 1),
            "Quero uma brownie.": ("Brownie", 1),
            "Quero dois cafés": ("Café", 2),
            "quero 3 cafe, por favor!": ("Café", 3),
            "Quero 2 dos brownies": ("Brownie", 2),
            "Quero três pães de queijo": ("Pão de Queijo", 3),
            "quero 4 unidades de suco de laranja": ("Suco de Laranja", 4),
            "Quero 2 sucos": ("Suco de Laranja", 2),  # única opção com "suco" no catálogo
        }.items():
            with self.subTest(text):
                self.assertEqual(self.want(text, *catalog), expected)

    def test_ambiguous_or_unknown_names_are_not_guessed(self):
        # Dois sucos: "sucos" não escolhe nenhum. Nome idêntico repetido também não.
        self.assertIn("Não identifiquei", self.want("Quero 2 sucos", "Suco de Laranja", "Suco de Uva"))
        self.assertIn("Não identifiquei", self.want("Quero 2 brownies", "Brownie", "Brownie"))
        self.assertIn("Não identifiquei", self.want("Quero 2 pizzas", "Brownie", "Café"))
        self.assertIn("Não identifiquei", self.want("Quero 2 brownies e 1 café", "Brownie", "Café"))
        # Nome exato vence a correspondência parcial.
        self.assertEqual(self.want("Quero 2 brownies", "Brownie", "Brownie de Chocolate"), ("Brownie", 2))
        # Sem quantidade não há suposição.
        self.assertIn("quantidade", self.want("Quero brownie", "Brownie"))
        # Estoque continua valendo.
        self.assertIn("quantidade solicitada", self.want("Quero 21 brownies", "Brownie"))

    def test_default_message_fits_script_and_fallback_use(self):
        answer = self.want("bom dia", "Brownie")
        self.assertTrue(answer.startswith("Posso mostrar o cardápio"))
        self.assertNotIn("IA", answer)


if __name__ == "__main__":
    unittest.main()

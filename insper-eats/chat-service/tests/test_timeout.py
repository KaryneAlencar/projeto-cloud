import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.ai import AIError, respond
from app.config import Settings


class TimeoutTests(unittest.TestCase):
    def test_configuration_accepts_120_and_rejects_above(self):
        env = {"CHAT_DATABASE_URL": "postgresql+psycopg://unused", "AI_TIMEOUT": "120"}
        with patch.dict(os.environ, env, clear=True), patch("app.config.load_dotenv"):
            self.assertEqual(Settings.from_env().ai_timeout, 120)
            os.environ["AI_TIMEOUT"] = "121"
            with self.assertRaises(RuntimeError):
                Settings.from_env()

    def test_120_seconds_is_shared_across_tool_rounds(self):
        timeouts = []
        class Provider:
            def generate(self, items, timeout):
                timeouts.append(timeout)
                if len(timeouts) == 1:
                    return [{"type": "function_call", "name": "listar_produtos", "arguments": "{}", "call_id": "catalog"}]
                return [{"type": "message", "content": [{"type": "output_text", "text": "Catálogo consultado."}]}]
        conversation = SimpleNamespace(id="test-timeout", compra=None)
        orders = SimpleNamespace(products=lambda: [])
        # Início, primeira rodada, retorno aos 40s, segunda rodada, retorno aos 90s.
        with patch("app.ai.time.monotonic", side_effect=[0, 0, 40, 40, 90]):
            result = respond(conversation, [], "Ver catálogo", orders, Provider(), 120)
        self.assertEqual(timeouts, [120, 80])
        self.assertEqual(result, "Catálogo consultado.")

    def test_late_model_response_is_not_accepted(self):
        provider = SimpleNamespace(generate=lambda items, timeout: [{"type": "message", "content": [{"type": "output_text", "text": "Resposta tardia"}]}])
        with patch("app.ai.time.monotonic", side_effect=[0, 0, 121]):
            with self.assertRaisesRegex(AIError, "120 segundos"):
                respond(SimpleNamespace(id="test-late", compra=None), [], "Oi", None, provider, 120)


if __name__ == "__main__":
    unittest.main()

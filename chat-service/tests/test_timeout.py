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

    def test_unknown_provider_is_rejected_with_clear_message(self):
        self.assertEqual(Settings("unused").gemini_model, "gemini-flash-lite-latest")
        for provider in ("openai", "outro"):
            env = {"CHAT_DATABASE_URL": "postgresql+psycopg://unused", "AI_PROVIDER": provider}
            with patch.dict(os.environ, env, clear=True), patch("app.config.load_dotenv"):
                with self.assertRaisesRegex(RuntimeError, "AI_PROVIDER deve ser gemini ou commands"):
                    Settings.from_env()

    def test_model_chain_and_script_fallback_configuration(self):
        defaults = Settings("unused")
        self.assertEqual(defaults.gemini_models, ("gemini-flash-lite-latest", "gemini-3.5-flash-lite", "gemini-3.8-flash"))
        self.assertTrue(defaults.ai_fallback_commands)
        base = {"CHAT_DATABASE_URL": "postgresql+psycopg://unused"}
        with patch.dict(os.environ, base, clear=True), patch("app.config.load_dotenv"):
            self.assertEqual(Settings.from_env().gemini_models, defaults.gemini_models)
            self.assertTrue(Settings.from_env().ai_fallback_commands)
            # Repetidos e o prefixo models/ não geram tentativas duplicadas.
            os.environ.update(GEMINI_MODEL="models/a", GEMINI_FALLBACK_MODELS=" b , a,, c ", AI_FALLBACK_COMMANDS="False")
            settings = Settings.from_env()
            self.assertEqual(settings.gemini_models, ("a", "b", "c"))
            self.assertFalse(settings.ai_fallback_commands)
            # Vazio = sem reservas, só o principal.
            os.environ["GEMINI_FALLBACK_MODELS"] = ""
            self.assertEqual(Settings.from_env().gemini_models, ("a",))
            os.environ["AI_FALLBACK_COMMANDS"] = "talvez"
            with self.assertRaisesRegex(RuntimeError, "AI_FALLBACK_COMMANDS"):
                Settings.from_env()

    def rounds(self, clock):
        timeouts = []
        class Provider:
            def generate(self, items, timeout):
                timeouts.append(timeout)
                if len(timeouts) == 1:
                    return [{"type": "function_call", "name": "listar_produtos", "arguments": "{}", "call_id": "catalog"}]
                return [{"type": "message", "content": [{"type": "output_text", "text": "Catálogo consultado."}]}]
        conversation = SimpleNamespace(id="test-timeout", compra=None)
        orders = SimpleNamespace(products=lambda: [])
        with patch("app.ai.time.monotonic", side_effect=clock):
            result = respond(conversation, [], "Ver catálogo", orders, Provider(), 120)
        self.assertEqual(result, "Catálogo consultado.")
        return timeouts

    def test_120_seconds_is_shared_and_each_round_is_capped_at_45(self):
        # Início, primeira rodada, retorno aos 40s, segunda rodada, retorno aos 90s.
        self.assertEqual(self.rounds([0, 0, 40, 40, 90]), [45, 45])
        # Com menos de 45 s de orçamento, a rodada recebe apenas o restante.
        self.assertEqual(self.rounds([0, 0, 44, 100, 110]), [45, 20])

    def test_pool_is_explicit_and_configurable_by_environment(self):
        from app.database import connect_database
        url = "postgresql+psycopg://user:pass@127.0.0.1:1/unused"  # Engine preguiçoso: não conecta.
        with patch.dict(os.environ, {}, clear=True):
            engine, _ = connect_database(url)
            self.assertEqual((engine.pool.size(), engine.pool._max_overflow, engine.pool._timeout), (5, 10, 5))
        with patch.dict(os.environ, {"DB_POOL_SIZE": "2", "DB_MAX_OVERFLOW": "0"}, clear=True):
            engine, _ = connect_database(url)
            self.assertEqual((engine.pool.size(), engine.pool._max_overflow), (2, 0))
        with patch.dict(os.environ, {"DB_POOL_SIZE": "0"}, clear=True):
            with self.assertRaises(RuntimeError):
                connect_database(url)

    def test_late_model_response_is_not_accepted(self):
        provider = SimpleNamespace(generate=lambda items, timeout: [{"type": "message", "content": [{"type": "output_text", "text": "Resposta tardia"}]}])
        with patch("app.ai.time.monotonic", side_effect=[0, 0, 121]):
            with self.assertRaisesRegex(AIError, "120 segundos"):
                respond(SimpleNamespace(id="test-late", compra=None), [], "Oi", None, provider, 120)


if __name__ == "__main__":
    unittest.main()

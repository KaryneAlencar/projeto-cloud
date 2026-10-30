import io
import json
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from app.ai import AIError
from app.config import Settings
from app.gemini import GeminiGenerateContent


def response(parts, finish="STOP"):
    return io.BytesIO(json.dumps({"candidates": [{"finishReason": finish, "content": {"role": "model", "parts": parts}}]}).encode())


class GeminiTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings("unused", gemini_api_key="test-only-key")
        self.provider = GeminiGenerateContent(self.settings)

    def test_native_tools_signatures_and_parallel_results(self):
        parts = [
            {"functionCall": {"name": "listar_produtos", "args": {}, "id": "first"}, "thoughtSignature": "opaque-signature"},
            {"functionCall": {"name": "consultar_pedido", "args": {"pedido_id": 7}, "id": "second"}},
        ]
        items = [{"role": "developer", "content": "Estado: null"}, {"role": "user", "content": "Ver cardápio e pedido 7"}]
        with patch("app.gemini.urlopen", return_value=response(parts)) as transport:
            output = self.provider.generate(items, 10)
        req = transport.call_args.args[0]
        self.assertNotIn("test-only-key", req.full_url)
        self.assertEqual(req.get_header("X-goog-api-key"), "test-only-key")
        payload = json.loads(req.data)
        self.assertIn("Estado: null", payload["systemInstruction"]["parts"][0]["text"])
        self.assertTrue(all("parametersJsonSchema" in t for t in payload["tools"][0]["functionDeclarations"]))
        items.extend(output)
        calls = [item for item in output if item["type"] == "function_call"]
        for call in calls:
            items.append({"type": "function_call_output", "call_id": call["call_id"], "output": json.dumps([{"id": 10}])})
        with patch("app.gemini.urlopen", return_value=response([{"text": "Catálogo consultado"}])) as transport:
            final = self.provider.generate(items, 10)
        payload = json.loads(transport.call_args.args[0].data)
        self.assertEqual(payload["contents"][-2], {"role": "model", "parts": parts})
        results = payload["contents"][-1]["parts"]
        self.assertEqual([r["functionResponse"]["id"] for r in results], ["first", "second"])
        self.assertEqual(final[-1]["content"][0]["text"], "Catálogo consultado")

    def test_quota_and_missing_key(self):
        self.assertFalse(Settings("unused").ai_configured)
        self.assertTrue(self.settings.ai_configured)
        with self.assertRaisesRegex(AIError, "GEMINI_API_KEY"):
            GeminiGenerateContent(Settings("unused")).generate([], 10)
        with patch("app.gemini.urlopen", side_effect=HTTPError("https://example.test", 429, "quota", {}, None)):
            with self.assertRaisesRegex(AIError, "Limite de uso"):
                self.provider.generate([], 10)

    def test_blocked_response_and_thought_not_displayed(self):
        with patch("app.gemini.urlopen", return_value=response([{"text": "internal", "thought": True}, {"text": "Olá"}])):
            output = self.provider.generate([], 10)
        self.assertEqual(output[-1]["content"][0]["text"], "Olá")
        with patch("app.gemini.urlopen", return_value=response([], finish="SAFETY")):
            with self.assertRaises(AIError):
                self.provider.generate([], 10)

    def test_idless_function_call(self):
        with patch("app.gemini.urlopen", return_value=response([{"functionCall": {"name": "listar_produtos", "args": {}}}])):
            output = self.provider.generate([], 10)
        call = output[-1]
        payload = self.provider.payload(output + [{"type": "function_call_output", "call_id": call["call_id"], "output": "[]"}])
        self.assertNotIn("id", payload["contents"][-1]["parts"][0]["functionResponse"])


if __name__ == "__main__":
    unittest.main()

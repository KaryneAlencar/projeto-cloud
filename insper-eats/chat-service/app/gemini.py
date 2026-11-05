"""Adapter Gemini REST: preserva contents nativos e thoughtSignature entre ferramentas."""
import json
import logging
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import uuid4

from .ai import AIError, INSTRUCTIONS, TOOLS

logger = logging.getLogger("insper-eats-chat")


class GeminiGenerateContent:
    def __init__(self, settings):
        self.settings = settings

    def request_with_retry(self, request, timeout):
        deadline = time.monotonic() + timeout
        for attempt in range(3):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Prazo da chamada esgotado")
            try:
                with urlopen(request, timeout=remaining) as response:
                    return json.load(response)
            except HTTPError as exc:
                if exc.code not in {500, 502, 503, 504} or attempt == 2:
                    raise
                delay = 2 ** attempt
                if deadline - time.monotonic() <= delay:
                    raise
                logger.warning("gemini_retry status=%s next_attempt=%s wait_seconds=%s", exc.code, attempt + 2, delay)
                exc.close()
                time.sleep(delay)

    def payload(self, items):
        contents, context, calls = [], [], {}

        def append_part(role, part):
            if contents and contents[-1]["role"] == role:
                contents[-1]["parts"].append(part)
            else:
                contents.append({"role": role, "parts": [part]})

        for item in items:
            kind = item.get("type")
            if item.get("role") == "developer":
                context.append(item["content"])
            elif kind == "gemini_content":
                # Não reconstrói/mescla a resposta do modelo: preserva assinaturas e ordem.
                contents.append(item["content"])
            elif kind == "function_call":
                calls[item["call_id"]] = item
            elif kind == "function_call_output":
                call = calls[item["call_id"]]
                response = {"name": call["name"], "response": {"result": json.loads(item["output"])}}
                if call.get("gemini_id"):
                    response["id"] = call["gemini_id"]
                append_part("user", {"functionResponse": response})
            elif item.get("role") in {"user", "assistant"}:
                append_part("user" if item["role"] == "user" else "model", {"text": item["content"]})

        return {
            "systemInstruction": {"parts": [{"text": INSTRUCTIONS + "\n" + "\n".join(context)}]},
            "contents": contents,
            "tools": [{"functionDeclarations": [
                {"name": t["name"], "description": t["description"], "parametersJsonSchema": t["parameters"]}
                for t in TOOLS
            ]}],
            "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
            "generationConfig": {"maxOutputTokens": 4096},
        }

    def generate(self, items, timeout):
        if not self.settings.gemini_api_key or not self.settings.gemini_model:
            raise AIError("Configure GEMINI_API_KEY e GEMINI_MODEL no .env do Chat Service.")
        model = quote(self.settings.gemini_model.removeprefix("models/"), safe="")
        req = Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                      data=json.dumps(self.payload(items)).encode(),
                      headers={"Content-Type": "application/json", "x-goog-api-key": self.settings.gemini_api_key})
        try:
            data = self.request_with_retry(req, timeout)
        except HTTPError as exc:
            if exc.code in {500, 502, 503, 504}:
                raise AIError("O Gemini está temporariamente indisponível, mesmo após novas tentativas. Tente novamente em instantes.", f"gemini_http_{exc.code}") from exc
            if exc.code == 429:
                raise AIError("Limite de uso do Gemini atingido. Aguarde e confira a cota no Google AI Studio.", "gemini_http_429") from exc
            if exc.code in {401, 403}:
                raise AIError("O Gemini recusou a chave ou o acesso. Confira GEMINI_API_KEY e as permissões do projeto.", f"gemini_http_{exc.code}") from exc
            if exc.code == 404:
                raise AIError("Modelo Gemini não disponível. Confira GEMINI_MODEL no Google AI Studio.", "gemini_http_404") from exc
            raise AIError("O Gemini não conseguiu atender. Confira o modelo/configuração ou tente novamente.", f"gemini_http_{exc.code}") from exc
        except TimeoutError as exc:
            raise AIError("O Gemini excedeu o tempo de espera desta etapa. Tente novamente.", "gemini_timeout") from exc
        except (URLError, OSError, ValueError) as exc:
            raise AIError("O Gemini está indisponível ou retornou dados inválidos. Tente novamente.", "gemini_transport_error") from exc

        try:
            candidate = data["candidates"][0]
            finish = candidate.get("finishReason")
            if finish != "STOP":
                if finish == "MAX_TOKENS":
                    raise AIError("O Gemini atingiu o limite de geração da resposta. Tente uma consulta mais específica.", "gemini_max_tokens")
                if finish == "MALFORMED_FUNCTION_CALL":
                    raise AIError("O Gemini retornou uma chamada de ferramenta inválida. Tente novamente.", "gemini_malformed_function_call")
                if finish in {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"}:
                    raise AIError("O Gemini bloqueou a resposta. Reformule a mensagem e tente novamente.", "gemini_blocked")
                raise AIError("O Gemini interrompeu a resposta. Tente novamente.", "gemini_incomplete")
            content = candidate["content"]
            if content.get("role") != "model" or not isinstance(content.get("parts"), list):
                raise ValueError("Content inválido")
            output = [{"type": "gemini_content", "content": content}]
            texts = []
            for part in content["parts"]:
                if "functionCall" in part:
                    call = part["functionCall"]
                    if not isinstance(call.get("name"), str) or not isinstance(call.get("args", {}), dict):
                        raise ValueError("Ferramenta inválida")
                    output.append({"type": "function_call", "name": call["name"], "arguments": json.dumps(call.get("args", {})),
                                   "call_id": str(uuid4()), "gemini_id": call.get("id")})
                elif isinstance(part.get("text"), str) and not part.get("thought"):
                    texts.append(part["text"])
            if texts:
                output.append({"type": "message", "content": [{"type": "output_text", "text": "\n".join(texts)}]})
            return output
        except (KeyError, IndexError, TypeError, AttributeError, ValueError) as exc:
            raise AIError("O Gemini retornou uma resposta inesperada. Tente novamente.") from exc

"""Adapter Gemini REST: preserva contents nativos e thoughtSignature entre ferramentas."""
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import uuid4

from .ai import AIError, INSTRUCTIONS, TOOLS


class GeminiGenerateContent:
    def __init__(self, settings):
        self.settings = settings

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
            with urlopen(req, timeout=timeout) as response:
                data = json.load(response)
        except HTTPError as exc:
            if exc.code == 429:
                raise AIError("Limite de uso do Gemini atingido. Aguarde e confira a cota no Google AI Studio.") from exc
            if exc.code in {401, 403}:
                raise AIError("O Gemini recusou a chave ou o acesso. Confira GEMINI_API_KEY e as permissões do projeto.") from exc
            if exc.code == 404:
                raise AIError("Modelo Gemini não disponível. Confira GEMINI_MODEL no Google AI Studio.") from exc
            raise AIError("O Gemini não conseguiu atender. Confira o modelo/configuração ou tente novamente.") from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise AIError("O Gemini está indisponível ou retornou dados inválidos. Tente novamente.") from exc

        try:
            candidate = data["candidates"][0]
            if candidate.get("finishReason") != "STOP":
                raise AIError("O Gemini interrompeu ou bloqueou a resposta. Reformule a mensagem e tente novamente.")
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

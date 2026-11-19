"""Adapter Gemini REST: preserva contents nativos e thoughtSignature entre ferramentas.
Cada rodada percorre uma cadeia de modelos (principal + reservas) dentro do mesmo prazo."""
import copy
import json
import logging
import time
from http.client import HTTPException as HTTPClientError
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import uuid4

from .ai import AIError, INSTRUCTIONS, TOOLS

logger = logging.getLogger("insper-eats-chat")

# Chave, modelo e configuração são assunto do operador: o detalhe fica só no log.
UNAVAILABLE = "O assistente está indisponível no momento. Tente novamente em instantes."

RETRYABLE = {500, 502, 503, 504}
# Tentativas no MESMO modelo em 5xx (1 repetição, pausa de 1 s): o tempo restante é do próximo.
ATTEMPTS_PER_MODEL = 2
# Fatia de um modelo que não é o último da cadeia (tentativa + repetição + pausa).
# Com a rodada de 45 s (app/ai.py) cabem três modelos: 15 + 15 + restante.
MODEL_SLICE = 15.0
# O Gemini valida a thoughtSignature da primeira functionCall de cada passo do turno atual
# (HTTP 400 se faltar) e a documentação só garante a assinatura devolvida ao MESMO modelo.
# Para um histórico vindo de outro modelo, o valor documentado abaixo dispensa a validação:
# https://ai.google.dev/gemini-api/docs/thought-signatures
SKIP_SIGNATURE = "skip_thought_signature_validator"


def foreign_content(content):
    """Content gerado por OUTRO modelo: troca as assinaturas das chamadas pelo valor neutro."""
    content = copy.deepcopy(content)
    first_call = True
    for part in content.get("parts", []):
        if not isinstance(part, dict):
            continue
        if "functionCall" in part:
            if first_call or "thoughtSignature" in part:
                part["thoughtSignature"] = SKIP_SIGNATURE
            first_call = False
        else:
            part.pop("thoughtSignature", None)
    return content


class GeminiGenerateContent:
    def __init__(self, settings):
        self.settings = settings

    def request_with_retry(self, request, timeout):
        deadline = time.monotonic() + timeout
        for attempt in range(ATTEMPTS_PER_MODEL):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Prazo da chamada esgotado")
            try:
                with urlopen(request, timeout=remaining) as response:
                    return json.load(response)
            except HTTPError as exc:
                if exc.code not in RETRYABLE or attempt == ATTEMPTS_PER_MODEL - 1:
                    raise
                delay = 2 ** attempt
                if deadline - time.monotonic() <= delay:
                    raise
                logger.warning("gemini_retry status=%s next_attempt=%s wait_seconds=%s", exc.code, attempt + 2, delay)
                exc.close()
                time.sleep(delay)

    def payload(self, items, model=None):
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
                # Exceção: content de outro modelo (troca no meio do ciclo), ver SKIP_SIGNATURE.
                if model and item.get("model") and item["model"] != model:
                    contents.append(foreign_content(item["content"]))
                else:
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
        models = self.settings.gemini_models
        if not self.settings.gemini_api_key or not models:
            raise AIError(UNAVAILABLE, "gemini_not_configured", internal="Configure GEMINI_API_KEY e GEMINI_MODEL no .env do Chat Service.")
        # Modelo fixado: o que já respondeu neste ciclo (itens gemini_content só existem dentro
        # de um respond). Ele continua sendo o primeiro; os demais só entram se ele falhar.
        pinned = next((item["model"] for item in reversed(items)
                       if item.get("type") == "gemini_content" and item.get("model")), None)
        chain = ([pinned] if pinned else []) + [name for name in models if name != pinned]
        deadline = time.monotonic() + timeout
        first_error = None
        for index, model in enumerate(chain):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            budget = remaining if index == len(chain) - 1 else min(remaining, MODEL_SLICE)
            try:
                output = self.generate_with(model, items, budget)
            except AIError as exc:
                # Recusa (400) de um histórico iniciado por outro modelo: este modelo não pode
                # continuar o ciclo, o que não é erro de configuração; segue para o próximo.
                rejected_history = pinned is not None and model != pinned and exc.code == "gemini_http_400"
                if not exc.unavailable and not rejected_history:
                    raise
                logger.warning("ai_model_failed model=%s code=%s next=%s", model, exc.code,
                               chain[index + 1] if index + 1 < len(chain) else "none")
                first_error = first_error or exc
                continue
            logger.info("ai_model_used model=%s fallback=%s", model, "false" if model == models[0] else "true")
            return output
        if first_error is None:
            raise AIError("O Gemini excedeu o tempo de espera desta etapa. Tente novamente.", "gemini_timeout", unavailable=True)
        # O erro do primeiro modelo tentado é sempre de indisponibilidade.
        raise first_error

    def generate_with(self, model, items, timeout):
        req = Request(f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model, safe='')}:generateContent",
                      data=json.dumps(self.payload(items, model)).encode(),
                      headers={"Content-Type": "application/json", "x-goog-api-key": self.settings.gemini_api_key})
        try:
            data = self.request_with_retry(req, timeout)
        except HTTPError as exc:
            if exc.code in RETRYABLE:
                raise AIError("O Gemini está temporariamente indisponível, mesmo após novas tentativas. Tente novamente em instantes.", f"gemini_http_{exc.code}", unavailable=True) from exc
            if exc.code == 429:
                raise AIError("Limite de uso do assistente atingido. Aguarde alguns instantes e tente novamente.", "gemini_http_429", internal="Cota do Gemini atingida. Confira a cota no Google AI Studio.", unavailable=True) from exc
            if exc.code in {401, 403}:
                raise AIError(UNAVAILABLE, f"gemini_http_{exc.code}", internal="O Gemini recusou a chave ou o acesso. Confira GEMINI_API_KEY e as permissões do projeto.") from exc
            if exc.code == 404:
                raise AIError(UNAVAILABLE, "gemini_http_404", internal="Modelo Gemini não disponível. Confira GEMINI_MODEL e GEMINI_FALLBACK_MODELS no Google AI Studio.", unavailable=True) from exc
            raise AIError(UNAVAILABLE, f"gemini_http_{exc.code}", internal="O Gemini não conseguiu atender. Confira o modelo/configuração.") from exc
        except TimeoutError as exc:
            raise AIError("O Gemini excedeu o tempo de espera desta etapa. Tente novamente.", "gemini_timeout", unavailable=True) from exc
        except (URLError, OSError, ValueError, HTTPClientError) as exc:
            # Timeout na conexão chega embrulhado em URLError; no corpo, como TimeoutError direto.
            if isinstance(getattr(exc, "reason", None), TimeoutError):
                raise AIError("O Gemini excedeu o tempo de espera desta etapa. Tente novamente.", "gemini_timeout", unavailable=True) from exc
            raise AIError("O Gemini está indisponível ou retornou dados inválidos. Tente novamente.", "gemini_transport_error", unavailable=True) from exc

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
            # model: qual modelo gerou este content (fixa o modelo no restante do ciclo).
            output = [{"type": "gemini_content", "content": content, "model": model}]
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

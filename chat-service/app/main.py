import logging
from contextlib import asynccontextmanager
from uuid import UUID, uuid4
import time

from fastapi import FastAPI, HTTPException, Path, Request, Response
from starlette.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError, TimeoutError as PoolTimeoutError

from .config import Settings
from .logging_setup import configure_logging, request_id_context
from .ai import AIError, respond
from .gemini import GeminiGenerateContent
from .checkout import confirm_purchase
from .database import connect_database, connect_health
from .dialogue import reply
from .models import Base, Conversation, ConversationAccess, Message, MessageRequest, BrowserSession, now
from .orders import OrdersClient, OrdersError
from .presentation import customer_message
from .order_history import (BROWSER_SCOPE, CONVERSATION_SCOPE, OwnedOrdersClient, conversation_order_ids,
                            fetch_orders, list_browser_orders, owned_order_ids)
from .security import owner_context, start_session, verify_request

logger = logging.getLogger("insper-eats-chat")

DATABASE_UNAVAILABLE = "O banco de conversas está indisponível. Tente novamente em instantes."
BUSY = "Ainda estou respondendo à mensagem anterior. Aguarde um instante."


class IncomingMessage(BaseModel):
    conteudo: str = Field(min_length=1, max_length=2000)
    mensagem_id: UUID

    @field_validator("conteudo")
    @classmethod
    def no_control_characters(cls, value):
        # NUL não é aceito pelo PostgreSQL (o INSERT falharia depois de a IA ser chamada);
        # os demais caracteres de controle não são texto. Quebra de linha e tabulação passam.
        if any((ord(c) < 32 and c not in "\n\r\t") or 127 <= ord(c) < 160 for c in value):
            raise ValueError("A mensagem contém caracteres de controle inválidos.")
        return value


class Confirmation(BaseModel):
    compra_id: UUID


def snapshot(session, conversation):
    messages = session.scalars(select(Message).where(Message.conversa_id == conversation.id).order_by(Message.sequencia)).all()
    return {
        "id": conversation.id,
        "confirmacao_habilitada": True,
        "mensagens": [{"id": m.id, "papel": m.papel, "conteudo": customer_message(m.conteudo) if m.papel == "assistente" else m.conteudo, "criado_em": m.criada_em.isoformat()} for m in messages],
        "compra": conversation.compra,
    }


def create_app(settings=None, *, engine=None, orders=None, ai=None):
    configure_logging()
    settings = settings or Settings.from_env()
    database, sessions = connect_database(settings.database_url)
    if engine is not None:
        database.dispose()
        from sqlalchemy.orm import sessionmaker
        database, sessions = engine, sessionmaker(engine, expire_on_commit=False)
    client = orders or OrdersClient(settings.orders_api_url, settings.orders_timeout, settings.orders_internal_token)
    provider = ai or GeminiGenerateContent(settings)  # Não é chamado no modo commands.
    # /health usa conexão própria, fora do pool: responde mesmo com o pool ocupado.
    health_database = connect_health(settings.database_url)

    @asynccontextmanager
    async def lifespan(_app):
        # Metadados exclusivos do chat: não importa modelos do backend da Pessoa 1.
        with database.begin() as connection:
            # Serializa criação aditiva das tabelas entre workers/tasks.
            connection.execute(text("SELECT pg_advisory_xact_lock(18742011)"))
            Base.metadata.create_all(connection)
        yield
        database.dispose()
        health_database.dispose()

    app = FastAPI(title="Insper Eats Chat Service", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        try:
            request_id = str(UUID(request.headers.get("x-request-id", "")))
        except ValueError:
            request_id = str(uuid4())
        trace = request_id_context.set(request_id)
        owner_token = None
        started = time.monotonic()
        try:
            if request.url.path.startswith("/chat/") and request.url.path != "/chat/sessao":
                try:
                    owner = await run_in_threadpool(verify_request, request, sessions, settings)
                except HTTPException as exc:
                    response = JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
                    response.headers["X-Request-ID"] = request_id
                    response.headers["Cache-Control"] = "no-store"
                    return response
                except (OperationalError, PoolTimeoutError) as exc:
                    logger.error("database_unavailable error=%s", type(exc).__name__)
                    response = JSONResponse(status_code=503, content={"detail": DATABASE_UNAVAILABLE})
                    response.headers["X-Request-ID"] = request_id
                    return response
                owner_token = owner_context.set(owner)
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            if request.url.path.startswith("/chat/"):
                response.headers["Cache-Control"] = "no-store"
            logger.info("http_request method=%s path=%s status=%s elapsed_ms=%.1f", request.method, request.url.path, response.status_code, (time.monotonic() - started) * 1000)
            return response
        finally:
            if owner_token is not None:
                owner_context.reset(owner_token)
            request_id_context.reset(trace)

    @app.post("/chat/sessao")
    def browser_session(request: Request, response: Response):
        return start_session(request, response, sessions, settings)

    @app.post("/chat/sessao/encerrar", status_code=204)
    def end_session(response: Response):
        with sessions.begin() as session:
            browser = session.get(BrowserSession, owner_context.get())
            browser.expira_em = now()
        response.delete_cookie(settings.cookie_name, path="/", secure=settings.cookie_secure, httponly=True, samesite="lax")

    @app.exception_handler(OrdersError)
    async def orders_failure(_request: Request, exc: OrdersError):
        logger.warning("orders_dependency_failure status=%s", exc.status)
        return JSONResponse(status_code=exc.status, content={"detail": exc.detail})

    @app.exception_handler(AIError)
    async def ai_failure(_request: Request, exc: AIError):
        # O detalhe interno (chave/modelo/configuração) fica só no log; o cliente recebe str(exc).
        logger.warning("ai_dependency_failure code=%s reason=%s", exc.code, exc.internal or str(exc))
        return JSONResponse(status_code=503, content={"detail": str(exc), "code": exc.code})

    async def database_failure(_request: Request, exc: Exception):
        # Conexão/pool: sem detalhes do driver para o cliente.
        logger.error("database_unavailable error=%s", type(exc).__name__)
        return JSONResponse(status_code=503, content={"detail": DATABASE_UNAVAILABLE})

    app.add_exception_handler(OperationalError, database_failure)
    app.add_exception_handler(PoolTimeoutError, database_failure)

    def find_conversation(session, conversation_id, *, lock=False, nowait=False):
        statement = select(Conversation).join(ConversationAccess, ConversationAccess.conversa_id == Conversation.id).where(
            Conversation.id == str(conversation_id), ConversationAccess.sessao_hash == owner_context.get())
        if lock:
            statement = statement.with_for_update(nowait=nowait)
        try:
            conversation = session.scalar(statement)
        except OperationalError as exc:
            # 55P03 = lock_not_available: outra requisição ainda processa esta conversa.
            if nowait and getattr(exc.orig, "sqlstate", None) == "55P03":
                raise HTTPException(409, BUSY) from exc
            raise
        if conversation is None:
            raise HTTPException(404, "Conversa não encontrada.")
        return conversation

    @app.get("/health")
    def health():
        try:
            with health_database.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception:
            return JSONResponse(status_code=503, content={"status": "indisponivel", "banco": "indisponivel"})
        return {"status": "ok", "banco": "ok", "modo": settings.ai_provider,
                "ia_configurada": settings.ai_configured, "confirmacao_habilitada": True}

    @app.get("/chat/produtos")
    def products():
        return [product.model_dump(mode="json") for product in client.products()]

    @app.get("/chat/pedidos/{pedido_id}")
    def order(pedido_id: int = Path(gt=0)):
        # IDs lidos e sessão fechada ANTES da chamada HTTP: não segura conexão do pool.
        with sessions() as session:
            owned = pedido_id in owned_order_ids(session, owner_context.get())
        if not owned:
            raise OrdersError(404, "Pedido não encontrado nesta sessão.")
        return client.order(pedido_id).model_dump(mode="json")

    @app.get("/chat/pedidos")
    def browser_orders():
        with sessions() as session:
            order_ids = owned_order_ids(session, owner_context.get())
        return fetch_orders(order_ids, client, BROWSER_SCOPE)

    @app.post("/chat/conversas", status_code=201)
    def create_conversation():
        with sessions.begin() as session:
            conversation = Conversation()
            session.add(conversation)
            session.flush()
            session.add(ConversationAccess(conversa_id=conversation.id, sessao_hash=owner_context.get()))
            session.add(Message(conversa_id=conversation.id, papel="assistente", conteudo="Olá! Posso consultar o catálogo real e preparar seu lanche. Você revisa o resumo e confirma a compra pelo botão. Quer ver o cardápio?"))
            session.flush()
            return snapshot(session, conversation)

    @app.get("/chat/conversas/{conversation_id}")
    def get_conversation(conversation_id: UUID):
        with sessions() as session:
            return snapshot(session, find_conversation(session, conversation_id))

    @app.get("/chat/conversas/{conversation_id}/pedidos")
    def get_conversation_orders(conversation_id: UUID):
        with sessions() as session:
            find_conversation(session, conversation_id)
            order_ids = conversation_order_ids(session, conversation_id)
        return fetch_orders(order_ids, client, CONVERSATION_SCOPE)

    @app.post("/chat/conversas/{conversation_id}/mensagens")
    def send_message(conversation_id: UUID, payload: IncomingMessage):
        content = payload.conteudo.strip()
        if not content:
            raise HTTPException(422, "A mensagem não pode ser vazia.")
        with sessions.begin() as session:
            # nowait: se a mensagem anterior ainda está na IA, responde 409 em vez de
            # enfileirar requisições segurando conexão do pool.
            conversation = find_conversation(session, conversation_id, lock=True, nowait=True)
            previous = session.scalar(select(MessageRequest).where(
                MessageRequest.conversa_id == conversation.id,
                MessageRequest.mensagem_id == str(payload.mensagem_id),
            ))
            if previous:
                if previous.conteudo != content:
                    raise HTTPException(409, "mensagem_id já utilizado com outro conteúdo.")
                # Retorna estado ATUAL para não restaurar uma seleção anterior à compra.
                return snapshot(session, conversation)
            if conversation.estado == "confirmando":
                raise HTTPException(409, "Há uma confirmação pendente. Use Repetir confirmação para recuperar o mesmo pedido antes de alterar a compra.")
            owned_client = OwnedOrdersClient(session, owner_context.get(), client)
            if settings.ai_provider == "commands":
                answer = reply(conversation, content, owned_client)
            else:
                history = session.scalars(select(Message).where(Message.conversa_id == conversation.id).order_by(Message.sequencia)).all()
                answer = respond(conversation, history, content, owned_client, provider, settings.ai_timeout,
                                 list_orders=lambda: list_browser_orders(session, owner_context.get(), client))
            conversation.atualizada_em = now()
            session.add(Message(conversa_id=conversation.id, papel="usuario", conteudo=content))
            session.flush()
            session.add(Message(conversa_id=conversation.id, papel="assistente", conteudo=answer))
            session.flush()
            result = snapshot(session, conversation)
            session.add(MessageRequest(conversa_id=conversation.id, mensagem_id=str(payload.mensagem_id), conteudo=content, resposta=result))
            logger.info("chat_message conversation_id=%s message_id=%s", conversation.id, payload.mensagem_id)
            return result

    @app.post("/chat/conversas/{conversation_id}/confirmar")
    def confirm(conversation_id: UUID, payload: Confirmation):
        return confirm_purchase(sessions, conversation_id, str(payload.compra_id), client, find_conversation, snapshot)

    return app


import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, TimeoutError as PoolTimeoutError
from sqlmodel import SQLModel, Session, select

from database import engine, get_session
from models import Produto, ProdutoCreate, ProdutoPublic
from pedidos import router as pedidos_router


# Uvicorn só configura os próprios loggers; sem isto, os logs INFO da aplicação
# não chegariam ao CloudWatch.
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    SQLModel.metadata.create_all(engine)
    yield


app = FastAPI(
    title="Insper Eats API",
    description="API de pedidos do Insper Eats",
    version="1.0.0",
    lifespan=lifespan
)


@app.exception_handler(OperationalError)
@app.exception_handler(PoolTimeoutError)
async def banco_indisponivel(_request: Request, _exc: Exception):
    # Banco fora, em failover ou com o pool esgotado: 503 com Retry-After, e não
    # um 500 genérico. O chat trata 5xx em POST /pedidos como resultado incerto
    # e repete com a mesma chave de idempotência.
    return JSONResponse(
        status_code=503,
        content={"detail": "Banco de dados indisponivel. Tente novamente."},
        headers={"Retry-After": "5"}
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post(
    "/produtos",
    response_model=ProdutoPublic,
    status_code=201
)
def criar_produto(
    dados: ProdutoCreate,
    session: Session = Depends(get_session)
):
    produto = Produto.model_validate(dados)

    session.add(produto)
    session.commit()
    session.refresh(produto)

    return produto


@app.get(
    "/produtos",
    response_model=list[ProdutoPublic]
)
def listar_produtos(
    session: Session = Depends(get_session)
):
    produtos = session.exec(select(Produto)).all()
    return produtos
app.include_router(pedidos_router)

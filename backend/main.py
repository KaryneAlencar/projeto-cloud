
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from sqlmodel import SQLModel, Session, select

from database import engine, get_session
from models import Produto, ProdutoCreate, ProdutoPublic
from pedidos import router as pedidos_router


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

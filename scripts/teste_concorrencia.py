"""Dois pedidos simultâneos para o mesmo produto (teste manual de concorrência).

Uso: ORDERS_INTERNAL_TOKEN=... python3 scripts/teste_concorrencia.py
API_URL muda o endereço da API (padrão http://127.0.0.1:8002, a porta do compose local).
Na AWS, terraform/scripts/verify_deploy.py cobre o mesmo cenário.
"""
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from urllib.request import Request, urlopen
from urllib.error import HTTPError

URL = os.getenv("API_URL", "http://127.0.0.1:8002").rstrip("/") + "/pedidos"
# /pedidos exige o mesmo token configurado na API; o padrão é o do compose local.
TOKEN = os.getenv("ORDERS_INTERNAL_TOKEN") or "insper-eats-local-only"

# Sincroniza as duas requisições
barreira = Barrier(3)


def criar_pedido(cliente):
    dados = {
        "cliente": cliente,
        "local_entrega": "Sala 512 - Predio 2",
        "chave_idempotencia": str(uuid.uuid4()),
        "itens": [
            {
                "produto_id": 2,
                "quantidade": 1
            }
        ]
    }

    requisicao = Request(
        URL,
        data=json.dumps(dados).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Internal-Token": TOKEN
        },
        method="POST"
    )

    barreira.wait()

    try:
        with urlopen(requisicao, timeout=20) as resposta:
            return cliente, resposta.status, json.loads(
                resposta.read().decode()
            )
    except HTTPError as erro:
        return cliente, erro.code, erro.read().decode()


with ThreadPoolExecutor(max_workers=2) as executor:
    resultados = [
        executor.submit(criar_pedido, "Cliente A"),
        executor.submit(criar_pedido, "Cliente B")
    ]

    # Libera as duas requisições ao mesmo tempo
    barreira.wait()

    for resultado in resultados:
        cliente, status, resposta = resultado.result()
        print(f"\n{cliente}")
        print(f"HTTP: {status}")
        print(f"Resposta: {resposta}")

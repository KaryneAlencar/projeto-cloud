
import os
import json
import time
import signal
import logging
from pathlib import Path

import boto3
from botocore.config import Config
from sqlmodel import Session, select

from database import engine
from models import Pedido, EventoOutbox


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("insper-eats-worker")

# Sem região fixa no código: vem do ambiente da task (AWS_REGION) ou da
# configuração padrão do boto3.
REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
QUEUE_NAME = os.getenv(
    "SQS_QUEUE_NAME",
    "insper-eats-orders"
)

# Tocado a cada volta do laço principal, inclusive quando o banco ou o SQS
# estão fora: reiniciar o worker não conserta uma dependência indisponível. O
# health check do contêiner (ECS e compose) falha se o arquivo ficar mais de
# 120 s sem atualização, isto é, se o laço travar.
HEARTBEAT_FILE = Path("/tmp/worker-heartbeat")

# Prazos curtos: uma chamada presa ao SQS manteria a transação da outbox
# aberta. O read_timeout precisa ser maior que o long polling de 10 s.
sqs = boto3.client(
    "sqs",
    region_name=REGION,
    config=Config(
        connect_timeout=3,
        read_timeout=20,
        retries={"max_attempts": 3, "mode": "standard"}
    )
)

QUEUE_URL = None
encerrando = False


def obter_fila():
    """Resolve a URL da fila na primeira volta, e não no import: se o SQS
    estiver indisponível na partida, o laço tenta de novo em vez de o processo
    morrer."""
    global QUEUE_URL

    if QUEUE_URL is None:
        QUEUE_URL = sqs.get_queue_url(
            QueueName=QUEUE_NAME
        )["QueueUrl"]

    return QUEUE_URL


def solicitar_encerramento(signum, _frame):
    """SIGTERM do ECS (deploy, scale-in): termina a volta atual e sai, em vez
    de esperar o SIGKILL com mensagens em processamento."""
    global encerrando
    encerrando = True
    logger.info("Sinal %s recebido; encerrando apos o ciclo atual", signum)


def publicar_pendentes():
    with Session(engine) as session:
        eventos = session.exec(
            select(EventoOutbox)
            .where(EventoOutbox.publicado.is_(False))
            .order_by(EventoOutbox.id)
            .limit(10)
            .with_for_update(skip_locked=True)
        ).all()

        for evento in eventos:
            mensagem = {
                "tipo": evento.tipo,
                "pedido_id": evento.pedido_id,
                "evento_id": evento.id
            }

            sqs.send_message(
                QueueUrl=obter_fila(),
                MessageBody=json.dumps(mensagem)
            )

            evento.publicado = True
            session.add(evento)

            logger.info(
                "Evento %s enviado ao SQS", evento.id
            )

        session.commit()


def processar_mensagem(mensagem):
    dados = json.loads(mensagem["Body"])

    if dados.get("tipo") != "pedido.criado":
        raise ValueError("Tipo de evento inválido")

    pedido_id = dados.get("pedido_id")

    if type(pedido_id) is not int or pedido_id <= 0:
        raise ValueError("ID de pedido inválido")

    with Session(engine) as session:
        pedido = session.exec(
            select(Pedido)
            .where(Pedido.id == pedido_id)
            .with_for_update()
        ).first()

        if pedido is None:
            raise ValueError("Pedido não encontrado")

        if pedido.status == "recebido":
            pedido.status = "confirmado"
            session.add(pedido)
            session.commit()

            logger.info(
                "Pedido %s confirmado", pedido_id
            )

        elif pedido.status == "confirmado":
            logger.info(
                "Pedido %s ja confirmado. Mensagem duplicada ignorada",
                pedido_id
            )

        else:
            raise ValueError("Status inesperado")

    sqs.delete_message(
        QueueUrl=obter_fila(),
        ReceiptHandle=mensagem["ReceiptHandle"]
    )


def executar_worker():
    signal.signal(signal.SIGTERM, solicitar_encerramento)
    signal.signal(signal.SIGINT, solicitar_encerramento)
    logger.info("Worker iniciado")

    while not encerrando:
        HEARTBEAT_FILE.touch()

        try:
            publicar_pendentes()

            resposta = sqs.receive_message(
                QueueUrl=obter_fila(),
                MaxNumberOfMessages=5,
                WaitTimeSeconds=10,
                VisibilityTimeout=60
            )

            for mensagem in resposta.get("Messages", []):
                try:
                    processar_mensagem(mensagem)
                except Exception:
                    logger.exception(
                        "Falha ao processar mensagem"
                    )

        except Exception:
            logger.exception("Falha no Worker")
            time.sleep(5)

    logger.info("Worker encerrado")


if __name__ == "__main__":
    executar_worker()
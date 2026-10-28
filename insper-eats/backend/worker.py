
import os
import json
import time
import logging

import boto3
from sqlmodel import Session, select

from database import engine
from models import Pedido, EventoOutbox


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("insper-eats-worker")

REGION = os.getenv("AWS_REGION", "us-east-2")
QUEUE_NAME = os.getenv(
    "SQS_QUEUE_NAME",
    "insper-eats-orders"
)

sqs = boto3.client("sqs", region_name=REGION)

QUEUE_URL = sqs.get_queue_url(
    QueueName=QUEUE_NAME
)["QueueUrl"]


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
                QueueUrl=QUEUE_URL,
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

        elif pedido.status != "confirmado":
            raise ValueError("Status inesperado")

    sqs.delete_message(
        QueueUrl=QUEUE_URL,
        ReceiptHandle=mensagem["ReceiptHandle"]
    )


def executar_worker():
    logger.info("Worker iniciado")

    while True:
        try:
            publicar_pendentes()

            resposta = sqs.receive_message(
                QueueUrl=QUEUE_URL,
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


if __name__ == "__main__":
    executar_worker()
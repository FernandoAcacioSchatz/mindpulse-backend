"""
Cliente RabbitMQ (via CloudAMQP) — conexão, declaração da topologia e
publicação de convites de pesquisa.

Topologia:

    radar.eventos (exchange, topic, durable)
          |
          | routing key: pesquisa.convite.enviar
          v
    fila.enviar_convite (durable)  <-------------------+
                                                         |
                                     dead-letter de volta após o TTL
                                     (retry automático, sem plugin extra)
                                                         |
    fila.enviar_convite.retry (durable, TTL 30s, DLX -> radar.eventos)
          ^
          | consumidor publica aqui (fila nomeada, exchange padrão)
          | quando dá erro e ainda não estourou MAX_TENTATIVAS
          |
    (consumidor: workers/consumidor_convites.py)
          |
          | estourou MAX_TENTATIVAS
          v
    fila.enviar_convite.dlq (durable) -- fica parada aqui pra investigar
                                          manualmente (e-mail inválido,
                                          Brevo rejeitando, etc.)

Por que exchange do tipo "topic" (e não "direct"): esse é só o primeiro
fluxo assíncrono do produto. Se amanhã "encerrar pesquisa" ou "alerta
crítico" também virarem eventos, dá pra usar o MESMO exchange com
routing keys tipo "pesquisa.encerrar", "alerta.critico", sem redesenhar
nada -- só criar novas filas com novos bindings.

Uma conexão por lote (não por mensagem): o CloudAMQP free tier
("Little Lemur") tem limite de conexões simultâneas, então publicar
todos os convites de uma pesquisa numa única conexão/canal é
importante, não só otimização.
"""
import json

import pika

from config import RABBITMQ_URL

EXCHANGE = "radar.eventos"
ROUTING_KEY_CONVITE = "pesquisa.convite.enviar"

FILA_PRINCIPAL = "fila.enviar_convite"
FILA_RETRY = "fila.enviar_convite.retry"
FILA_DLQ = "fila.enviar_convite.dlq"

TTL_RETRY_MS = 30_000  # 30s parado na fila de retry antes de voltar pra principal
MAX_TENTATIVAS = 3


def conectar() -> pika.BlockingConnection:
    if not RABBITMQ_URL:
        raise RuntimeError("RABBITMQ_URL não configurada no ambiente.")
    parametros = pika.URLParameters(RABBITMQ_URL)
    return pika.BlockingConnection(parametros)


def declarar_topologia(canal) -> None:
    """
    Idempotente -- seguro chamar toda vez que conecta. Se já existe
    com os mesmos parâmetros, o RabbitMQ não faz nada; declarar de
    novo também deixa o sistema auto-recuperável caso algo seja
    apagado manualmente no painel do CloudAMQP.
    """
    canal.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)

    canal.queue_declare(queue=FILA_PRINCIPAL, durable=True)
    canal.queue_bind(queue=FILA_PRINCIPAL, exchange=EXCHANGE, routing_key=ROUTING_KEY_CONVITE)

    # Fila de retry: ninguém consome dela. Ela só "segura" a mensagem
    # por TTL_RETRY_MS e depois ela mesma expira e é dead-lettered de
    # volta pro exchange principal, reaparecendo na fila principal.
    canal.queue_declare(
        queue=FILA_RETRY,
        durable=True,
        arguments={
            "x-message-ttl": TTL_RETRY_MS,
            "x-dead-letter-exchange": EXCHANGE,
            "x-dead-letter-routing-key": ROUTING_KEY_CONVITE,
        },
    )

    canal.queue_declare(queue=FILA_DLQ, durable=True)


def publicar_convites(mensagens: list[dict]) -> None:
    """
    Publica várias mensagens de convite numa única conexão/canal.
    Chamado pelo produtor (jobs/enviar_pesquisa.py) -- é rápido, só
    confirma que o RabbitMQ recebeu, não espera nenhum e-mail ser
    enviado de verdade (isso é trabalho do consumidor).
    """
    if not mensagens:
        return

    conexao = conectar()
    try:
        canal = conexao.channel()
        declarar_topologia(canal)
        canal.confirm_delivery()  # publisher confirms: garante que o broker recebeu antes de seguir

        for mensagem in mensagens:
            corpo = json.dumps(mensagem).encode("utf-8")
            publicado = canal.basic_publish(
                exchange=EXCHANGE,
                routing_key=ROUTING_KEY_CONVITE,
                body=corpo,
                properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
                mandatory=True,
            )
            if not publicado:
                raise RuntimeError(f"RabbitMQ não confirmou o recebimento da mensagem: {mensagem}")
    finally:
        conexao.close()

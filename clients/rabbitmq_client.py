import json
import time

import pika

from config import RABBITMQ_URL, RABBITMQ_URL_CONSUMIDOR, RABBITMQ_URL_PUBLISHER

EXCHANGE = "radar.eventos"

ROUTING_KEY_NORMAL = "email.normal"
ROUTING_KEY_PRIORITARIO = "email.prioritario"

FILA_PRINCIPAL = "fila.enviar_convite"
FILA_RETRY = "fila.enviar_convite.retry"
FILA_PRIORITARIA = "fila.enviar_convite.prioritaria"
FILA_RETRY_PRIORITARIA = "fila.enviar_convite.prioritaria.retry"
FILA_DLQ = "fila.enviar_convite.dlq"

TTL_RETRY_MS = 30_000
MAX_TENTATIVAS = 3

MAX_TENTATIVAS_PUBLICACAO = 3
ESPERA_ENTRE_TENTATIVAS_S = 0.5


def _conectar(url: str, nome_credencial: str) -> pika.BlockingConnection:
    if not url:
        raise RuntimeError(
            f"{nome_credencial} não configurada no ambiente. Ver RABBITMQ_AUTORIZACAO.md."
        )
    parametros = pika.URLParameters(url)
    return pika.BlockingConnection(parametros)


def conectar_admin() -> pika.BlockingConnection:
    return _conectar(RABBITMQ_URL, "RABBITMQ_URL")


def conectar_publicador() -> pika.BlockingConnection:
    return _conectar(RABBITMQ_URL_PUBLISHER, "RABBITMQ_URL_PUBLISHER")


def conectar_consumidor() -> pika.BlockingConnection:
    return _conectar(RABBITMQ_URL_CONSUMIDOR, "RABBITMQ_URL_CONSUMIDOR")


def declarar_topologia(canal) -> None:
    canal.exchange_declare(exchange=EXCHANGE, exchange_type="direct", durable=True)

    canal.queue_declare(
        queue=FILA_PRINCIPAL,
        durable=True,
        arguments={
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": FILA_RETRY,
        },
    )
    canal.queue_bind(queue=FILA_PRINCIPAL, exchange=EXCHANGE, routing_key=ROUTING_KEY_NORMAL)

    canal.queue_declare(
        queue=FILA_RETRY,
        durable=True,
        arguments={
            "x-message-ttl": TTL_RETRY_MS,
            "x-dead-letter-exchange": EXCHANGE,
            "x-dead-letter-routing-key": ROUTING_KEY_NORMAL,
        },
    )

    canal.queue_declare(
        queue=FILA_PRIORITARIA,
        durable=True,
        arguments={
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": FILA_RETRY_PRIORITARIA,
        },
    )
    canal.queue_bind(queue=FILA_PRIORITARIA, exchange=EXCHANGE, routing_key=ROUTING_KEY_PRIORITARIO)

    canal.queue_declare(
        queue=FILA_RETRY_PRIORITARIA,
        durable=True,
        arguments={
            "x-message-ttl": TTL_RETRY_MS,
            "x-dead-letter-exchange": EXCHANGE,
            "x-dead-letter-routing-key": ROUTING_KEY_PRIORITARIO,
        },
    )

    canal.queue_declare(queue=FILA_DLQ, durable=True)


def tentativas_anteriores(propriedades, fila: str = FILA_PRINCIPAL) -> int:
    headers = getattr(propriedades, "headers", None) or {}
    for entrada in headers.get("x-death", []) or []:
        if entrada.get("queue") == fila and entrada.get("reason") == "rejected":
            return int(entrada.get("count", 0))
    return 0


def publicar_mensagens(mensagens: list[dict], routing_key: str = ROUTING_KEY_NORMAL) -> list[bool]:
    if not mensagens:
        return []

    resultados = [False] * len(mensagens)
    conexao = None

    try:
        conexao = conectar_publicador()
        canal = conexao.channel()
        canal.confirm_delivery()
    except Exception as e:
        print(f"[rabbitmq_client] Não foi possível conectar como publicador -- lote inteiro falhou ({len(mensagens)} mensagens): {e}")
        try:
            if conexao is not None and conexao.is_open:
                conexao.close()
        except Exception:
            pass
        return resultados

    try:
        for i, mensagem in enumerate(mensagens):
            corpo = json.dumps(mensagem).encode("utf-8")
            publicado = False

            for tentativa in range(1, MAX_TENTATIVAS_PUBLICACAO + 1):
                try:
                    canal.basic_publish(
                        exchange=EXCHANGE,
                        routing_key=routing_key,
                        body=corpo,
                        properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
                        mandatory=True,
                    )
                    publicado = True
                except (pika.exceptions.UnroutableError, pika.exceptions.NackError) as e:
                    print(f"[rabbitmq_client] Broker recusou a mensagem (tentativa {tentativa}/{MAX_TENTATIVAS_PUBLICACAO}): {e}")
                    publicado = False
                except Exception as e:
                    print(f"[rabbitmq_client] Erro ao publicar (tentativa {tentativa}/{MAX_TENTATIVAS_PUBLICACAO}): {e}")
                    publicado = False

                if publicado:
                    break

                if tentativa < MAX_TENTATIVAS_PUBLICACAO:
                    print(f"[rabbitmq_client] Falha ao publicar, tentativa {tentativa}/{MAX_TENTATIVAS_PUBLICACAO}, reconectando...")
                    try:
                        conexao.close()
                    except Exception:
                        pass
                    try:
                        time.sleep(ESPERA_ENTRE_TENTATIVAS_S)
                        conexao = conectar_publicador()
                        canal = conexao.channel()
                        canal.confirm_delivery()
                    except Exception as e:
                        print(f"[rabbitmq_client] Falha ao reconectar (tentativa {tentativa}/{MAX_TENTATIVAS_PUBLICACAO}): {e}")
                        conexao = None

            resultados[i] = publicado
            if not publicado:
                print(f"[rabbitmq_client] Desisti de publicar após {MAX_TENTATIVAS_PUBLICACAO} tentativas: {mensagem}")

            if conexao is None:
                restantes = len(mensagens) - i - 1
                if restantes > 0:
                    print(f"[rabbitmq_client] Conexão perdida -- interrompendo o lote, {restantes} mensagem(ns) restante(s) ficam como falha.")
                break
    finally:
        try:
            if conexao is not None and conexao.is_open:
                conexao.close()
        except Exception:
            pass

    return resultados

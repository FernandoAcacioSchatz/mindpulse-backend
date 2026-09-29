import json
import time

import pika

from config import RABBITMQ_URL

EXCHANGE = "radar.eventos"

ROUTING_KEY_NORMAL = "email.normal"
ROUTING_KEY_PRIORITARIO = "email.prioritario"

FILA_PRINCIPAL = "fila.enviar_convite"
FILA_RETRY = "fila.enviar_convite.retry"
FILA_DLQ = "fila.enviar_convite.dlq"

TTL_RETRY_MS = 30_000
MAX_TENTATIVAS = 3

MAX_TENTATIVAS_PUBLICACAO = 3
ESPERA_ENTRE_TENTATIVAS_S = 0.5


def conectar() -> pika.BlockingConnection:
    if not RABBITMQ_URL:
        raise RuntimeError("RABBITMQ_URL não configurada no ambiente.")
    parametros = pika.URLParameters(RABBITMQ_URL)
    return pika.BlockingConnection(parametros)


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
    canal.queue_bind(
        queue=FILA_PRINCIPAL, exchange=EXCHANGE, routing_key=ROUTING_KEY_NORMAL
    )

    canal.queue_declare(
        queue=FILA_RETRY,
        durable=True,
        arguments={
            "x-message-ttl": TTL_RETRY_MS,
            "x-dead-letter-exchange": EXCHANGE,
            "x-dead-letter-routing-key": ROUTING_KEY_NORMAL,
        },
    )

    canal.queue_declare(queue=FILA_DLQ, durable=True)


def tentativas_anteriores(propriedades) -> int:
    headers = getattr(propriedades, "headers", None) or {}
    for entrada in headers.get("x-death", []) or []:
        if (
            entrada.get("queue") == FILA_PRINCIPAL
            and entrada.get("reason") == "rejected"
        ):
            return int(entrada.get("count", 0))
    return 0


def publicar_convites(mensagens: list[dict]) -> list[bool]:
    if not mensagens:
        return []

    resultados = [False] * len(mensagens)
    conexao = None

    try:
        conexao = conectar()
        canal = conexao.channel()
        declarar_topologia(canal)
        canal.confirm_delivery()
    except Exception as e:
        print(
            f"[rabbitmq_client] Não foi possível conectar/declarar a topologia -- lote inteiro falhou ({len(mensagens)} mensagens): {e}"
        )
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
                    publicado = canal.basic_publish(
                        exchange=EXCHANGE,
                        routing_key=ROUTING_KEY_NORMAL,
                        body=corpo,
                        properties=pika.BasicProperties(
                            content_type="application/json", delivery_mode=2
                        ),
                        mandatory=True,
                    )
                except Exception as e:
                    print(
                        f"[rabbitmq_client] Erro ao publicar (tentativa {tentativa}/{MAX_TENTATIVAS_PUBLICACAO}): {e}"
                    )
                    publicado = False

                if publicado:
                    break

                if tentativa < MAX_TENTATIVAS_PUBLICACAO:
                    print(
                        f"[rabbitmq_client] Mensagem não confirmada, tentativa {tentativa}/{MAX_TENTATIVAS_PUBLICACAO}, reconectando..."
                    )
                    try:
                        conexao.close()
                    except Exception:
                        pass
                    try:
                        time.sleep(ESPERA_ENTRE_TENTATIVAS_S)
                        conexao = conectar()
                        canal = conexao.channel()
                        declarar_topologia(canal)
                        canal.confirm_delivery()
                    except Exception as e:
                        print(
                            f"[rabbitmq_client] Falha ao reconectar (tentativa {tentativa}/{MAX_TENTATIVAS_PUBLICACAO}): {e}"
                        )
                        conexao = None

            resultados[i] = publicado
            if not publicado:
                print(
                    f"[rabbitmq_client] Desisti de publicar após {MAX_TENTATIVAS_PUBLICACAO} tentativas: {mensagem}"
                )

            if conexao is None:
                restantes = len(mensagens) - i - 1
                if restantes > 0:
                    print(
                        f"[rabbitmq_client] Conexão perdida -- interrompendo o lote, {restantes} mensagem(ns) restante(s) ficam como falha."
                    )
                break
    finally:
        try:
            if conexao is not None and conexao.is_open:
                conexao.close()
        except Exception:
            pass

    return resultados

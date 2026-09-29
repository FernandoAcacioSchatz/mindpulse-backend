"""
Cliente RabbitMQ (via CloudAMQP) — conexão, declaração da topologia e
publicação de convites de pesquisa.

Topologia (exchange DIRECT, conforme Etapa 2.b do trabalho de
Sistemas Distribuídos -- roteamento simples e previsível, sem precisar
dos padrões de uma topic nem da réplica de uma fanout):

    radar.eventos (exchange, direct, durable)
          |
          | routing key: email.normal (envio inicial da pesquisa)
          | routing key: email.prioritario (reservada p/ lembretes
          |              próximos do prazo -- ainda sem binding, os
          |              jobs de lembrete ainda não migraram pro
          |              RabbitMQ)
          v
    fila.enviar_convite (durable, com dead-letter automático)  <---+
          |                                                        |
          | consumidor NÃO confirma (nack) quando falha            |
          | -- a própria fila já manda sozinha pra fila de retry   |
          v                                       dead-letter de   |
    fila.enviar_convite.retry (durable, TTL 30s)   volta após TTL -+
          |
          | (consumidor: workers/consumidor_convites.py)
          | estourou MAX_TENTATIVAS (contado pelo header x-death,
          | nativo do RabbitMQ -- não guardamos contador manual)
          v
    fila.enviar_convite.dlq (durable) -- fica parada aqui pra investigar
                                          manualmente (e-mail inválido,
                                          Brevo rejeitando, etc.)

Ack manual (Etapa 2.a/2.d do trabalho): uma mensagem só sai da fila
principal de verdade quando o Brevo confirma o envio (ack). Falhou?
NUNCA fazemos ack -- fazemos nack(requeue=False), e quem tira a
mensagem da fila principal e manda pra retry é o dead-letter-exchange
da própria fila (configurado abaixo), automaticamente. Isso também
resolve a contagem de tentativas sem precisar de um campo manual no
corpo da mensagem: o RabbitMQ já anota em `x-death` quantas vezes essa
mensagem foi rejeitada dali.

Uma conexão por lote (não por mensagem): o CloudAMQP free tier
("Little Lemur") tem limite de conexões simultâneas, então publicar
todos os convites de uma pesquisa numa única conexão/canal é
importante, não só otimização.

Retentativa na PUBLICAÇÃO (diferente do retry do consumidor): de vez
em quando, principalmente em broker gratuito compartilhado, o RabbitMQ
não confirma a primeira publicação de uma mensagem (a chamada volta
"não confirmado", sem nenhum erro de conexão visível). Isso não tem
nada a ver com MAX_TENTATIVAS (que é do consumidor, controla reenvio
de e-mail via fila.enviar_convite.retry) -- aqui é antes disso, é
sobre conseguir colocar a mensagem na fila em primeiro lugar.
MAX_TENTATIVAS_PUBLICACAO trata isso: tenta de novo, reabrindo a
conexão do zero se preciso, antes de desistir daquela mensagem
específica -- sem abortar o lote inteiro por causa de 1 mensagem.

IMPORTANTE ao fazer deploy desta versão: o RabbitMQ não deixa
redeclarar uma fila já existente com argumentos diferentes dos que ela
já tem (erro PRECONDITION_FAILED). Como fila.enviar_convite e
fila.enviar_convite.retry mudaram de argumentos (routing key e/ou
dead-letter), é preciso apagar as duas manualmente no painel da
CloudAMQP (RabbitMQ Manager -> Queues and Streams) antes do primeiro
deploy com este arquivo -- elas são recriadas sozinhas, do jeito novo,
na primeira chamada depois disso.
"""
import json
import time

import pika

from config import RABBITMQ_URL

EXCHANGE = "radar.eventos"

ROUTING_KEY_NORMAL = "email.normal"            # envio inicial da pesquisa (em uso)
ROUTING_KEY_PRIORITARIO = "email.prioritario"  # reservada p/ lembretes -- sem binding ainda

FILA_PRINCIPAL = "fila.enviar_convite"
FILA_RETRY = "fila.enviar_convite.retry"
FILA_DLQ = "fila.enviar_convite.dlq"

TTL_RETRY_MS = 30_000  # 30s parado na fila de retry antes de voltar pra principal
MAX_TENTATIVAS = 3  # retry do CONSUMIDOR (reenvio de e-mail) -- ver workers/consumidor_convites.py

MAX_TENTATIVAS_PUBLICACAO = 3  # retry do PRODUTOR (confirmar que a mensagem entrou na fila)
ESPERA_ENTRE_TENTATIVAS_S = 0.5


def conectar() -> pika.BlockingConnection:
    if not RABBITMQ_URL:
        raise RuntimeError("RABBITMQ_URL não configurada no ambiente.")
    parametros = pika.URLParameters(RABBITMQ_URL)
    return pika.BlockingConnection(parametros)


def declarar_topologia(canal) -> None:
    """
    Idempotente -- seguro chamar toda vez que conecta, DESDE QUE os
    argumentos não mudem entre uma chamada e outra (ver aviso no
    docstring do módulo sobre apagar as filas manualmente na primeira
    vez que este arquivo for publicado).
    """
    canal.exchange_declare(exchange=EXCHANGE, exchange_type="direct", durable=True)

    # Dead-letter automático: uma mensagem rejeitada (nack, requeue=False)
    # cai direto na fila de retry, sem o consumidor precisar republicar
    # nada manualmente -- o ack só acontece de verdade após o Brevo
    # confirmar o envio.
    canal.queue_declare(
        queue=FILA_PRINCIPAL,
        durable=True,
        arguments={
            "x-dead-letter-exchange": "",  # exchange padrão -- roteia pelo nome da fila
            "x-dead-letter-routing-key": FILA_RETRY,
        },
    )
    canal.queue_bind(queue=FILA_PRINCIPAL, exchange=EXCHANGE, routing_key=ROUTING_KEY_NORMAL)

    # Fila de retry: ninguém consome dela. Ela só "segura" a mensagem
    # por TTL_RETRY_MS e depois ela mesma expira e é dead-lettered de
    # volta pro exchange principal, reaparecendo na fila principal.
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
    """
    Quantas vezes essa mensagem já foi rejeitada (nack) da fila
    principal -- lido do header `x-death`, que o próprio RabbitMQ
    mantém a cada dead-letter. Não guardamos esse contador no corpo da
    mensagem; o broker já faz isso por nós.
    """
    headers = getattr(propriedades, "headers", None) or {}
    for entrada in headers.get("x-death", []) or []:
        if entrada.get("queue") == FILA_PRINCIPAL and entrada.get("reason") == "rejected":
            return int(entrada.get("count", 0))
    return 0


def publicar_convites(mensagens: list[dict]) -> list[bool]:
    """
    Publica várias mensagens de convite numa única conexão/canal.
    Chamado pelo produtor (jobs/enviar_pesquisa.py) -- é rápido, só
    confirma que o RabbitMQ recebeu, não espera nenhum e-mail ser
    enviado de verdade (isso é trabalho do consumidor).

    Devolve uma lista de bool, na MESMA ORDEM de `mensagens`, dizendo
    quais entraram na fila com sucesso. Uma mensagem que falhar mesmo
    depois de MAX_TENTATIVAS_PUBLICACAO tentativas não derruba as
    outras -- quem chama decide o que fazer com quem falhou (ver
    jobs/enviar_pesquisa.py, que desfaz o token daquele funcionário
    pra tentar de novo na próxima execução).
    """
    if not mensagens:
        return []

    resultados = [False] * len(mensagens)
    conexao = None

    try:
        conexao = conectar()
        canal = conexao.channel()
        declarar_topologia(canal)
        canal.confirm_delivery()  # publisher confirms: garante que o broker recebeu antes de seguir

        for i, mensagem in enumerate(mensagens):
            corpo = json.dumps(mensagem).encode("utf-8")
            publicado = False

            for tentativa in range(1, MAX_TENTATIVAS_PUBLICACAO + 1):
                try:
                    publicado = canal.basic_publish(
                        exchange=EXCHANGE,
                        routing_key=ROUTING_KEY_NORMAL,
                        body=corpo,
                        properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
                        mandatory=True,
                    )
                except Exception as e:
                    print(f"[rabbitmq_client] Erro ao publicar (tentativa {tentativa}/{MAX_TENTATIVAS_PUBLICACAO}): {e}")
                    publicado = False

                if publicado:
                    break

                if tentativa < MAX_TENTATIVAS_PUBLICACAO:
                    # Não confirmado (ou deu erro) -- reabre a conexão do zero antes
                    # de tentar de novo, caso o problema seja a conexão/canal, não
                    # só uma confirmação isolada perdida.
                    print(f"[rabbitmq_client] Mensagem não confirmada, tentativa {tentativa}/{MAX_TENTATIVAS_PUBLICACAO}, reconectando...")
                    try:
                        conexao.close()
                    except Exception:
                        pass
                    time.sleep(ESPERA_ENTRE_TENTATIVAS_S)
                    conexao = conectar()
                    canal = conexao.channel()
                    declarar_topologia(canal)
                    canal.confirm_delivery()

            resultados[i] = publicado
            if not publicado:
                print(f"[rabbitmq_client] Desisti de publicar após {MAX_TENTATIVAS_PUBLICACAO} tentativas: {mensagem}")
    finally:
        try:
            if conexao is not None and conexao.is_open:
                conexao.close()
        except Exception:
            pass

    return resultados

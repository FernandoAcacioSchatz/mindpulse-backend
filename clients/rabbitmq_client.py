"""
Cliente RabbitMQ (via CloudAMQP) — conexão, declaração da topologia e
publicação de convites de pesquisa e lembretes.

Topologia (exchange DIRECT, conforme Etapa 2.b do trabalho de
Sistemas Distribuídos -- roteamento simples e previsível, sem precisar
dos padrões de uma topic nem da réplica de uma fanout). Duas rotas,
cada uma com seu par fila-principal/fila-retry, mas as DUAS filas
principais são lidas pelo MESMO consumidor (workers/consumidor_continuo.py),
que confere sempre a de prioridade primeiro:

    radar.eventos (exchange, direct, durable)
          |
          |-- routing key: email.normal (envio inicial da pesquisa)
          |         v
          |   fila.enviar_convite (durable, dead-letter automático)  <---+
          |         |                                                    |
          |         v                                dead-letter de      |
          |   fila.enviar_convite.retry (durable, TTL 30s)  volta após TTL-+
          |
          |-- routing key: email.prioritario (lembretes próximos do prazo)
                    v
              fila.enviar_convite.prioritaria (durable, dead-letter automático)  <---+
                    |                                                                |
                    v                                             dead-letter de     |
              fila.enviar_convite.prioritaria.retry (durable, TTL 30s) volta após TTL-+

    (consumidor NÃO confirma (nack) quando falha em qualquer uma das
    duas -- a própria fila já manda sozinha pra sua fila de retry)

    Depois de MAX_TENTATIVAS (contado pelo header x-death, nativo do
    RabbitMQ -- não guardamos contador manual) em qualquer uma das
    duas rotas, o consumidor manda manualmente pra:

    fila.enviar_convite.dlq (durable, compartilhada pelas duas rotas)
        -- fica parada aqui pra investigar manualmente (e-mail
           inválido, Brevo rejeitando, etc.)

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

Retentativa na PUBLICAÇÃO (diferente do retry do consumidor): a conexão
com um broker gratuito compartilhado pode cair, ou o broker pode
recusar a mensagem de verdade (exceção real) -- isso não tem nada a ver
com MAX_TENTATIVAS (que é do consumidor, controla reenvio de e-mail via
fila.enviar_convite.retry) -- aqui é antes disso, é sobre conseguir
colocar a mensagem na fila em primeiro lugar. MAX_TENTATIVAS_PUBLICACAO
trata isso: tenta de novo, reabrindo a conexão do zero se preciso, antes
de desistir daquela mensagem específica -- sem abortar o lote inteiro
por causa de 1 mensagem.

BUG CORRIGIDO (importante): com `canal.confirm_delivery()` ativo, o
`pika` NUNCA devolve `True`/`False` no retorno de `basic_publish` --
ele sempre devolve `None` (ver padrão oficial em
https://pika.readthedocs.io/en/stable/examples/blocking_delivery_confirmations.html).
Quem indica que a publicação foi confirmada é a AUSÊNCIA de exceção, não
o valor de retorno. A versão anterior desta função guardava o retorno em
`publicado` e checava `if publicado:` -- como o retorno é sempre `None`
("falso" em Python), ela tratava TODA publicação como "não confirmada",
mesmo as que tinham funcionado -- reconectava, tentava de novo (podendo
publicar a MESMA mensagem mais de uma vez) e, no fim, devolvia `False`
pra quem chamou mesmo quando a mensagem já estava na fila. É muito
provável que isso explique o bug histórico citado abaixo (tokens
ficando "pendente" com a mensagem já enfileirada).

IMPORTANTE ao fazer deploy desta versão: o RabbitMQ não deixa
redeclarar uma fila já existente com argumentos diferentes dos que ela
já tem (erro PRECONDITION_FAILED). Como fila.enviar_convite e
fila.enviar_convite.retry mudaram de argumentos (routing key e/ou
dead-letter), é preciso apagar as duas manualmente no painel da
CloudAMQP (RabbitMQ Manager -> Queues and Streams) antes do primeiro
deploy com este arquivo -- elas são recriadas sozinhas, do jeito novo,
na primeira chamada depois disso.

Autorização por papel (Etapa 3 do trabalho de Sistemas Distribuídos):
até aqui, TODO mundo -- produtor e consumidor -- conectava com a MESMA
credencial (acesso total ao vhost: cria, apaga, lê e escreve em
qualquer fila ou exchange). O código abaixo já está pronto pra 3
credenciais distintas (ver config.py), cada uma só com o que
precisaria pra fazer o seu trabalho:

    RABBITMQ_URL (admin)       -- configure+write+read em tudo.
                                   Só usada por scripts/provisionar_topologia.py,
                                   rodado manualmente. NUNCA em produção.
    RABBITMQ_URL_PUBLISHER      -- write só em "radar.eventos" (a exchange).
                                   configure e read vazios -- não lê fila
                                   nenhuma, não apaga nada, não vê a DLQ.
    RABBITMQ_URL_CONSUMIDOR     -- read só em "fila.*". write só na exchange
                                   default (mapeada pelo RabbitMQ como
                                   "amq.default" -- é como o consumidor manda
                                   a mensagem morta pra DLQ). Não publica na
                                   exchange principal, não é um produtor.

RESSALVA IMPORTANTE (documentada em RABBITMQ_AUTORIZACAO.md): o plano
gratuito da CloudAMQP usado neste projeto (Little Lemur, compartilhado)
não permite criar usuários/permissões novos -- isso só existe nos
planos "dedicados" pagos. Ou seja, HOJE as 3 variáveis acima apontam
pra credencial única de sempre (config.py cai de volta sozinho, com um
aviso no log) -- os 3 papéis abaixo (conectar_admin/publicador/
consumidor) são uma separação real no CÓDIGO, esperando as credenciais
reais existirem. O ganho concreto de agora: nenhum processo em
produção (jobs, workers) usa mais permissão "configure" -- só o script
de provisionamento declara topologia, manualmente. Ver
RABBITMQ_AUTORIZACAO.md pra matriz completa e os dois caminhos que
destravam credenciais de verdade (upgrade de plano ou self-host).
"""
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
    """Credencial de acesso total -- só pra scripts/provisionar_topologia.py."""
    return _conectar(RABBITMQ_URL, "RABBITMQ_URL")


def conectar_publicador() -> pika.BlockingConnection:
    """Credencial do papel 'produtor' -- write só na exchange radar.eventos."""
    return _conectar(RABBITMQ_URL_PUBLISHER, "RABBITMQ_URL_PUBLISHER")


def conectar_consumidor() -> pika.BlockingConnection:
    """Credencial do papel 'consumidor' -- read só nas filas fila.*."""
    return _conectar(RABBITMQ_URL_CONSUMIDOR, "RABBITMQ_URL_CONSUMIDOR")


def declarar_topologia(canal) -> None:
    """
    Cria/confirma exchange, filas e bindings. Exige permissão
    "configure" em tudo -- por isso só é chamada pelo script de
    provisionamento (scripts/provisionar_topologia.py), com a
    credencial admin. Produtor e consumidor, em produção, NUNCA
    chamam esta função -- eles só usam recursos que já existem.

    Idempotente -- seguro chamar de novo, DESDE QUE os argumentos não
    mudem entre uma chamada e outra (ver aviso no docstring do módulo
    sobre apagar as filas manualmente antes de mudar algum argumento).
    """
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
    """
    Quantas vezes essa mensagem já foi rejeitada (nack) da fila de
    origem (`fila`) -- lido do header `x-death`, que o próprio
    RabbitMQ mantém a cada dead-letter. Não guardamos esse contador no
    corpo da mensagem; o broker já faz isso por nós. Default
    FILA_PRINCIPAL pra não quebrar quem já chamava essa função sem
    informar de qual fila veio a mensagem (workers/consumidor_convites.py,
    que só lê da fila principal mesmo).
    """
    headers = getattr(propriedades, "headers", None) or {}
    for entrada in headers.get("x-death", []) or []:
        if entrada.get("queue") == fila and entrada.get("reason") == "rejected":
            return int(entrada.get("count", 0))
    return 0


def publicar_mensagens(mensagens: list[dict], routing_key: str = ROUTING_KEY_NORMAL) -> list[bool]:
    """
    Publica várias mensagens numa única conexão/canal, todas com a
    mesma `routing_key` -- ROUTING_KEY_NORMAL pro envio inicial de
    pesquisa (jobs/enviar_pesquisa.py) ou ROUTING_KEY_PRIORITARIO pros
    lembretes (jobs/lembrete_diario.py, jobs/lembrete_segundo.py). É
    rápido, só confirma que o RabbitMQ recebeu, não espera nenhum
    e-mail ser enviado de verdade (isso é trabalho do consumidor).

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

"""
Script de teste (rodar manualmente) -- demonstra AO VIVO o caminho de
falha completo: publica de propósito 1 mensagem sem os campos
obrigatórios direto na fila principal e deixa o consumidor de verdade
processá-la até ela cair na DLQ (Etapa 4 do trabalho: "caso de uso
representativo... com entradas, processamento e saídas esperadas").

Entrada: uma mensagem JSON válida (chega na fila normalmente -- o
publicador não valida o conteúdo, só publica) mas incompleta: só tem
"tipo": "convite", sem funcionario_nome/funcionario_email/token_codigo/
prazo_horas.

Processamento esperado, TODO ele feito pelo consumidor que já está
rodando de verdade (workers/consumidor_continuo.py, ou o chamado via
POST /executar/processar-fila-convites -- não precisa rodar nada além
deste script):
    1ª entrega -> _montar_email_convite tenta ler msg["token_codigo"],
                  estoura KeyError -> consumidor NÃO dá ack -> nack ->
                  dead-letter automático manda pra fila.enviar_convite.retry
    (espera TTL_RETRY_MS = 30s)
    2ª entrega -> mesmo KeyError -> retry de novo
    (espera mais 30s)
    3ª entrega -> mesmo KeyError -> x-death já mostra 3 rejeições dessa
                  fila -> consumidor publica manualmente na DLQ e SÓ AÍ
                  dá ack (mensagem sai da fila principal de vez)

Saída esperada: fila.enviar_convite.dlq com +1 mensagem, corpo igual
ao publicado aqui, e o header x-death com o histórico das 3 rejeições
(visível no painel do CloudAMQP, aba da fila -> "Get Message(s)").

Tempo total esperado: ~70-100s entre rodar este script e a mensagem
aparecer na DLQ, DESDE QUE exista um consumidor rodando continuamente
(workers/consumidor_continuo.py) ou sendo chamado por cron com
intervalo menor que 30s. Se o único consumidor em uso for o
"drena e sai" via cron (POST /executar/processar-fila-convites) com
intervalo maior que isso, cada chamada avança uma tentativa -- pode
levar até N execuções do cron pra fechar o ciclo, não ~100s corridos.

Autorização por papel (Etapa 3): publica com RABBITMQ_URL_PUBLISHER --
a mesma variável usada em produção por
clients/rabbitmq_client.py::publicar_mensagens. Enquanto o usuário
radar_publisher não existir de verdade (plano gratuito da CloudAMQP
não permite criar usuário novo -- ver RABBITMQ_AUTORIZACAO.md), essa
variável cai pra credencial única de sempre; o dia que existir, este
script já publica com ela sem precisar mudar nada aqui.

Retentativa: a conexão com um broker gratuito compartilhado pode cair,
ou o broker pode recusar a mensagem de verdade (exceção real). Nesses
casos este script tenta até 3 vezes, reabrindo a conexão entre uma
tentativa e outra, antes de desistir.

IMPORTANTE (bug corrigido): com `canal.confirm_delivery()` ativo, o
`pika` NUNCA devolve `True`/`False` no retorno de `basic_publish` --
ele sempre devolve `None` (ver padrão oficial em
https://pika.readthedocs.io/en/stable/examples/blocking_delivery_confirmations.html).
Quem indica se a publicação foi confirmada é a AUSÊNCIA de exceção, não
o valor de retorno. A versão anterior deste script guardava o retorno
numa variável e checava `if publicado:` -- como o retorno é sempre
`None` (valor "falso" em Python), ela reportava "não confirmado" SEMPRE,
mesmo quando a mensagem tinha sido publicada com sucesso (foi
exatamente isso que gerou várias mensagens duplicadas na DLQ ao rodar
este script mais de uma vez).

Como rodar (da raiz do projeto):
    python -m scripts.teste_falha_dlq
"""
import json
import time

import pika

from clients.rabbitmq_client import EXCHANGE, ROUTING_KEY_NORMAL, conectar_publicador

MAX_TENTATIVAS = 3
ESPERA_ENTRE_TENTATIVAS_S = 1.0


def publicar_mensagem_quebrada() -> None:
    mensagem = {
        "tipo": "convite",
        "teste_dlq": True,
    }
    corpo = json.dumps(mensagem).encode("utf-8")

    publicado = False
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        print(f"[teste_falha_dlq] Conectando como publicador (tentativa {tentativa}/{MAX_TENTATIVAS})...")
        conexao = conectar_publicador()
        try:
            canal = conexao.channel()
            canal.confirm_delivery()
            canal.basic_publish(
                exchange=EXCHANGE,
                routing_key=ROUTING_KEY_NORMAL,
                body=corpo,
                properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
                mandatory=True,
            )
            publicado = True
        except (pika.exceptions.UnroutableError, pika.exceptions.NackError) as e:
            print(f"[teste_falha_dlq] Broker recusou a mensagem (tentativa {tentativa}/{MAX_TENTATIVAS}): {e}")
            publicado = False
        except Exception as e:
            print(f"[teste_falha_dlq] Erro ao publicar (tentativa {tentativa}/{MAX_TENTATIVAS}): {e}")
            publicado = False
        finally:
            conexao.close()

        if publicado:
            break

        if tentativa < MAX_TENTATIVAS:
            print(
                f"[teste_falha_dlq] Falha real ao publicar -- "
                f"tentando de novo em {ESPERA_ENTRE_TENTATIVAS_S}s..."
            )
            time.sleep(ESPERA_ENTRE_TENTATIVAS_S)

    if not publicado:
        print(
            f"[teste_falha_dlq] Desisti depois de {MAX_TENTATIVAS} tentativas -- "
            "dessa vez é uma falha de verdade (veja o erro de cada tentativa "
            "acima): conexão caindo ou o broker recusando a mensagem. Confira "
            "RABBITMQ_URL/RABBITMQ_URL_PUBLISHER e se o serviço no Render está "
            "no ar antes de rodar de novo."
        )
        return

    print(f"[teste_falha_dlq] Mensagem de teste publicada: {mensagem}")
    print(
        "[teste_falha_dlq] Agora acompanhe os logs do consumidor no Render "
        "(o backend só roda lá, a thread contínua é iniciada por main.py) e o "
        "painel do CloudAMQP (fila.enviar_convite -> fila.enviar_convite.retry "
        "-> de volta -> 3x -> fila.enviar_convite.dlq). Deve levar entre ~70 e "
        "~100 segundos se o consumidor contínuo estiver rodando."
    )


if __name__ == "__main__":
    publicar_mensagem_quebrada()

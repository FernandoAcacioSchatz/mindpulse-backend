"""
Consumidor dos convites de pesquisa -- lê da fila.enviar_convite,
manda o e-mail de verdade (Brevo) e trata falha com retry + DLQ.

Roda em modo "drena um lote e sai" (não fica escutando pra sempre):
o Render free não tem processo persistente de graça, então esse
worker é chamado por HTTP (POST /executar/processar-fila-convites,
protegido por X-API-Key) periodicamente por um cron externo -- ver
Documento de arquitetura de mensageria. Cada chamada processa até
`max_mensagens` e devolve; se a fila estiver maior que isso, a
próxima chamada do cron continua de onde parou.
"""
import json

import pika

from clients.brevo_client import enviar_email
from clients.rabbitmq_client import (
    FILA_DLQ,
    FILA_PRINCIPAL,
    FILA_RETRY,
    MAX_TENTATIVAS,
    conectar,
    declarar_topologia,
)
from config import BASE_URL_FRONTEND


def _montar_email(msg: dict) -> tuple[str, str]:
    link = f"{BASE_URL_FRONTEND}/pulse/{msg['token_codigo']}"
    corpo_html = f"""
        <p>Olá, {msg['funcionario_nome']}!</p>
        <p>Você foi convidado a participar de uma pesquisa rápida e anônima sobre o
        ambiente de trabalho. Leva menos de 5 minutos.</p>
        <p><a href="{link}">Responder pesquisa</a></p>
        <p>Este link é pessoal e expira em {msg['prazo_horas']} horas.</p>
    """
    return "Pesquisa de Clima e Bem-estar — sua participação é importante", corpo_html


def processar_lote(max_mensagens: int = 50) -> dict:
    conexao = conectar()
    processadas = 0
    sucesso = 0
    reencaminhadas = 0
    mortas = 0

    try:
        canal = conexao.channel()
        declarar_topologia(canal)
        canal.basic_qos(prefetch_count=10)

        while processadas < max_mensagens:
            metodo, _propriedades, corpo = canal.basic_get(queue=FILA_PRINCIPAL, auto_ack=False)
            if metodo is None:
                break  # fila vazia por enquanto -- nada mais a fazer nessa chamada

            processadas += 1
            msg = json.loads(corpo)

            try:
                assunto, corpo_html = _montar_email(msg)
                enviar_email(
                    destinatario_email=msg["funcionario_email"],
                    destinatario_nome=msg["funcionario_nome"],
                    assunto=assunto,
                    corpo_html=corpo_html,
                )
                canal.basic_ack(delivery_tag=metodo.delivery_tag)
                sucesso += 1
            except Exception as e:
                # Tira da fila principal de qualquer jeito -- a "nova
                # tentativa" é uma cópia nova publicada na fila de
                # retry (ou na DLQ), não um nack/requeue nativo, porque
                # precisamos do atraso do TTL, não uma redelivery
                # instantânea.
                canal.basic_ack(delivery_tag=metodo.delivery_tag)

                tentativas = msg.get("tentativas", 0) + 1
                msg["tentativas"] = tentativas
                corpo_novo = json.dumps(msg).encode("utf-8")

                if tentativas >= MAX_TENTATIVAS:
                    canal.basic_publish(
                        exchange="",
                        routing_key=FILA_DLQ,
                        body=corpo_novo,
                        properties=pika.BasicProperties(delivery_mode=2),
                    )
                    mortas += 1
                    print(f"[consumidor_convites] {msg['funcionario_email']} -> DLQ após {tentativas} tentativas: {e}")
                else:
                    canal.basic_publish(
                        exchange="",
                        routing_key=FILA_RETRY,
                        body=corpo_novo,
                        properties=pika.BasicProperties(delivery_mode=2),
                    )
                    reencaminhadas += 1
                    print(f"[consumidor_convites] {msg['funcionario_email']} -> retry (tentativa {tentativas}): {e}")
    finally:
        conexao.close()

    resultado = {
        "processadas": processadas,
        "sucesso": sucesso,
        "reencaminhadas_para_retry": reencaminhadas,
        "mortas_dlq": mortas,
    }
    print(f"[consumidor_convites] {resultado}")
    return resultado

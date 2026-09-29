"""
Consumidor dos convites de pesquisa -- lê da fila.enviar_convite,
manda o e-mail de verdade (Brevo) e trata falha com nack + dead-letter
automático (ver clients/rabbitmq_client.py pra topologia).

Ack manual conforme Etapa 2.a/2.d do trabalho de Sistemas
Distribuídos: uma mensagem só sai da fila principal de vez quando o
Brevo confirma o envio (ack). Se falhar, NUNCA damos ack -- damos
nack(requeue=False), e é o dead-letter-exchange da própria fila que
manda a mensagem pra fila de retry sozinho. As tentativas são contadas
pelo header `x-death` (nativo do RabbitMQ), não por um campo manual no
corpo da mensagem.

Idempotência (Etapa 2.d): antes de mandar o e-mail, confere se aquele
token já foi marcado como enviado -- protege contra duplicidade se a
mesma mensagem for entregue duas vezes (ex: o worker caiu depois de
mandar o e-mail mas antes de conseguir confirmar o ack).

Roda em modo "drena um lote e sai" (não fica escutando pra sempre):
o Render free não tem processo persistente de graça, então esse
worker é chamado por HTTP (POST /executar/processar-fila-convites,
protegido por X-API-Key) periodicamente por um cron externo. Cada
chamada processa até `max_mensagens` e devolve; se a fila estiver
maior que isso, a próxima chamada do cron continua de onde parou.
"""
import json
from datetime import datetime, timezone

from clients.brevo_client import enviar_email
from clients.rabbitmq_client import (
    FILA_DLQ,
    FILA_PRINCIPAL,
    MAX_TENTATIVAS,
    conectar,
    declarar_topologia,
    tentativas_anteriores,
)
from clients.supabase_client import supabase
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


def _ja_enviado(token_id: str) -> bool:
    resposta = (
        supabase.table("token_resposta")
        .select("convite_enviado_em")
        .eq("id", token_id)
        .maybe_single()
        .execute()
    )
    linha = resposta.data if resposta else None
    return bool(linha and linha.get("convite_enviado_em"))


def _marcar_enviado(token_id: str) -> None:
    supabase.table("token_resposta").update(
        {"convite_enviado_em": datetime.now(timezone.utc).isoformat()}
    ).eq("id", token_id).execute()


def _atualizar_status_item(envio_item_id: str | None, status: str, mensagem_id_brevo: str = None, erro: str = None) -> None:
    if not envio_item_id:
        return  # mensagem antiga, sem esse campo -- não quebra, só não atualiza status por lote
    dados = {"status": status, "atualizado_em": datetime.now(timezone.utc).isoformat()}
    if mensagem_id_brevo is not None:
        dados["mensagem_id_brevo"] = mensagem_id_brevo
    if erro is not None:
        dados["erro"] = erro[:500]
    supabase.table("envio_lote_item").update(dados).eq("id", envio_item_id).execute()


def processar_lote(max_mensagens: int = 50) -> dict:
    conexao = conectar()
    processadas = sucesso = reencaminhadas = mortas = duplicadas = 0

    try:
        canal = conexao.channel()
        declarar_topologia(canal)
        canal.basic_qos(prefetch_count=10)

        while processadas < max_mensagens:
            metodo, propriedades, corpo = canal.basic_get(queue=FILA_PRINCIPAL, auto_ack=False)
            if metodo is None:
                break  # fila vazia por enquanto -- nada mais a fazer nessa chamada

            processadas += 1
            msg = json.loads(corpo)
            token_id = msg.get("token_id")
            envio_item_id = msg.get("envio_item_id")

            if token_id and _ja_enviado(token_id):
                # Idempotência: essa mensagem já foi processada com sucesso
                # antes (entrega duplicada) -- confirma sem reenviar.
                canal.basic_ack(delivery_tag=metodo.delivery_tag)
                duplicadas += 1
                print(f"[consumidor_convites] {msg.get('funcionario_email')} já tinha sido enviado -- ignorando duplicata.")
                continue

            try:
                assunto, corpo_html = _montar_email(msg)
                resposta_brevo = enviar_email(
                    destinatario_email=msg["funcionario_email"],
                    destinatario_nome=msg["funcionario_nome"],
                    assunto=assunto,
                    corpo_html=corpo_html,
                    tags=[envio_item_id] if envio_item_id else None,
                )
                if token_id:
                    _marcar_enviado(token_id)
                _atualizar_status_item(envio_item_id, "enviado", mensagem_id_brevo=resposta_brevo.get("messageId"))

                # Só agora, com a confirmação real do Brevo, a mensagem sai da fila.
                canal.basic_ack(delivery_tag=metodo.delivery_tag)
                sucesso += 1
            except Exception as e:
                tentativa_atual = tentativas_anteriores(propriedades) + 1

                if tentativa_atual >= MAX_TENTATIVAS:
                    # Esgotou as tentativas -- move manualmente pra DLQ
                    # (preserva o corpo e os headers originais, incluindo o
                    # histórico de x-death, útil pra investigar depois) e
                    # só aí confirma a saída da fila principal.
                    canal.basic_publish(
                        exchange="",
                        routing_key=FILA_DLQ,
                        body=corpo,
                        properties=propriedades,
                    )
                    canal.basic_ack(delivery_tag=metodo.delivery_tag)
                    _atualizar_status_item(envio_item_id, "falhou", erro=str(e))
                    mortas += 1
                    print(f"[consumidor_convites] {msg.get('funcionario_email')} -> DLQ após {tentativa_atual} tentativas: {e}")
                else:
                    # NÃO dá ack -- nack(requeue=False) aciona o
                    # dead-letter-exchange da própria fila principal, que
                    # manda pra fila de retry sozinho (ver rabbitmq_client.py).
                    canal.basic_nack(delivery_tag=metodo.delivery_tag, requeue=False)
                    reencaminhadas += 1
                    print(f"[consumidor_convites] {msg.get('funcionario_email')} -> retry (tentativa {tentativa_atual}): {e}")
    finally:
        conexao.close()

    resultado = {
        "processadas": processadas,
        "sucesso": sucesso,
        "duplicadas_ignoradas": duplicadas,
        "reencaminhadas_para_retry": reencaminhadas,
        "mortas_dlq": mortas,
    }
    print(f"[consumidor_convites] {resultado}")
    return resultado

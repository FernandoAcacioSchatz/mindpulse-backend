from clients.brevo_client import enviar_email
from clients.rabbitmq_client import FILA_DLQ, conectar_consumidor
from config import ADMIN_EMAILS


def _consultar_profundidade_dlq() -> int:
    conexao = conectar_consumidor()
    try:
        canal = conexao.channel()
        resposta = canal.queue_declare(queue=FILA_DLQ, passive=True)
        return resposta.method.message_count
    finally:
        conexao.close()


def _montar_alerta(quantidade: int) -> tuple[str, str]:
    assunto = f"[Radar] {quantidade} convite(s) parado(s) na fila morta"
    corpo_html = f"""
        <p>A fila <code>{FILA_DLQ}</code> tem <strong>{quantidade}</strong>
        mensagem(ns) que esgotaram as tentativas de envio e precisam de
        investigação manual (e-mail inválido, Brevo rejeitando, etc.).</p>
        <p>Confira no painel do CloudAMQP (RabbitMQ Manager → Queues and
        Streams → {FILA_DLQ}) o conteúdo de cada mensagem antes de decidir
        reprocessar ou descartar.</p>
    """
    return assunto, corpo_html


def rodar() -> dict:
    quantidade = _consultar_profundidade_dlq()

    if quantidade == 0:
        resultado = {"mensagens_na_dlq": 0, "alerta_enviado": False}
        print(f"[monitorar_dlq] {resultado}")
        return resultado

    assunto, corpo_html = _montar_alerta(quantidade)
    destinatarios_notificados = []
    for email_admin in ADMIN_EMAILS:
        try:
            enviar_email(
                destinatario_email=email_admin,
                destinatario_nome="Equipe Radar",
                assunto=assunto,
                corpo_html=corpo_html,
            )
            destinatarios_notificados.append(email_admin)
        except Exception as e:
            print(f"[monitorar_dlq] Falha ao alertar {email_admin}: {e}")

    resultado = {
        "mensagens_na_dlq": quantidade,
        "alerta_enviado": bool(destinatarios_notificados),
        "notificados": destinatarios_notificados,
    }
    print(f"[monitorar_dlq] {resultado}")
    return resultado

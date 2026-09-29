"""
Cliente Brevo — equivalente aos nodes HTTP Request de envio de
e-mail no n8n.
"""
import httpx
from config import BREVO_API_KEY, BREVO_SENDER_EMAIL


def enviar_email(
    destinatario_email: str,
    destinatario_nome: str,
    assunto: str,
    corpo_html: str,
    tags: list[str] | None = None,
) -> dict:
    """
    `tags`: usado pra marcar o e-mail com o id do item do lote
    (envio_lote_item.id) -- a Brevo devolve essa mesma tag no webhook
    de entrega/bounce, o que deixa correlacionar o evento assíncrono
    de volta com a linha certa na tabela de status (ver Etapa 2.c do
    trabalho de mensageria e workers/consumidor_convites.py).
    """
    corpo_requisicao = {
        "sender": {"name": "Radar", "email": BREVO_SENDER_EMAIL},
        "to": [{"email": destinatario_email, "name": destinatario_nome}],
        "subject": assunto,
        "htmlContent": corpo_html,
    }
    if tags:
        corpo_requisicao["tags"] = [str(t) for t in tags]

    response = httpx.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json"},
        json=corpo_requisicao,
        timeout=15,
    )
    response.raise_for_status()
    return response.json()

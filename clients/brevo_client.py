"""
Cliente Brevo — equivalente aos nodes HTTP Request de envio de
e-mail no n8n.
"""
import httpx
from config import BREVO_API_KEY, BREVO_SENDER_EMAIL


def enviar_email(destinatario_email: str, destinatario_nome: str, assunto: str, corpo_html: str) -> dict:
    response = httpx.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json"},
        json={
            "sender": {"name": "MindPulse", "email": BREVO_SENDER_EMAIL},
            "to": [{"email": destinatario_email, "name": destinatario_nome}],
            "subject": assunto,
            "htmlContent": corpo_html,
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.json()

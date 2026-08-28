"""
Notifica a equipe Radar (ADMIN_EMAILS) quando alguém preenche o
formulário de contato do site comercial.

Chamado pelo Supabase Database Webhook (evento INSERT na tabela
'lead') -- mesmo mecanismo já usado pro alerta crítico, só que
apontando pra essa rota em vez daquela.
"""
from clients.brevo_client import enviar_email
from config import ADMIN_EMAILS


def processar(payload: dict) -> dict:
    record = payload.get("record", {})

    if not ADMIN_EMAILS:
        return {"acao": "nenhuma", "motivo": "ADMIN_EMAILS nao configurado"}

    nome = record.get("nome") or "Alguém"
    email = record.get("email") or "não informado"
    empresa = record.get("empresa") or "não informada"
    mensagem = record.get("mensagem") or "(sem mensagem)"

    enviados = 0
    for destino in ADMIN_EMAILS:
        enviar_email(
            destinatario_email=destino,
            destinatario_nome="Radar",
            assunto=f"Novo contato no site: {nome}",
            corpo_html=f"""
                <p>Novo contato recebido pelo formulário do site.</p>
                <p><strong>Nome:</strong> {nome}<br>
                <strong>E-mail:</strong> {email}<br>
                <strong>Empresa:</strong> {empresa}</p>
                <p><strong>Mensagem:</strong><br>{mensagem}</p>
            """,
        )
        enviados += 1

    return {"acao": "notificado", "emails_enviados": enviados}

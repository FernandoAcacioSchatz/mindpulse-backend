"""
Equivalente ao workflow n8n 'Lembrete Diario de Pesquisa (v2 corrigido)'.
Este é o primeiro a ser portado (o mais simples), seguindo a ordem
sugerida no Documento 12.

Roda todo dia às 8h (agendado em main.py via APScheduler), mas também
pode ser disparado manualmente via POST /executar/lembrete-diario,
útil pra testar sem esperar o horário.
"""
from datetime import datetime, timezone

from clients.supabase_client import supabase
from clients.brevo_client import enviar_email
from config import BASE_URL_FRONTEND

HORAS_MINIMAS_ANTES_DO_LEMBRETE = 6


def rodar() -> dict:
    agora = datetime.now(timezone.utc)

    tokens = (
        supabase.table("token_resposta")
        .select("*")
        .eq("respondido", False)
        .gt("expira_em", agora.isoformat())
        .execute()
        .data
    )

    enviados = 0

    for token in tokens:
        criado = datetime.fromisoformat(token["criado_em"])
        horas_desde_envio = (agora - criado).total_seconds() / 3600
        if horas_desde_envio < HORAS_MINIMAS_ANTES_DO_LEMBRETE:
            continue

        funcionario = (
            supabase.table("funcionario")
            .select("*")
            .eq("id", token["funcionario_id"])
            .single()
            .execute()
            .data
        )

        expira = datetime.fromisoformat(token["expira_em"])
        horas_restantes = max(0, round((expira - agora).total_seconds() / 3600))
        link = f"{BASE_URL_FRONTEND}/pulse/{token['codigo']}"

        enviar_email(
            destinatario_email=funcionario["email"],
            destinatario_nome=funcionario["nome"],
            assunto="Lembrete: sua pesquisa ainda está aberta",
            corpo_html=f"""
                <p>Olá, {funcionario['nome']}!</p>
                <p>Notamos que você ainda não respondeu à pesquisa de clima e bem-estar.
                Faltam aproximadamente {horas_restantes} horas para o link expirar.</p>
                <p><a href="{link}">Responder agora</a></p>
                <p>Leva menos de 5 minutos e sua resposta é anônima.</p>
            """,
        )
        enviados += 1

    resultado = {"tokens_verificados": len(tokens), "lembretes_enviados": enviados}
    print(f"[lembrete_diario] {resultado}")
    return resultado

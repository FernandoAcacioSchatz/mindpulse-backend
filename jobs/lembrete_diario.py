from datetime import datetime, timezone

from clients.supabase_client import supabase
from clients.brevo_client import enviar_email
from config import BASE_URL_FRONTEND

HORAS_ATE_O_PRIMEIRO_LEMBRETE = 24


def rodar() -> dict:
    agora = datetime.now(timezone.utc)

    tokens = (
        supabase.table("token_resposta")
        .select("*, pesquisa:pesquisa_id(status)")
        .eq("respondido", False)
        .is_("lembrete1_enviado_em", "null")
        .gt("expira_em", agora.isoformat())
        .execute()
        .data
    )

    enviados = 0

    for token in tokens:
        # Pesquisa já encerrada (por qualquer motivo) -- não faz
        # sentido lembrar de responder algo que já foi analisado.
        if not token.get("pesquisa") or token["pesquisa"]["status"] != "enviada":
            continue

        criado = datetime.fromisoformat(token["criado_em"])
        horas_desde_envio = (agora - criado).total_seconds() / 3600
        if horas_desde_envio < HORAS_ATE_O_PRIMEIRO_LEMBRETE:
            continue

        resposta_func = (
            supabase.table("funcionario")
            .select("nome, email")
            .eq("id", token["funcionario_id"])
            .single()
            .execute()
        )
        funcionario = resposta_func.data if resposta_func else None
        if not funcionario:
            continue

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
        supabase.table("token_resposta").update(
            {"lembrete1_enviado_em": agora.isoformat()}
        ).eq("id", token["id"]).execute()
        enviados += 1

    resultado = {"tokens_verificados": len(tokens), "lembretes_enviados": enviados}
    print(f"[lembrete_diario] {resultado}")
    return resultado

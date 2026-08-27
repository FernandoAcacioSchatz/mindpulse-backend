"""
Segundo (e último) lembrete da cascata: dispara 3h depois do
PRIMEIRO lembrete, só pra quem ainda não respondeu e ainda não
recebeu esse segundo aviso.

Roda todo dia às 11h (3h depois do primeiro lembrete, às 8h).
Também pode ser disparado manualmente via POST /executar/lembrete-segundo.
"""
from datetime import datetime, timezone

from clients.supabase_client import supabase
from clients.brevo_client import enviar_email
from config import BASE_URL_FRONTEND

HORAS_ATE_O_SEGUNDO_LEMBRETE = 3


def rodar() -> dict:
    agora = datetime.now(timezone.utc)

    tokens = (
        supabase.table("token_resposta")
        .select("*, pesquisa:pesquisa_id(status)")
        .eq("respondido", False)
        .not_.is_("lembrete1_enviado_em", "null")
        .is_("lembrete2_enviado_em", "null")
        .gt("expira_em", agora.isoformat())
        .execute()
        .data
    )

    enviados = 0

    for token in tokens:
        if not token.get("pesquisa") or token["pesquisa"]["status"] != "enviada":
            continue

        lembrete1 = datetime.fromisoformat(token["lembrete1_enviado_em"])
        horas_desde_lembrete1 = (agora - lembrete1).total_seconds() / 3600
        if horas_desde_lembrete1 < HORAS_ATE_O_SEGUNDO_LEMBRETE:
            continue

        resposta_func = supabase.table("funcionario").select("nome, email").eq("id", token["funcionario_id"]).single().execute()
        funcionario = resposta_func.data if resposta_func else None
        if not funcionario:
            continue

        expira = datetime.fromisoformat(token["expira_em"])
        horas_restantes = max(0, round((expira - agora).total_seconds() / 3600))
        link = f"{BASE_URL_FRONTEND}/pulse/{token['codigo']}"

        enviar_email(
            destinatario_email=funcionario["email"],
            destinatario_nome=funcionario["nome"],
            assunto="Último lembrete: sua pesquisa fecha em breve",
            corpo_html=f"""
                <p>Olá, {funcionario['nome']}!</p>
                <p>Esse é o último lembrete -- sua resposta ainda não chegou, e o link
                expira em aproximadamente {horas_restantes} horas.</p>
                <p><a href="{link}">Responder agora</a></p>
                <p>Leva menos de 5 minutos e sua resposta é anônima.</p>
            """,
        )
        supabase.table("token_resposta").update({"lembrete2_enviado_em": agora.isoformat()}).eq("id", token["id"]).execute()
        enviados += 1

    resultado = {"tokens_verificados": len(tokens), "lembretes_enviados": enviados}
    print(f"[lembrete_segundo] {resultado}")
    return resultado

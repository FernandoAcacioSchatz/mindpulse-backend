from datetime import datetime, timezone

from clients.supabase_client import supabase
from clients.rabbitmq_client import ROUTING_KEY_PRIORITARIO, publicar_mensagens

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

    pendentes = []
    for token in tokens:
        if not token.get("pesquisa") or token["pesquisa"]["status"] != "enviada":
            continue

        lembrete1 = datetime.fromisoformat(token["lembrete1_enviado_em"])
        horas_desde_lembrete1 = (agora - lembrete1).total_seconds() / 3600
        if horas_desde_lembrete1 < HORAS_ATE_O_SEGUNDO_LEMBRETE:
            continue

        pendentes.append(token)

    if not pendentes:
        resultado = {"tokens_verificados": len(tokens), "lembretes_enfileirados": 0}
        print(f"[lembrete_segundo] {resultado}")
        return resultado

    funcionarios = (
        supabase.table("funcionario")
        .select("id, nome, email")
        .in_("id", [t["funcionario_id"] for t in pendentes])
        .execute()
        .data
    )
    funcionario_por_id = {f["id"]: f for f in funcionarios}

    mensagens = []
    for token in pendentes:
        funcionario = funcionario_por_id.get(token["funcionario_id"])
        if not funcionario:
            continue
        mensagens.append({
            "tipo": "lembrete_2",
            "token_id": token["id"],
            "token_codigo": token["codigo"],
            "funcionario_nome": funcionario["nome"],
            "funcionario_email": funcionario["email"],
            "expira_em": token["expira_em"],
        })

    resultados = publicar_mensagens(mensagens, routing_key=ROUTING_KEY_PRIORITARIO)
    enfileirados = sum(1 for ok in resultados if ok)

    resultado = {"tokens_verificados": len(tokens), "lembretes_enfileirados": enfileirados}
    print(f"[lembrete_segundo] {resultado}")
    return resultado

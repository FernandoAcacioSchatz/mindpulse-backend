"""
Primeiro lembrete da cascata: dispara 24h depois do convite inicial,
só pra quem ainda não respondeu e ainda não recebeu esse lembrete.

Roda todo dia às 8h. Também pode ser disparado manualmente via
POST /executar/lembrete-diario.

Migrado pra mensageria (Etapa 2.b do trabalho): em vez de mandar o
e-mail direto por aqui, esse job só DECIDE quem precisa de lembrete e
publica 1 mensagem por pessoa na fila de prioridade (routing key
email.prioritario) -- quem manda o e-mail de verdade é o mesmo
consumidor que processa os convites (workers/consumidor_continuo.py),
só que essa fila é sempre conferida primeiro, antes da fila normal.

Por isso o campo lembrete1_enviado_em só é marcado pelo CONSUMIDOR,
depois que o Brevo confirma o envio -- nunca aqui. Se a publicação
falhar, o token simplesmente continua sem o campo marcado e é
tentado de novo na próxima execução (mesmo raciocínio de idempotência
de jobs/enviar_pesquisa.py, só que mais simples: aqui não existe
token nem item pra desfazer, só um campo que fica em branco até dar
certo).
"""
from datetime import datetime, timezone

from clients.supabase_client import supabase
from clients.rabbitmq_client import ROUTING_KEY_PRIORITARIO, publicar_mensagens

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

    pendentes = []
    for token in tokens:
        # Pesquisa já encerrada (por qualquer motivo) -- não faz
        # sentido lembrar de responder algo que já foi analisado.
        if not token.get("pesquisa") or token["pesquisa"]["status"] != "enviada":
            continue

        criado = datetime.fromisoformat(token["criado_em"])
        horas_desde_envio = (agora - criado).total_seconds() / 3600
        if horas_desde_envio < HORAS_ATE_O_PRIMEIRO_LEMBRETE:
            continue

        pendentes.append(token)

    if not pendentes:
        resultado = {"tokens_verificados": len(tokens), "lembretes_enfileirados": 0}
        print(f"[lembrete_diario] {resultado}")
        return resultado

    # Busca os funcionários em lote (1 SELECT), não 1 por token.
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
            "tipo": "lembrete_1",
            "token_id": token["id"],
            "token_codigo": token["codigo"],
            "funcionario_nome": funcionario["nome"],
            "funcionario_email": funcionario["email"],
            "expira_em": token["expira_em"],
        })

    resultados = publicar_mensagens(mensagens, routing_key=ROUTING_KEY_PRIORITARIO)
    enfileirados = sum(1 for ok in resultados if ok)

    resultado = {"tokens_verificados": len(tokens), "lembretes_enfileirados": enfileirados}
    print(f"[lembrete_diario] {resultado}")
    return resultado

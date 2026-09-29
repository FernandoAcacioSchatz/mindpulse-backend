"""
Equivalente ao workflow n8n 'Enviar Pesquisa (v2 corrigido)' —
migração completa.

Melhoria em relação à versão n8n: processa TODAS as pesquisas
agendadas numa execução, não só 1 (era uma limitação conhecida
do node "limit: 1", documentada no Documento 10).

Idempotente: se rodar 2x por engano, não duplica token nem manda
e-mail 2x — verifica se o token já existe antes de criar.

Envio de e-mail via RabbitMQ (CloudAMQP), não mais direto por aqui:
criar token é rápido (banco), mas mandar e-mail é uma chamada de
rede -- pra uma empresa grande, esperar todo mundo enviar antes de
responder a requisição tem o mesmo risco que já vimos em
/encerrar-pesquisa (timeout do proxy na frente do Render). Agora
esse job só cria os tokens e PUBLICA 1 mensagem por convite na fila
-- quem manda o e-mail de verdade é o worker separado
(workers/consumidor_convites.py). Ver clients/rabbitmq_client.py
pra topologia (exchange, filas, retry, DLQ).

IMPORTANTE: no plano gratuito da Brevo existe um teto de 300
e-mails/dia -- isso não é resolvido por código nenhum, é limite
de conta. Cliente grande = upgrade de plano na Brevo, não mais fila.
"""
from datetime import datetime, timezone, timedelta

from clients.supabase_client import supabase
from clients.rabbitmq_client import publicar_convites


def rodar() -> dict:
    pesquisas = (
        supabase.table("pesquisa")
        .select("id, nome, ciclo_id, prazo_horas")
        .eq("status", "agendada")
        .execute()
        .data
    )

    resultado_geral = {"pesquisas_processadas": 0, "convites_enfileirados": 0, "detalhes": []}

    for pesquisa in pesquisas:
        detalhe = processar_uma_pesquisa(pesquisa)
        resultado_geral["pesquisas_processadas"] += 1
        resultado_geral["convites_enfileirados"] += detalhe["convites_enfileirados"]
        resultado_geral["detalhes"].append(detalhe)

    print(f"[enviar_pesquisa] {resultado_geral}")
    return resultado_geral


def processar_uma_pesquisa(pesquisa: dict) -> dict:
    pesquisa_id = pesquisa["id"]
    prazo_horas = pesquisa.get("prazo_horas") or 24

    resposta_ciclo = supabase.table("ciclo").select("empresa_id").eq("id", pesquisa["ciclo_id"]).single().execute()
    ciclo = resposta_ciclo.data if resposta_ciclo else None
    if not ciclo:
        raise ValueError(f"Ciclo {pesquisa['ciclo_id']} não encontrado ao processar pesquisa {pesquisa_id}.")
    empresa_id = ciclo["empresa_id"]

    funcionarios = (
        supabase.table("funcionario")
        .select("id, nome, email")
        .eq("empresa_id", empresa_id)
        .eq("ativo", True)
        .execute()
        .data
    )

    expira_em = (datetime.now(timezone.utc) + timedelta(hours=prazo_horas)).isoformat()

    # ---- Passo 1: cria todos os tokens primeiro (rápido, só banco, sequencial está ok) ----
    fila_de_envio = []
    for funcionario in funcionarios:
        resposta_existente = (
            supabase.table("token_resposta")
            .select("id")
            .eq("pesquisa_id", pesquisa_id)
            .eq("funcionario_id", funcionario["id"])
            .maybe_single()
            .execute()
        )
        existente = resposta_existente.data if resposta_existente else None
        if existente:
            continue  # já processado numa execução anterior — idempotência

        resposta_token = (
            supabase.table("token_resposta")
            .insert({"pesquisa_id": pesquisa_id, "funcionario_id": funcionario["id"], "expira_em": expira_em})
            .execute()
        )
        if not resposta_token or not resposta_token.data:
            print(f"[enviar_pesquisa] Falha ao criar token pra funcionário {funcionario['id']}, pulando.")
            continue
        token = resposta_token.data[0]
        fila_de_envio.append((funcionario, token))

    # ---- Passo 2: publica 1 mensagem por convite no RabbitMQ ----
    # (quem manda o e-mail de verdade é workers/consumidor_convites.py,
    # chamado separadamente -- ver Documento de arquitetura de mensageria)
    mensagens = [
        {
            "pesquisa_id": pesquisa_id,
            "ciclo_id": pesquisa["ciclo_id"],
            "funcionario_id": funcionario["id"],
            "funcionario_nome": funcionario["nome"],
            "funcionario_email": funcionario["email"],
            "token_codigo": token["codigo"],
            "prazo_horas": prazo_horas,
            "tentativas": 0,
        }
        for funcionario, token in fila_de_envio
    ]
    publicar_convites(mensagens)

    # "enviada" agora significa "despachada pra fila", não "todo mundo já
    # recebeu o e-mail" -- é o momento certo pra começar a contar o prazo
    # de resposta de qualquer forma (o prazo é sobre a pesquisa, não sobre
    # quando cada e-mail individual saiu da fila).
    supabase.table("pesquisa").update(
        {"status": "enviada", "enviada_em": datetime.now(timezone.utc).isoformat()}
    ).eq("id", pesquisa_id).execute()

    return {
        "pesquisa_id": pesquisa_id,
        "nome": pesquisa["nome"],
        "funcionarios_totais": len(funcionarios),
        "convites_enfileirados": len(mensagens),
    }

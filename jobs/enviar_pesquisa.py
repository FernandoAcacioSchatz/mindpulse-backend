import uuid
from datetime import datetime, timezone, timedelta

from clients.supabase_client import supabase
from clients.rabbitmq_client import publicar_mensagens


def rodar() -> dict:
    pesquisas = (
        supabase.table("pesquisa")
        .select("id, nome, ciclo_id, prazo_horas, status")
        .in_("status", ["agendada", "enviada"])
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


def preparar_lote(pesquisa: dict) -> dict:
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

    tokens_existentes = (
        supabase.table("token_resposta")
        .select("funcionario_id")
        .eq("pesquisa_id", pesquisa_id)
        .execute()
        .data
    )
    ids_com_token = {t["funcionario_id"] for t in tokens_existentes}
    pendentes = [f for f in funcionarios if f["id"] not in ids_com_token]

    resultado_base = {
        "pesquisa": pesquisa,
        "pesquisa_id": pesquisa_id,
        "funcionarios_totais": len(funcionarios),
        "convites_enfileirados": 0,
        "lote_id": None,
        "mensagens": [],
        "fila_de_envio": [],
    }
    if not pendentes:
        return resultado_base

    lote_id = str(uuid.uuid4())
    expira_em = (datetime.now(timezone.utc) + timedelta(hours=prazo_horas)).isoformat()

    tokens_novos = (
        supabase.table("token_resposta")
        .insert([{"pesquisa_id": pesquisa_id, "funcionario_id": f["id"], "expira_em": expira_em} for f in pendentes])
        .execute()
        .data
    )
    token_por_funcionario = {t["funcionario_id"]: t for t in tokens_novos}

    try:
        itens_novos = (
            supabase.table("envio_lote_item")
            .insert([
                {
                    "lote_id": lote_id,
                    "pesquisa_id": pesquisa_id,
                    "token_id": token_por_funcionario[f["id"]]["id"],
                    "funcionario_id": f["id"],
                    "status": "pendente",
                }
                for f in pendentes
            ])
            .execute()
            .data
        )
    except Exception:
        supabase.table("token_resposta").delete().in_("id", [t["id"] for t in tokens_novos]).execute()
        raise
    item_por_funcionario = {i["funcionario_id"]: i for i in itens_novos}

    fila_de_envio = [(f, token_por_funcionario[f["id"]], item_por_funcionario[f["id"]]) for f in pendentes]
    mensagens = [
        {
            "lote_id": lote_id,
            "pesquisa_id": pesquisa_id,
            "ciclo_id": pesquisa["ciclo_id"],
            "funcionario_id": funcionario["id"],
            "funcionario_nome": funcionario["nome"],
            "funcionario_email": funcionario["email"],
            "token_id": token["id"],
            "token_codigo": token["codigo"],
            "envio_item_id": envio_item["id"],
            "prazo_horas": prazo_horas,
        }
        for funcionario, token, envio_item in fila_de_envio
    ]

    resultado_base.update({
        "convites_enfileirados": len(fila_de_envio),
        "lote_id": lote_id,
        "mensagens": mensagens,
        "fila_de_envio": fila_de_envio,
    })
    return resultado_base


def publicar_e_finalizar(preparo: dict) -> dict:
    pesquisa_id = preparo["pesquisa_id"]
    fila_de_envio = preparo["fila_de_envio"]
    if not fila_de_envio:
        return {**preparo, "falhas_ao_enfileirar": []}

    resultados = publicar_mensagens(preparo["mensagens"])

    falhas = []
    for (funcionario, token, envio_item), sucesso in zip(fila_de_envio, resultados):
        if not sucesso:
            item_apagado = (
                supabase.table("envio_lote_item")
                .delete()
                .eq("id", envio_item["id"])
                .eq("status", "pendente")
                .execute()
                .data
            )
            if not item_apagado:
                print(f"[enviar_pesquisa] Convite pra {funcionario['email']} -- publicação reportou falha, mas o consumidor já tinha processado antes. Nada foi desfeito.")
                continue

            supabase.table("token_resposta").delete().eq("id", token["id"]).execute()
            falhas.append(funcionario["email"])
            print(f"[enviar_pesquisa] Convite pra {funcionario['email']} falhou após retentativas -- token e item de status desfeitos, será tentado de novo na próxima execução.")

    sucesso_total = not falhas
    if sucesso_total and preparo["pesquisa"].get("status") != "enviada":
        supabase.table("pesquisa").update(
            {"status": "enviada", "enviada_em": datetime.now(timezone.utc).isoformat()}
        ).eq("id", pesquisa_id).execute()
    elif falhas:
        print(f"[enviar_pesquisa] Pesquisa {pesquisa_id}, lote {preparo['lote_id']} -- {len(falhas)} convite(s) falharam e podem ser reenviados depois.")

    return {**preparo, "convites_enfileirados": len(fila_de_envio) - len(falhas), "falhas_ao_enfileirar": falhas}


def processar_uma_pesquisa(pesquisa: dict) -> dict:
    preparo = preparar_lote(pesquisa)
    if not preparo["fila_de_envio"]:
        return {
            "pesquisa_id": preparo["pesquisa_id"],
            "nome": pesquisa["nome"],
            "lote_id": None,
            "funcionarios_totais": preparo["funcionarios_totais"],
            "convites_enfileirados": 0,
        }
    final = publicar_e_finalizar(preparo)
    resultado = {
        "pesquisa_id": final["pesquisa_id"],
        "nome": pesquisa["nome"],
        "lote_id": final["lote_id"],
        "funcionarios_totais": final["funcionarios_totais"],
        "convites_enfileirados": final["convites_enfileirados"],
    }
    if final["falhas_ao_enfileirar"]:
        resultado["falhas_ao_enfileirar"] = final["falhas_ao_enfileirar"]
    return resultado

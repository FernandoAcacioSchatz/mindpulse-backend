from datetime import datetime, timezone
from collections import defaultdict, Counter

from clients.supabase_client import supabase
from clients.gemini_client import analisar_ciclo
from ml.qualidade_resposta import avaliar_qualidade, resumo_qualidade_ciclo
from ml.classificador_comentarios import classificar_comentario
from ml.analise_texto import analisar_comentario
from ml.classificador_knn import classificar_por_knn
from ml.indice_preditivo import avaliar as avaliar_indice

LIMITE_INDICADOR_BAIXO = 2.5
LIMITE_QUEDA_BRUSCA = 0.5
MINIMO_RESPOSTAS_POR_INDICADOR = 5


def processar(payload: dict) -> dict:
    pesquisa_id = payload["pesquisa_id"]
    ciclo_id = payload["ciclo_id"]

    resposta_ciclo = (
        supabase.table("ciclo")
        .select("empresa_id")
        .eq("id", ciclo_id)
        .single()
        .execute()
    )
    ciclo = resposta_ciclo.data if resposta_ciclo else None
    if not ciclo:
        raise ValueError(
            f"Ciclo {ciclo_id} não encontrado ao encerrar pesquisa {pesquisa_id}."
        )
    empresa_id = ciclo["empresa_id"]

    respostas = _buscar_respostas(pesquisa_id)
    tokens_info = _buscar_info_tokens(
        pesquisa_id
    )


    indicadores_empresa = _calcular_indicadores(respostas, agrupar_por_setor=False)
    _salvar_indicadores(ciclo_id, indicadores_empresa, setor_id=None)

    # ---- 2. Indicadores por categoria, quebrado por setor ----
    indicadores_por_setor = _calcular_indicadores_por_setor(respostas, tokens_info)
    for setor_id, indicadores in indicadores_por_setor.items():
        _salvar_indicadores(ciclo_id, indicadores, setor_id=setor_id)

    # ---- 3. Checagem de qualidade de resposta ----
    avaliacoes_qualidade = _avaliar_qualidade_respostas(respostas, tokens_info)
    resumo_qualidade = resumo_qualidade_ciclo(avaliacoes_qualidade)

    # ---- 4. Classificação dos comentários abertos (risco grave + sentimento/tema) ----
    comentarios = [r["valor_texto"] for r in respostas if r.get("valor_texto")]
    classificacoes_comentarios = [classificar_comentario(c) for c in comentarios]
    prioridade_ml = _prioridade_mais_severa(classificacoes_comentarios)

    analises_texto = [analisar_comentario(c) for c in comentarios]
    resumo_sentimento = _resumir_sentimento(analises_texto)
    temas_comentarios = _resumir_temas(analises_texto)

    # ---- 5. Comparação com ciclo anterior (queda brusca) ----
    ciclo_anterior = _buscar_ciclo_anterior(empresa_id, ciclo_id)
    alertas_criados = []
    for ind in indicadores_empresa:
        if ind["total_respostas"] < MINIMO_RESPOSTAS_POR_INDICADOR:
            continue  # protege anonimato — não gera alerta com poucos dados

        if ind["media"] < LIMITE_INDICADOR_BAIXO:
            alertas_criados.append(
                _criar_alerta(
                    ciclo_id,
                    ind["categoria_id"],
                    "indicador_baixo",
                    f"A categoria {ind['categoria_nome']} apresentou média {ind['media']}, "
                    f"abaixo do limite recomendado de {LIMITE_INDICADOR_BAIXO}.",
                )
            )

        if ciclo_anterior:
            media_anterior = _media_anterior_da_categoria(
                ciclo_anterior["id"], ind["categoria_id"]
            )
            if media_anterior is not None:
                queda = media_anterior - ind["media"]
                if queda >= LIMITE_QUEDA_BRUSCA:
                    alertas_criados.append(
                        _criar_alerta(
                            ciclo_id,
                            ind["categoria_id"],
                            "queda_brusca",
                            f"A categoria {ind['categoria_nome']} caiu de {media_anterior} para "
                            f"{ind['media']} em relação ao ciclo anterior (queda de {round(queda, 2)} pontos).",
                        )
                    )

    # ---- 6. Alerta de comentário crítico (PLN) ----
    if prioridade_ml in ("alta", "media"):
        alertas_criados.append(
            _criar_alerta(
                ciclo_id,
                None,
                "comentario_critico",
                f"O classificador de comentários identificou prioridade '{prioridade_ml}' "
                f"na análise de texto aberto deste ciclo.",
            )
        )

    # ---- 7. Relatório da IA (Gemini) ----
    total_respondentes = len(tokens_info)
    analise_ia = analisar_ciclo(
        indicadores=[
            {"categoria": i["categoria_nome"], "media": i["media"]}
            for i in indicadores_empresa
        ],
        total_respondentes=total_respondentes,
        comentarios=comentarios,
    )

    # Regra de ouro (Documento 3, seção 4): a IA NUNCA decide o score —
    # ela só interpreta. O número vem de fórmula fixa, documentada e
    # auditável, calculada aqui, não pedida à IA.
    score_geral = _calcular_score_geral(indicadores_empresa)

    # a IA do Gemini e o classificador PLN local podem discordar sobre
    # prioridade — sempre vence o mais severo dos dois (o local é
    # especializado em detectar risco grave, não deve ser subestimado)
    prioridade_final = _mais_severa(
        analise_ia.get("prioridade", "baixa"), prioridade_ml
    )

    # ---- 8. Índice preditivo — empresa ----
    historico_empresa = _historico_score_empresa(empresa_id, ciclo_id)
    if score_geral is not None:
        historico_empresa.append(score_geral)
    previsao_empresa = avaliar_indice(historico_empresa)

    # Segunda opinião via KNN (ml/classificador_knn.py) — roda ao lado
    # da fórmula, nunca decide sozinha. Nível empresa aqui.
    knn_empresa = classificar_por_knn(indicadores_empresa)

    relatorio = (
        supabase.table("relatorio_ia")
        .insert(
            {
                "ciclo_id": ciclo_id,
                "resumo_executivo": analise_ia.get("resumo_executivo"),
                "tendencias": analise_ia.get("tendencias"),
                "analise_comentarios": analise_ia.get("analise_comentarios"),
                "recomendacoes": "\n".join(analise_ia.get("recomendacoes", [])),
                "prioridade": prioridade_final,
                "score_geral": score_geral,
                "tendencia": previsao_empresa.get("tendencia"),
                "projecao_proximo_ciclo": previsao_empresa.get(
                    "projecao_proximo_ciclo"
                ),
                "faixa_projetada": previsao_empresa.get("faixa_projetada"),
                "sentimento_geral": resumo_sentimento,
                "classificacao_knn": (
                    knn_empresa["classificacao_knn"] if knn_empresa else None
                ),
                "confianca_knn": knn_empresa["confianca_knn"] if knn_empresa else None,
            }
        )
        .execute()
        .data[0]
    )

    # ---- 9. Índice preditivo — por setor ----
    resultados_setor = {}
    for setor_id, indicadores in indicadores_por_setor.items():
        if not indicadores:
            continue
        score_setor_ciclo = round(
            sum(i["media"] for i in indicadores) / len(indicadores), 2
        )
        historico_setor = _historico_score_setor(setor_id, ciclo_id)
        if score_setor_ciclo is not None:
            historico_setor.append(score_setor_ciclo)
        previsao_setor = avaliar_indice(historico_setor)
        knn_setor = classificar_por_knn(indicadores)

        supabase.table("indice_setor").insert(
            {
                "ciclo_id": ciclo_id,
                "setor_id": setor_id,
                "score": score_setor_ciclo,
                "faixa": previsao_setor["faixa_atual"],
                "tendencia": previsao_setor.get("tendencia"),
                "projecao_proximo_ciclo": previsao_setor.get("projecao_proximo_ciclo"),
                "classificacao_knn": (
                    knn_setor["classificacao_knn"] if knn_setor else None
                ),
                "confianca_knn": knn_setor["confianca_knn"] if knn_setor else None,
            }
        ).execute()
        resultados_setor[setor_id] = previsao_setor

    # ---- 10. Marca a pesquisa como encerrada (faltava — bug real corrigido) ----
    supabase.table("pesquisa").update(
        {
            "status": "encerrada",
            "encerrada_em": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", pesquisa_id).execute()

    return {
        "relatorio_id": relatorio["id"],
        "prioridade_final": prioridade_final,
        "alertas_criados": len(alertas_criados),
        "resumo_qualidade": resumo_qualidade,
        "sentimento_comentarios": resumo_sentimento,
        "temas_comentarios": temas_comentarios,
        "previsao_empresa": previsao_empresa,
        "previsao_por_setor": resultados_setor,
    }


# ================================================================
# Funções auxiliares
# ================================================================


def _calcular_score_geral(indicadores: list[dict]) -> float | None:
    """
    Fórmula documentada no Documento 3, seção 4 — a única fonte de
    verdade do score geral. Nunca pedimos esse número à IA.
    Escala 1-5 (média das categorias) convertida para 0-10.
    """
    if not indicadores:
        return None
    media = sum(i["media"] for i in indicadores) / len(indicadores)
    score = (media - 1) / 4 * 10
    return round(max(0.0, min(10.0, score)), 2)


def _buscar_respostas(pesquisa_id: str) -> list[dict]:
    resultado = supabase.rpc(
        "obter_respostas_pesquisa", {"p_pesquisa_id": pesquisa_id}
    ).execute()
    return resultado.data or []


def _buscar_info_tokens(pesquisa_id: str) -> dict:
    tokens = (
        supabase.table("token_resposta")
        .select("id, funcionario_id, iniciado_em, respondido_em")
        .eq("pesquisa_id", pesquisa_id)
        .execute()
        .data
    )
    funcionario_ids = list({t["funcionario_id"] for t in tokens})
    funcionarios = (
        supabase.table("funcionario")
        .select("id, setor_id")
        .in_("id", funcionario_ids)
        .execute()
        .data
        if funcionario_ids
        else []
    )
    setor_por_funcionario = {f["id"]: f["setor_id"] for f in funcionarios}

    info = {}
    for t in tokens:
        tempo_segundos = None
        if t.get("iniciado_em") and t.get("respondido_em"):
            inicio = datetime.fromisoformat(t["iniciado_em"])
            fim = datetime.fromisoformat(t["respondido_em"])
            tempo_segundos = (fim - inicio).total_seconds()

        info[t["id"]] = {
            "funcionario_id": t["funcionario_id"],
            "setor_id": setor_por_funcionario.get(t["funcionario_id"]),
            "tempo_segundos": tempo_segundos,
        }
    return info


def _calcular_indicadores(respostas: list[dict], agrupar_por_setor: bool) -> list[dict]:
    grupos = defaultdict(lambda: {"soma": 0, "total": 0, "categoria_nome": ""})
    for r in respostas:
        if r.get("valor_escala") is None:
            continue
        chave = r["categoria_id"]
        grupos[chave]["soma"] += r["valor_escala"]
        grupos[chave]["total"] += 1
        grupos[chave]["categoria_nome"] = r["categoria_nome"]

    return [
        {
            "categoria_id": cat_id,
            "categoria_nome": g["categoria_nome"],
            "media": round(g["soma"] / g["total"], 2),
            "total_respostas": g["total"],
        }
        for cat_id, g in grupos.items()
    ]


def _calcular_indicadores_por_setor(respostas: list[dict], tokens_info: dict) -> dict:
    respostas_por_setor = defaultdict(list)
    for r in respostas:
        setor_id = tokens_info.get(r["token_id"], {}).get("setor_id")
        if setor_id:
            respostas_por_setor[setor_id].append(r)

    return {
        setor_id: _calcular_indicadores(resp_setor, agrupar_por_setor=True)
        for setor_id, resp_setor in respostas_por_setor.items()
    }


def _salvar_indicadores(
    ciclo_id: str, indicadores: list[dict], setor_id: str | None
) -> None:
    for ind in indicadores:
        if ind["total_respostas"] < MINIMO_RESPOSTAS_POR_INDICADOR:
            continue  # protege anonimato — não salva indicador com poucos dados
        supabase.table("indicador").insert(
            {
                "ciclo_id": ciclo_id,
                "categoria_id": ind["categoria_id"],
                "setor_id": setor_id,
                "media": ind["media"],
                "total_respostas": ind["total_respostas"],
            }
        ).execute()


def _avaliar_qualidade_respostas(
    respostas: list[dict], tokens_info: dict
) -> list[dict]:
    respostas_por_token = defaultdict(list)
    for r in respostas:
        if r.get("valor_escala") is not None:
            respostas_por_token[r["token_id"]].append(r["valor_escala"])

    avaliacoes = []
    for token_id, valores in respostas_por_token.items():
        tempo = tokens_info.get(token_id, {}).get("tempo_segundos")
        avaliacoes.append(avaliar_qualidade(valores, tempo))
    return avaliacoes


def _resumir_sentimento(analises: list[dict]) -> str | None:
    """Sentimento predominante entre os comentarios do ciclo."""
    validos = [a["sentimento"] for a in analises if a.get("tem_conteudo")]
    if not validos:
        return None
    contagem = Counter(validos)
    mais_comum, qtd = contagem.most_common(1)[0]
    # se estiver muito dividido, chama de "misto" em vez de forcar 1 rotulo
    if qtd / len(validos) < 0.5:
        return "misto"
    return mais_comum


def _resumir_temas(analises: list[dict]) -> dict:
    """Quantos comentarios (com confianca razoavel) cairam em cada tema."""
    validos = [
        a
        for a in analises
        if a.get("tem_conteudo") and a.get("tema_confianca", 0) >= 0.4
    ]
    contagem = Counter(a["tema_categoria"] for a in validos)
    return dict(contagem)


def _prioridade_mais_severa(classificacoes: list[dict]) -> str:
    ordem = {"baixa": 0, "media": 1, "alta": 2}
    maior = "baixa"
    for c in classificacoes:
        if ordem.get(c["prioridade"], 0) > ordem[maior]:
            maior = c["prioridade"]
    return maior


def _mais_severa(a: str, b: str) -> str:
    ordem = {"baixa": 0, "media": 1, "alta": 2}
    return a if ordem.get(a, 0) >= ordem.get(b, 0) else b


def _buscar_ciclo_anterior(empresa_id: str, ciclo_id_atual: str) -> dict | None:
    ciclos = (
        supabase.table("ciclo")
        .select("id, data_inicio")
        .eq("empresa_id", empresa_id)
        .eq("status", "concluido")
        .neq("id", ciclo_id_atual)
        .order("data_inicio", desc=True)
        .limit(1)
        .execute()
        .data
    )
    return ciclos[0] if ciclos else None


def _media_anterior_da_categoria(
    ciclo_anterior_id: str, categoria_id: str
) -> float | None:
    linhas = (
        supabase.table("indicador")
        .select("media")
        .eq("ciclo_id", ciclo_anterior_id)
        .eq("categoria_id", categoria_id)
        .is_("setor_id", "null")
        .execute()
        .data
    )
    return linhas[0]["media"] if linhas else None


def _criar_alerta(
    ciclo_id: str, categoria_id: str | None, tipo: str, descricao: str
) -> dict:
    return (
        supabase.table("alerta")
        .insert(
            {
                "ciclo_id": ciclo_id,
                "categoria_id": categoria_id,
                "tipo": tipo,
                "descricao": descricao,
            }
        )
        .execute()
        .data[0]
    )


def _historico_score_empresa(empresa_id: str, ciclo_id_atual: str) -> list[float]:
    # Usa criado_em, não data_inicio -- esse campo é opcional e a tela
    # de criar ciclo nunca preenche ele, então fica sempre nulo.
    ciclos = (
        supabase.table("ciclo")
        .select("id, criado_em")
        .eq("empresa_id", empresa_id)
        .neq("id", ciclo_id_atual)
        .order("criado_em")
        .execute()
        .data
    )
    scores = []
    for c in ciclos:
        relatorios = (
            supabase.table("relatorio_ia")
            .select("score_geral")
            .eq("ciclo_id", c["id"])
            .execute()
            .data
        )
        if relatorios and relatorios[0]["score_geral"] is not None:
            scores.append(relatorios[0]["score_geral"])
    return scores


def _historico_score_setor(setor_id: str, ciclo_id_atual: str) -> list[float]:
    linhas = (
        supabase.table("indice_setor")
        .select("score, ciclo:ciclo_id(criado_em)")
        .eq("setor_id", setor_id)
        .neq("ciclo_id", ciclo_id_atual)
        .execute()
        .data
    )
    # Filtra linha sem score ou sem data antes de ordenar -- evita
    # comparar None com None (TypeError em Python)
    linhas_validas = [
        l
        for l in linhas
        if l.get("score") is not None and l.get("ciclo") and l["ciclo"].get("criado_em")
    ]
    linhas_ordenadas = sorted(linhas_validas, key=lambda x: x["ciclo"]["criado_em"])
    return [l["score"] for l in linhas_ordenadas]

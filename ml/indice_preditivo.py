"""
Classificação (bom/médio/ruim) e projeção de tendência do índice
psicossocial — SEMPRE por setor ou por empresa, NUNCA por
funcionário individual.

Isso não é limitação técnica, é decisão deliberada: o produto
inteiro (RLS, mínimo de 5 respostas por indicador, Documento 3)
foi desenhado pra nunca permitir identificar indivíduo. Um índice
"deste funcionário está ruim" seria dado de saúde vinculado a
pessoa nomeada — sensível sob a LGPD (Art. 5º, II) e um risco real
de uso indevido numa relação de trabalho.

Reaproveita a mesma escala já documentada no Documento 3, seção 4:
    8.0–10.0  Excelente   ┐
    6.0–7.9   Bom         ┘── aqui: "bom"
    4.0–5.9   Atenção     ── aqui: "medio"
    2.0–3.9   Risco elevado ┐
    0.0–1.9   Crítico       ┘── aqui: "ruim"
"""
from typing import Optional


def classificar_faixa(score_geral: float) -> str:
    if score_geral >= 6.0:
        return "bom"
    elif score_geral >= 4.0:
        return "medio"
    else:
        return "ruim"


def prever_tendencia(scores_historicos: list[float]) -> dict:
    """
    scores_historicos: score_geral dos últimos ciclos, em ordem
    cronológica (mais antigo primeiro).

    Com menos de 3 ciclos, não existe dado suficiente pra projetar
    tendência com confiança — o produto admite isso explicitamente
    em vez de inventar um número. Mesmo princípio de honestidade
    estatística que já seguimos em outras partes do produto.
    """
    n = len(scores_historicos)

    if n < 3:
        return {
            "tendencia": "dados_insuficientes",
            "projecao_proximo_ciclo": None,
            "confianca": "baixa",
            "motivo": f"Apenas {n} ciclo(s) registrado(s) — mínimo de 3 para projetar tendência.",
        }

    # Regressão linear simples — não precisa de biblioteca de ML
    # pra ajustar uma reta em poucos pontos.
    xs = list(range(n))
    media_x = sum(xs) / n
    media_y = sum(scores_historicos) / n

    numerador = sum((xs[i] - media_x) * (scores_historicos[i] - media_y) for i in range(n))
    denominador = sum((xs[i] - media_x) ** 2 for i in range(n))
    inclinacao = (numerador / denominador) if denominador else 0.0

    projecao = scores_historicos[-1] + inclinacao
    projecao = max(0.0, min(10.0, projecao))

    if inclinacao > 0.15:
        tendencia = "melhorando"
    elif inclinacao < -0.15:
        tendencia = "piorando"
    else:
        tendencia = "estavel"

    return {
        "tendencia": tendencia,
        "projecao_proximo_ciclo": round(projecao, 2),
        "faixa_projetada": classificar_faixa(projecao),
        "confianca": "media" if n < 6 else "alta",
        "inclinacao_por_ciclo": round(inclinacao, 3),
    }


def avaliar(scores_historicos: list[float]) -> dict:
    """
    Função principal — serve tanto pra um setor quanto pra empresa
    inteira; a diferença é só de onde vem a lista de scores (ver
    routes/encerrar_pesquisa.py para como agregar cada caso).
    """
    if not scores_historicos:
        return {"score_atual": None, "faixa_atual": None, "motivo": "sem dados"}

    score_atual = scores_historicos[-1]
    return {
        "score_atual": score_atual,
        "faixa_atual": classificar_faixa(score_atual),
        **prever_tendencia(scores_historicos),
    }

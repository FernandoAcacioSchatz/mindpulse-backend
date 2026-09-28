from typing import Optional


def classificar_faixa(score_geral: float) -> str:
    if score_geral >= 6.0:
        return "bom"
    elif score_geral >= 4.0:
        return "medio"
    else:
        return "ruim"


def prever_tendencia(scores_historicos: list[float]) -> dict:
    n = len(scores_historicos)

    if n < 3:
        return {
            "tendencia": "dados_insuficientes",
            "projecao_proximo_ciclo": None,
            "confianca": "baixa",
            "motivo": f"Apenas {n} ciclo(s) registrado(s) — mínimo de 3 para projetar tendência.",
        }

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
    if not scores_historicos:
        return {"score_atual": None, "faixa_atual": None, "motivo": "sem dados"}

    score_atual = scores_historicos[-1]
    return {
        "score_atual": score_atual,
        "faixa_atual": classificar_faixa(score_atual),
        **prever_tendencia(scores_historicos),
    }

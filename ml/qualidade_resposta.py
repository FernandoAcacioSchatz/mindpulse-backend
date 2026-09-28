from statistics import pstdev
from typing import Optional


DESVIO_MINIMO = 0.3
TEMPO_MINIMO_SEGUNDOS = 20


def avaliar_qualidade(valores_escala: list[int], tempo_segundos: Optional[float] = None) -> dict:
    if not valores_escala:
        return {"suspeita": False, "motivo": "sem respostas de escala para avaliar"}

    desvio = pstdev(valores_escala) if len(valores_escala) > 1 else 0.0

    sinais = []
    if desvio < DESVIO_MINIMO:
        sinais.append("respostas quase identicas entre si")
    if tempo_segundos is not None and tempo_segundos < TEMPO_MINIMO_SEGUNDOS:
        sinais.append("tempo de preenchimento muito curto")

    return {
        "suspeita": len(sinais) > 0,
        "desvio_padrao": round(desvio, 3),
        "tempo_segundos": tempo_segundos,
        "sinais": sinais,
    }


def resumo_qualidade_ciclo(avaliacoes: list[dict]) -> dict:
    total = len(avaliacoes)
    if total == 0:
        return {"total_respostas": 0, "percentual_confiavel": None}

    suspeitas = sum(1 for a in avaliacoes if a["suspeita"])
    confiavel = round(((total - suspeitas) / total) * 100, 1)

    return {
        "total_respostas": total,
        "respostas_suspeitas": suspeitas,
        "percentual_confiavel": confiavel,
    }

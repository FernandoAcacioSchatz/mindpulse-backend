"""
Checagem de qualidade das respostas — detecta sinais de resposta
descuidada (straight-lining), sem nunca identificar quem respondeu
assim e sem excluir ninguém automaticamente. Só sinaliza.

FASE 1 (aqui): regra estatística simples (desvio padrão + tempo).
Funciona bem mesmo com poucos dados — é o que usamos agora.

FASE 2 (futuro, quando houver volume de ciclos acumulado):
trocar por um modelo de detecção de anomalia não supervisionado
(sklearn.ensemble.IsolationForest), que aprende sozinho o padrão
"normal" de cada ciclo. Não vale a pena introduzir isso ainda —
com poucas respostas por ciclo, o modelo aprenderia ruído, não
padrão real. Ver Documento de ML da conversa original para mais
contexto sobre essa decisão.
"""
from statistics import pstdev
from typing import Optional


DESVIO_MINIMO = 0.3      # abaixo disso, respostas quase idênticas entre si
TEMPO_MINIMO_SEGUNDOS = 20  # abaixo disso, tempo insuficiente pra ler as perguntas


def avaliar_qualidade(valores_escala: list[int], tempo_segundos: Optional[float] = None) -> dict:
    """
    Recebe as respostas de escala (1-5) de UM token (um respondente) e,
    opcionalmente, quanto tempo levou pra responder.

    Retorna um dicionário com o veredito e os sinais que levaram a ele —
    nunca um "descarte automático": o RH decide o que fazer com esse sinal.
    """
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
    """
    Agrega as avaliações individuais de um ciclo inteiro num número
    só, pra mostrar no Dashboard (ex: "Confiabilidade dos dados: 91%").
    Nunca expõe qual token específico foi marcado como suspeito.
    """
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

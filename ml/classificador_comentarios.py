"""
Classificador de comentários abertos — decide se um comentário
sinaliza necessidade de intervenção da empresa.

FASE 1 (aqui): regras + padrões de texto, 100% explicável — cada
classificação vem acompanhada do motivo exato. Isso segue o mesmo
princípio do cálculo de score (Documento 3): numa auditoria, você
precisa conseguir justificar "por que isso foi marcado como
urgente", não apenas apontar pra uma caixa-preta.

Roda 100% local, sem chamar nenhuma API externa — nenhum comentário
sensível sai da sua infraestrutura. Zero dependência nova.

FASE 2 (futuro): quando `alerta_feedback` (ver 20-tabela-alerta-feedback.sql)
acumular confirmações reais do RH, esse vira o dataset rotulado
pra treinar de verdade um modelo (fine-tune de um BERT em
português) nos dados reais do MindPulse — não antes disso.
"""
import re
from typing import Optional

# Temas de risco alto — qualquer menção aciona prioridade máxima,
# independente do restante da análise. Mantido em nível de padrão
# (não é uma lista exaustiva), suficiente pra rotear pro RH agir.
TEMAS_RISCO_ALTO = {
    "risco_a_vida": [
        r"pensei em (me matar|acabar com (tudo|a (minha )?vida)|desistir de tudo)",
        r"n[aã]o aguento mais viver",
        r"vontade de (sumir|desaparecer)",
        r"me (cortar|machucar)",
    ],
    "assedio": [
        r"ass[eé]dio (moral|sexual)",
        r"fui (assediad[oa]|amea[cç]ad[oa])",
        r"toque[s]? sem consentimento",
    ],
    "ameaca": [
        r"amea[cç]a(ndo|ram|do)?",
        r"medo de (represalia|ser demitid[oa])",
    ],
}

# Temas de atenção — não disparam prioridade máxima sozinhos, mas
# somam ao nível de urgência quando aparecem em conjunto.
TEMAS_ATENCAO = [
    r"esgotad[oa]", r"burnout", r"n[aã]o aguento (mais )?a rotina",
    r"chorei? no trabalho", r"ansiedade", r"crise de p[aâ]nico",
    r"sem reconhecimento", r"sobrecarreg?ad[oa]",
]


def classificar_comentario(texto: Optional[str]) -> dict:
    """
    Recebe o texto de um comentário aberto e devolve a classificação
    de urgência (baixa / media / alta), sempre com o motivo explícito.
    """
    if not texto or not texto.strip():
        return {
            "tem_conteudo": False,
            "prioridade": "baixa",
            "necessita_intervencao": False,
            "motivo": "comentário vazio",
        }

    texto_lower = texto.lower()

    temas_risco_encontrados = []
    for tema, padroes in TEMAS_RISCO_ALTO.items():
        for padrao in padroes:
            if re.search(padrao, texto_lower):
                temas_risco_encontrados.append(tema)
                break

    temas_atencao_encontrados = [p for p in TEMAS_ATENCAO if re.search(p, texto_lower)]

    if temas_risco_encontrados:
        prioridade = "alta"
        motivo = f"Sinal de risco grave identificado: {', '.join(temas_risco_encontrados)}"
    elif len(temas_atencao_encontrados) >= 2:
        prioridade = "media"
        motivo = f"Múltiplos sinais de sofrimento/esgotamento ({len(temas_atencao_encontrados)} identificados)"
    elif len(temas_atencao_encontrados) == 1:
        prioridade = "baixa"
        motivo = "Um sinal de atenção identificado, isolado"
    else:
        prioridade = "baixa"
        motivo = "Nenhum sinal de risco ou atenção identificado"

    return {
        "tem_conteudo": True,
        "prioridade": prioridade,
        "temas_risco_alto": temas_risco_encontrados,
        "qtd_temas_atencao": len(temas_atencao_encontrados),
        "necessita_intervencao": prioridade in ("alta", "media"),
        "motivo": motivo,
    }

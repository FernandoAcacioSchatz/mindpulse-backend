import re
from typing import Optional

TEMAS_RISCO_ALTO = {
    "risco_a_vida": [
        r"quero morrer",
        r"queria (estar morto|estar morta|morrer|n[aã]o (ter nascido|existir))",
        r"n[aã]o quero mais viver",
        r"n[aã]o aguento mais viver",
        r"n[aã]o vejo (mais )?sentido (em|na) vida",
        r"(pensei em|penso em|tenho pensado em|quero) (me matar|acabar com (tudo|a (minha )?vida)|desistir de tudo|dar fim (a |em )?(tudo|isso)|tirar minha vida)",
        r"vontade de (sumir|desaparecer|morrer|n[aã]o existir)",
        r"quero (sumir|desaparecer) (de vez|pra sempre)?",
        r"pensamentos? suicidas?",
        r"ideia[cç][aã]o suicida",
        r"me (cortar|machucar|ferir) (de prop[oó]sito)?",
    ],
    "assedio": [
        r"ass[eé]dio (moral|sexual)",
        r"(fui|sofri) (assediad[oa]|amea[cç]ad[oa])",
        r"me (assediou|assediaram|amea[cç]ou|amea[cç]aram)",
        r"toque[s]? sem consentimento",
    ],
    "ameaca": [
        r"amea[cç]a(ndo|ram|do)?",
        r"medo de (represalia|ser demitid[oa])",
    ],
}

TEMAS_ATENCAO = [
    r"esgotad[oa]", r"burnout", r"n[aã]o aguento (mais )?a rotina",
    r"chorei? no trabalho", r"ansiedade", r"crise de p[aâ]nico",
    r"sem reconhecimento", r"sobrecarreg?ad[oa]",
]


def classificar_comentario(texto: Optional[str]) -> dict:
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

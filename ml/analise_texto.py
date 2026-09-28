from pathlib import Path

import joblib

_PASTA_MODELOS = Path(__file__).parent / "modelos"
_vetorizador = joblib.load(_PASTA_MODELOS / "vetorizador_tema.joblib")
_classificador_tema = joblib.load(_PASTA_MODELOS / "classificador_tema.joblib")

_PALAVRAS_POSITIVAS = {
    "bom",
    "boa",
    "otimo",
    "otima",
    "tranquilo",
    "tranquila",
    "satisfeito",
    "satisfeita",
    "feliz",
    "reconhecido",
    "reconhecida",
    "valorizado",
    "valorizada",
    "confio",
    "apoia",
    "apoio",
    "claro",
    "clara",
    "seguro",
    "segura",
    "equilibrada",
    "equilibrado",
    "disposto",
    "disposta",
}
_PALAVRAS_NEGATIVAS = {
    "nao",
    "exausto",
    "exausta",
    "sobrecarregado",
    "sobrecarregada",
    "cansado",
    "cansada",
    "ruim",
    "pessimo",
    "pessima",
    "nunca",
    "aguento",
    "demais",
    "sem",
    "medo",
    "ansiedade",
    "confuso",
    "confusa",
    "ausente",
    "ignoradas",
    "ignoradas",
    "abusiva",
    "impropria",
    "improprio",
}


def analisar_sentimento(texto: str) -> str:
    palavras = texto.lower().split()
    pos = sum(1 for p in palavras if p in _PALAVRAS_POSITIVAS)
    neg = sum(1 for p in palavras if p in _PALAVRAS_NEGATIVAS)
    if pos > neg:
        return "positivo"
    if neg > pos:
        return "negativo"
    return "neutro"


def classificar_tema(texto: str) -> dict:
    X = _vetorizador.transform([texto])
    categoria = _classificador_tema.predict(X)[0]
    vizinhos = _classificador_tema.kneighbors(X, return_distance=False)[0]
    rotulos_vizinhos = (
        _classificador_tema._y[vizinhos] if hasattr(_classificador_tema, "_y") else None
    )
    confianca = _classificador_tema.predict_proba(X).max()
    return {"categoria": categoria, "confianca": round(float(confianca), 2)}


def analisar_comentario(texto: str) -> dict:
    if not texto or not texto.strip():
        return {"tem_conteudo": False}

    sentimento = analisar_sentimento(texto)
    tema = classificar_tema(texto)

    return {
        "tem_conteudo": True,
        "sentimento": sentimento,
        "tema_categoria": tema["categoria"],
        "tema_confianca": tema["confianca"],
    }

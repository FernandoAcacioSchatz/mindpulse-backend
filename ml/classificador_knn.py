from pathlib import Path

import joblib
import pandas as pd

_PASTA_MODELOS = Path(__file__).parent / "modelos"
_modelo = joblib.load(_PASTA_MODELOS / "knn_indice.joblib")

COLUNAS_MODELO = ["carga_trabalho", "lideranca", "comunicacao", "reconhecimento",
                   "bem_estar", "seguranca_psicologica", "assedio"]
_MAPA_NOME_PARA_COLUNA = {
    "Carga de Trabalho": "carga_trabalho", "Liderança": "lideranca",
    "Comunicação": "comunicacao", "Reconhecimento": "reconhecimento",
    "Bem-estar": "bem_estar", "Segurança Psicológica": "seguranca_psicologica",
    "Assédio": "assedio",
}
VALOR_PADRAO_CATEGORIA_FALTANTE = 3.0


def classificar_por_knn(indicadores: list[dict]) -> dict | None:
    if not indicadores:
        return None

    medias_por_coluna = {
        _MAPA_NOME_PARA_COLUNA[i["categoria_nome"]]: i["media"]
        for i in indicadores if i["categoria_nome"] in _MAPA_NOME_PARA_COLUNA
    }
    linha = {col: medias_por_coluna.get(col, VALOR_PADRAO_CATEGORIA_FALTANTE) for col in COLUNAS_MODELO}
    entrada = pd.DataFrame([linha], columns=COLUNAS_MODELO)

    classe = _modelo.predict(entrada)[0]
    confianca = _modelo.predict_proba(entrada).max()

    return {"classificacao_knn": classe, "confianca_knn": round(float(confianca), 2)}

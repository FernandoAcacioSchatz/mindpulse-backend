"""
Projeta indicadores (7 categorias) no mesmo espaço 3D do PCA
ajustado sobre o dataset sintético -- é o que permite comparar uma
pesquisa real com a "nuvem" de referência visualmente.

Mesma ideia do classificador_knn.py: usa artefato treinado uma vez
(ml/modelos/pca_3d.joblib), nunca re-ajusta o PCA em tempo real.
"""
import json
from pathlib import Path

import joblib
import pandas as pd

_PASTA_MODELOS = Path(__file__).parent / "modelos"
_pca = joblib.load(_PASTA_MODELOS / "pca_3d.joblib")

with open(_PASTA_MODELOS / "nuvem_fundo_3d.json") as f:
    NUVEM_FUNDO = json.load(f)

COLUNAS_MODELO = ["carga_trabalho", "lideranca", "comunicacao", "reconhecimento",
                   "bem_estar", "seguranca_psicologica", "assedio"]
_MAPA_NOME_PARA_COLUNA = {
    "Carga de Trabalho": "carga_trabalho", "Liderança": "lideranca",
    "Comunicação": "comunicacao", "Reconhecimento": "reconhecimento",
    "Bem-estar": "bem_estar", "Segurança Psicológica": "seguranca_psicologica",
    "Assédio": "assedio",
}
VALOR_PADRAO_CATEGORIA_FALTANTE = 3.0


def projetar_em_3d(indicadores: list[dict]) -> dict | None:
    """
    indicadores: lista de {categoria_nome, media} -- mesmo formato
    usado no classificador_knn.py e no cálculo do score.
    Retorna {x, y, z} ou None se não houver indicador nenhum.
    """
    if not indicadores:
        return None

    medias_por_coluna = {
        _MAPA_NOME_PARA_COLUNA[i["categoria_nome"]]: i["media"]
        for i in indicadores if i["categoria_nome"] in _MAPA_NOME_PARA_COLUNA
    }
    linha = {col: medias_por_coluna.get(col, VALOR_PADRAO_CATEGORIA_FALTANTE) for col in COLUNAS_MODELO}
    entrada = pd.DataFrame([linha], columns=COLUNAS_MODELO)

    coords = _pca.transform(entrada)[0]
    return {"x": round(float(coords[0]), 3), "y": round(float(coords[1]), 3), "z": round(float(coords[2]), 3)}

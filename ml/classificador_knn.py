"""
Classificação de índice (bom/médio/ruim) por KNN — SEGUNDA OPINIÃO,
rodando ao lado da fórmula determinística (_calcular_score_geral em
routes/encerrar_pesquisa.py), nunca no lugar dela.

Nível de aplicação: SETOR e EMPRESA — nunca funcionário. É a mesma
granularidade que o resto do produto já protege (mínimo de 5
respostas), por decisão de projeto: um índice por pessoa quebraria
a promessa de anonimato que sustenta o produto inteiro.

Treinado com o dataset sintético (ml/dataset/dataset_radar_sintetico.csv,
20 mil linhas) — não é dado real de cliente. Ver Documento 3 e o
histórico da conversa sobre essa decisão.
"""
from pathlib import Path

import joblib
import pandas as pd

_PASTA_MODELOS = Path(__file__).parent / "modelos"
_modelo = joblib.load(_PASTA_MODELOS / "knn_indice.joblib")

# Ordem e nomes EXATOS usados no treino (ml/dataset/gerar_dataset_sintetico.py)
COLUNAS_MODELO = ["carga_trabalho", "lideranca", "comunicacao", "reconhecimento",
                   "bem_estar", "seguranca_psicologica", "assedio"]
_MAPA_NOME_PARA_COLUNA = {
    "Carga de Trabalho": "carga_trabalho", "Liderança": "lideranca",
    "Comunicação": "comunicacao", "Reconhecimento": "reconhecimento",
    "Bem-estar": "bem_estar", "Segurança Psicológica": "seguranca_psicologica",
    "Assédio": "assedio",
}
VALOR_PADRAO_CATEGORIA_FALTANTE = 3.0  # neutro, meio da escala 1-5


def classificar_por_knn(indicadores: list[dict]) -> dict | None:
    """
    indicadores: lista de {categoria_nome, media} — mesmo formato que
    já alimenta o cálculo do score determinístico. Funciona tanto pra
    empresa inteira quanto pra 1 setor, dependendo do que for passado.
    """
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

"""
Gera um dataset sintético de 20.000 registros pra treinar/validar
um classificador de risco psicossocial (bom/medio/ruim).

IMPORTANTE: dado sintético, não é dado real de nenhum cliente.
Declare isso explicitamente na banca e em qualquer documentação —
é prática aceita para protótipo, desde que não seja apresentado
como se fosse real.

Rodar:
    python ml/dataset/gerar_dataset_sintetico.py
Gera: dataset_radar_sintetico.csv, com 20.000 linhas.
"""
import csv
import random

FEATURES = [
    "carga_trabalho", "lideranca", "comunicacao",
    "reconhecimento", "bem_estar", "seguranca_psicologica", "assedio",
]

N_LINHAS = 20_000
random.seed(42)  # reprodutível — mesma seed sempre gera o mesmo dataset


def classificar_faixa(media: float) -> str:
    """
    Mesmo espírito da regra em ml/indice_preditivo.py, recalibrada
    pra escala 1-5 (o índice real do produto usa 0-10, calculado a
    partir da média 1-5 — aqui geramos direto na escala da pesquisa).
    """
    if media >= 4.0:
        return "bom"
    elif media >= 2.7:
        return "medio"
    else:
        return "ruim"


def gerar_linha():
    """
    Gera uma linha com CORRELAÇÃO real entre as features e a faixa
    final — não é ruído puro. A lógica: sorteia primeiro um "perfil
    de empresa" (saudável, mediano ou em risco), depois gera cada
    feature em torno daquele perfil, com variação individual.
    """
    perfil = random.choices(
        ["saudavel", "mediano", "em_risco"],
        weights=[0.45, 0.35, 0.20],  # a maioria das empresas não está em crise
    )[0]

    centro = {"saudavel": 4.3, "mediano": 3.0, "em_risco": 1.8}[perfil]

    valores = {}
    for feat in FEATURES:
        # assedio pesa diferente: mesmo empresa "mediana" tende a ter
        # valor mais alto aqui (é um evento raro, não uma média geral)
        if feat == "assedio":
            valor = random.gauss(centro + 0.6, 0.7)
        else:
            valor = random.gauss(centro, 0.8)

        valor = max(1.0, min(5.0, valor))  # trava entre 1 e 5
        valores[feat] = round(valor, 2)

    media_geral = sum(valores.values()) / len(valores)
    valores["faixa"] = classificar_faixa(media_geral)
    return valores


def main():
    caminho_saida = "dataset_radar_sintetico.csv"
    with open(caminho_saida, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FEATURES + ["faixa"])
        writer.writeheader()
        for _ in range(N_LINHAS):
            writer.writerow(gerar_linha())

    print(f"Gerado: {caminho_saida} com {N_LINHAS} linhas.")


if __name__ == "__main__":
    main()

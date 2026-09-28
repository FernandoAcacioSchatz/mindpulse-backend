import csv
import random

FEATURES = [
    "carga_trabalho", "lideranca", "comunicacao",
    "reconhecimento", "bem_estar", "seguranca_psicologica", "assedio",
]

N_LINHAS = 20_000
random.seed(42)


def classificar_faixa(media: float) -> str:
    if media >= 4.0:
        return "bom"
    elif media >= 2.7:
        return "medio"
    else:
        return "ruim"


def gerar_linha():
    perfil = random.choices(
        ["saudavel", "mediano", "em_risco"],
        weights=[0.45, 0.35, 0.20],
    )[0]

    centro = {"saudavel": 4.3, "mediano": 3.0, "em_risco": 1.8}[perfil]

    valores = {}
    for feat in FEATURES:
        if feat == "assedio":
            valor = random.gauss(centro + 0.6, 0.7)
        else:
            valor = random.gauss(centro, 0.8)

        valor = max(1.0, min(5.0, valor))
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

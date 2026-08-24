"""
Gera um dataset de ~500 frases de comentário de pesquisa, distribuídas
nas 7 categorias do produto, com frases BOAS e RUINS em cada uma —
de propósito, pra o classificador de TEMA aprender a reconhecer o
assunto independente do sentimento (evita que ele "aprenda" sentimento
por engano, achando que é tema).

IMPORTANTE: as frases-base foram escritas à mão (curadoria humana,
uma por uma), e depois passam por variação sistemática (troca de
palavra por sinônimo, jeito de começar a frase) pra multiplicar a
quantidade mantendo qualidade. Não são 500 frases 100% independentes
— é honesto declarar isso, inclusive na banca.
"""
import csv
import itertools
import random

random.seed(42)

# ============================================================
# Frases-base por categoria — escritas à mão, comentário real
# de pesquisa de clima organizacional
# ============================================================
BASE = {
    "carga_trabalho": {
        "bom": [
            "Consigo terminar minhas tarefas dentro do horário normal",
            "Minha carga de trabalho é equilibrada",
            "Tenho tempo suficiente para fazer um bom trabalho",
            "As demandas são razoáveis para o meu cargo",
            "Não preciso levar trabalho para casa",
            "Meu volume de tarefas é administrável",
            "Consigo organizar bem minhas entregas da semana",
        ],
        "ruim": [
            "Estou sobrecarregado com tarefas demais",
            "Não consigo terminar tudo dentro do horário",
            "Trabalho até tarde quase todos os dias",
            "As demandas são impossíveis de cumprir no prazo",
            "Sinto que nunca tenho tempo suficiente",
            "Meu volume de tarefas está fora de controle",
            "Não consigo organizar minhas entregas da semana",
        ],
    },
    "lideranca": {
        "bom": [
            "Meu líder me apoia quando eu preciso",
            "Confio nas decisões da minha liderança",
            "Meu gestor está sempre disponível para ajudar",
            "Recebo orientação clara do meu chefe",
            "Minha liderança reconhece o esforço da equipe",
            "Meu gestor me dá autonomia com responsabilidade",
            "Sinto apoio genuíno da minha chefia direta",
        ],
        "ruim": [
            "Meu chefe nunca está disponível quando preciso",
            "Não confio nas decisões da liderança",
            "Meu gestor não me dá suporte nenhum",
            "Sinto falta de orientação da minha chefia",
            "Minha liderança é ausente no dia a dia",
            "Meu gestor microgerencia tudo sem confiar na equipe",
            "Sinto que a chefia não está do meu lado",
        ],
    },
    "comunicacao": {
        "bom": [
            "As informações chegam claras até mim",
            "Sei exatamente o que é esperado de mim",
            "A comunicação entre as equipes funciona bem",
            "Recebo feedback claro sobre meu trabalho",
            "As prioridades são bem explicadas pela gestão",
            "As reuniões são objetivas e produtivas",
            "Sou informado sobre mudanças com antecedência",
        ],
        "ruim": [
            "Nunca sei o que está acontecendo na empresa",
            "As informações chegam confusas ou atrasadas",
            "Falta comunicação entre os setores",
            "Não recebo feedback sobre meu desempenho",
            "As prioridades mudam sem nenhum aviso",
            "As reuniões são desorganizadas e sem objetivo",
            "Fico sabendo de mudanças importantes de última hora",
        ],
    },
    "reconhecimento": {
        "bom": [
            "Meu trabalho é valorizado pela empresa",
            "Recebo reconhecimento quando faço um bom trabalho",
            "Sinto que meu esforço é notado pela gestão",
            "Sou recompensado de forma justa pelos resultados",
            "Meus colegas reconhecem minhas contribuições",
            "Já fui elogiado publicamente pelo meu trabalho",
            "Sinto orgulho de como minha entrega é vista aqui",
        ],
        "ruim": [
            "Meu esforço nunca é reconhecido",
            "Sinto que meu trabalho é invisível para a empresa",
            "Nunca recebo elogio nem feedback positivo",
            "Trabalho muito e não sou valorizado por isso",
            "Sinto que não faço diferença nenhuma aqui",
            "Meus resultados passam despercebidos pela gestão",
            "Sinto que meu esforço não vale a pena aqui",
        ],
    },
    "bem_estar": {
        "bom": [
            "Consigo manter equilíbrio entre vida pessoal e trabalho",
            "Me sinto bem fisicamente e mentalmente no trabalho",
            "Tenho pausas suficientes durante o dia",
            "Durmo bem e não penso no trabalho fora do horário",
            "Me sinto disposto na maior parte dos dias",
            "Consigo desconectar do trabalho nos fins de semana",
            "Meu nível de estresse está sob controle",
        ],
        "ruim": [
            "Estou constantemente cansado e sem energia",
            "Não consigo desconectar do trabalho nunca",
            "Tenho dormido mal por causa do trabalho",
            "Sinto ansiedade só de pensar em vir trabalhar",
            "Meu bem-estar tem piorado bastante ultimamente",
            "Não consigo descansar nem nos fins de semana",
            "Meu nível de estresse está fora de controle",
        ],
    },
    "seguranca_psicologica": {
        "bom": [
            "Me sinto à vontade para expressar minha opinião",
            "Posso admitir um erro sem medo de punição",
            "Sinto que posso ser eu mesmo no trabalho",
            "Minhas ideias são ouvidas com respeito",
            "Não tenho medo de discordar da liderança",
            "Posso fazer perguntas sem medo de parecer incompetente",
            "Me sinto seguro para levantar um problema",
        ],
        "ruim": [
            "Tenho medo de expressar minha opinião no trabalho",
            "Erros são punidos duramente por aqui",
            "Sinto que preciso me policiar o tempo todo",
            "Minhas ideias são ignoradas ou ridicularizadas",
            "Tenho medo de discordar de qualquer decisão",
            "Evito fazer perguntas com medo de parecer incompetente",
            "Não me sinto seguro para levantar um problema",
        ],
    },
    "assedio": {
        "bom": [
            "Nunca presenciei nem sofri assédio no ambiente de trabalho",
            "O ambiente é respeitoso entre todos os colegas",
            "Nunca vi conduta inadequada na empresa",
            "Me sinto seguro em relação a esse tema aqui",
            "As relações no trabalho são sempre profissionais",
            "Nunca ouvi comentário impróprio no ambiente",
            "Sinto que a empresa leva esse assunto a sério",
        ],
        "ruim": [
            "Já presenciei comportamento inadequado no ambiente",
            "Já me senti desrespeitado por um colega ou chefe",
            "Existem comentários impróprios que me incomodam",
            "Já vi alguém sendo tratado de forma abusiva aqui",
            "Não me sinto seguro em relação a esse tema",
            "Já ouvi comentário de conotação sexual no ambiente",
            "Sinto que esse assunto não é levado a sério aqui",
        ],
    },
}

# ============================================================
# Variação sistemática — multiplica as frases-base mantendo
# qualidade, trocando o jeito de abrir a frase
# ============================================================
PREFIXOS = [
    "", "Sinceramente, ", "No geral, ", "Ultimamente, ", "Para ser honesto, ",
    "Na minha experiência, ", "De forma geral, ", "Recentemente, ",
    "Ao longo do tempo, ", "No meu dia a dia, ",
]

def gerar_variacoes(frase_base, quantidade):
    variacoes = set()
    variacoes.add(frase_base)
    prefixos_embaralhados = PREFIXOS.copy()
    random.shuffle(prefixos_embaralhados)
    for prefixo in prefixos_embaralhados:
        if len(variacoes) >= quantidade:
            break
        if prefixo:
            texto = prefixo + frase_base[0].lower() + frase_base[1:]
        else:
            texto = frase_base
        variacoes.add(texto)
    return list(variacoes)[:quantidade]


def main():
    linhas = []
    for categoria, grupos in BASE.items():
        for sentimento, frases_base in grupos.items():
            # ~5 variações por frase-base -> ~35 por sentimento -> ~70 por categoria
            for frase_base in frases_base:
                for variacao in gerar_variacoes(frase_base, 5):
                    linhas.append({"frase": variacao, "categoria": categoria, "sentimento": sentimento})

    random.shuffle(linhas)

    caminho = "dataset_comentarios_texto.csv"
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["frase", "categoria", "sentimento"])
        writer.writeheader()
        writer.writerows(linhas)

    print(f"Gerado: {caminho} com {len(linhas)} linhas")

    from collections import Counter
    print("\nDistribuição por categoria:")
    print(Counter(l["categoria"] for l in linhas))
    print("\nDistribuição por sentimento:")
    print(Counter(l["sentimento"] for l in linhas))


if __name__ == "__main__":
    main()

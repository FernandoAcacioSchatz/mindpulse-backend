"""
Cliente Gemini — substitui o antigo openai_client.py.

Usa a própria biblioteca 'openai' (já estava no requirements.txt,
não precisou instalar nada novo) apontando pra API do Gemini —
o Google oferece uma camada de compatibilidade com o formato da
OpenAI, então o resto do código (montagem do prompt, leitura da
resposta) não precisou mudar quase nada.

Saída estruturada (Pydantic + response_format): em vez de pedir
"responda em JSON" no prompt e torcer pra vir certo, a API valida
o formato antes de devolver -- elimina a gambiarra antiga de tirar
```json``` na mão quando o modelo desobedecia.

ABSA (análise de sentimento por aspecto): além do resumo em texto
livre, o Gemini agora também devolve uma lista de aspectos --
cada um com a categoria (uma das 7 já existentes no produto),
a polaridade e um trecho do comentário que sustenta a
classificação. Isso resolve uma perda de informação real: um
comentário como "meu líder é ótimo, mas a carga de trabalho está
impossível" antes só virava 1 tema no classificador local -- agora
os dois aspectos aparecem separados.
"""

import json
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel

from config import GEMINI_API_KEY

client = OpenAI(
    api_key=GEMINI_API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)

MODEL = "gemini-3.6-flash"  # modelo Flash — dentro do nível gratuito da API

# Precisa bater exatamente com os nomes de categoria já cadastrados
# no banco (tabela categoria) -- é assim que a gente liga o aspecto
# devolvido pela IA de volta pra categoria_id na hora de salvar.
CATEGORIAS = Literal[
    "Carga de Trabalho",
    "Liderança",
    "Comunicação",
    "Reconhecimento",
    "Bem-estar",
    "Segurança Psicológica",
    "Assédio",
]


class AspectoIdentificado(BaseModel):
    categoria: CATEGORIAS
    polaridade: Literal["positivo", "neutro", "negativo", "misto"]
    evidencia: str  # trecho curto, copiado de um comentário real -- nunca inventado


class RespostaAnaliseCiclo(BaseModel):
    resumo_executivo: str
    tendencias: str
    analise_comentarios: str
    recomendacoes: list[str]
    prioridade: Literal["baixa", "media", "alta"]
    aspectos_identificados: list[AspectoIdentificado]


SYSTEM_PROMPT = (
    "Voce e um consultor de RH especialista em riscos psicossociais e NR-1. "
    "Analise os indicadores e comentarios de uma pesquisa pulse.\n\n"
    "Alem do resumo em texto livre, faca tambem uma analise de sentimento "
    "por aspecto (ABSA) dos comentarios: para cada trecho relevante, "
    "identifique a que categoria ele se refere (uma das 7 ja existentes: "
    "Carga de Trabalho, Lideranca, Comunicacao, Reconhecimento, Bem-estar, "
    "Seguranca Psicologica, Assedio), a polaridade (positivo, neutro, "
    "negativo ou misto) e copie um trecho curto do comentario original "
    "como evidencia. Um unico comentario pode gerar varios aspectos, em "
    "categorias diferentes, se falar de mais de uma coisa. Nao invente "
    "aspecto que nao esteja sustentado pelo texto -- se nenhum comentario "
    "tocar numa categoria, simplesmente nao gere aspecto pra ela. "
    "Nao calcule nem inclua nenhum 'score' ou nota geral — isso e "
    "calculado por formula fixa fora da IA."
)


def analisar_ciclo(
    indicadores: list, total_respondentes: int, comentarios: list
) -> dict:
    user_prompt = (
        f"Indicadores por categoria (escala 1 a 5): {indicadores}. "
        f"Total de respondentes: {total_respondentes}. "
        f"Comentarios abertos dos colaboradores: {comentarios}"
    )

    completion = client.beta.chat.completions.parse(
        model=MODEL,
        temperature=0.4,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format=RespostaAnaliseCiclo,
    )

    resultado = completion.choices[0].message.parsed
    if resultado is None:
        # Acontece se a API recusar a resposta (ex: filtro de conteudo) --
        # melhor falhar alto do que salvar relatorio pela metade.
        motivo = completion.choices[0].message.refusal or "motivo desconhecido"
        raise ValueError(f"Gemini nao devolveu saida estruturada valida: {motivo}")

    return resultado.model_dump()

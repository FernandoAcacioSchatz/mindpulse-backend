"""
Cliente Gemini — substitui o antigo openai_client.py.

Usa a própria biblioteca 'openai' (já estava no requirements.txt,
não precisou instalar nada novo) apontando pra API do Gemini —
o Google oferece uma camada de compatibilidade com o formato da
OpenAI, então o resto do código (montagem do prompt, leitura da
resposta) não precisou mudar quase nada.
"""
import json
from openai import OpenAI
from config import GEMINI_API_KEY

client = OpenAI(
    api_key=GEMINI_API_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)

MODEL = "gemini-3.6-flash"  # modelo Flash — dentro do nível gratuito da API

SYSTEM_PROMPT = (
    "Voce e um consultor de RH especialista em riscos psicossociais e NR-1. "
    "Analise os indicadores e comentarios de uma pesquisa pulse e responda "
    "SOMENTE em JSON valido, sem markdown, com as chaves: resumo_executivo, "
    "tendencias, analise_comentarios, recomendacoes (lista de strings), "
    "prioridade (baixa, media ou alta). Nao calcule nem inclua nenhum "
    "'score' ou nota geral — isso e calculado por formula fixa fora da IA."
)


def analisar_ciclo(indicadores: list, total_respondentes: int, comentarios: list) -> dict:
    user_prompt = (
        f"Indicadores por categoria (escala 1 a 5): {indicadores}. "
        f"Total de respondentes: {total_respondentes}. "
        f"Comentarios abertos dos colaboradores: {comentarios}"
    )

    response = client.chat.completions.create(
        model=MODEL,
        temperature=0.4,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )

    conteudo = response.choices[0].message.content.strip()
    # O Gemini às vezes embrulha o JSON em ```json ... ``` mesmo
    # quando instruído a não fazer isso — removemos se aparecer.
    if conteudo.startswith("```"):
        conteudo = conteudo.strip("`")
        if conteudo.startswith("json"):
            conteudo = conteudo[4:]
        conteudo = conteudo.strip()

    return json.loads(conteudo)

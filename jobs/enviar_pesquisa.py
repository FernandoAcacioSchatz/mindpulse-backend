"""
Equivalente ao workflow n8n 'Enviar Pesquisa (v2 corrigido)' —
migração completa.

Melhoria em relação à versão n8n: processa TODAS as pesquisas
agendadas numa execução, não só 1 (era uma limitação conhecida
do node "limit: 1", documentada no Documento 10).

Idempotente: se rodar 2x por engano, não duplica token nem manda
e-mail 2x — verifica se o token já existe antes de criar.

Envio de e-mail EM PARALELO CONTROLADO (ThreadPoolExecutor, não
1-a-1): criar token é rápido (banco), mas mandar e-mail é uma
chamada de rede -- esperar 1000 chamadas sequenciais levaria uns
5 minutos à toa. 15 envios simultâneos equilibra velocidade sem
sobrecarregar a API da Brevo (que aceita bem mais que isso).

IMPORTANTE: no plano gratuito da Brevo existe um teto de 300
e-mails/dia -- isso não é resolvido por código nenhum, é limite
de conta. Cliente grande = upgrade de plano na Brevo, não mais
threads.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

from clients.supabase_client import supabase
from clients.brevo_client import enviar_email
from config import BASE_URL_FRONTEND

MAX_ENVIOS_SIMULTANEOS = 15


def rodar() -> dict:
    pesquisas = (
        supabase.table("pesquisa")
        .select("id, nome, ciclo_id, prazo_horas")
        .eq("status", "agendada")
        .execute()
        .data
    )

    resultado_geral = {"pesquisas_processadas": 0, "emails_enviados": 0, "emails_com_erro": 0, "detalhes": []}

    for pesquisa in pesquisas:
        detalhe = processar_uma_pesquisa(pesquisa)
        resultado_geral["pesquisas_processadas"] += 1
        resultado_geral["emails_enviados"] += detalhe["emails_enviados"]
        resultado_geral["emails_com_erro"] += detalhe["emails_com_erro"]
        resultado_geral["detalhes"].append(detalhe)

    print(f"[enviar_pesquisa] {resultado_geral}")
    return resultado_geral


def processar_uma_pesquisa(pesquisa: dict) -> dict:
    pesquisa_id = pesquisa["id"]
    prazo_horas = pesquisa.get("prazo_horas") or 24

    ciclo = supabase.table("ciclo").select("empresa_id").eq("id", pesquisa["ciclo_id"]).single().execute().data
    empresa_id = ciclo["empresa_id"]

    funcionarios = (
        supabase.table("funcionario")
        .select("id, nome, email")
        .eq("empresa_id", empresa_id)
        .eq("ativo", True)
        .execute()
        .data
    )

    expira_em = (datetime.now(timezone.utc) + timedelta(hours=prazo_horas)).isoformat()

    # ---- Passo 1: cria todos os tokens primeiro (rápido, só banco, sequencial está ok) ----
    fila_de_envio = []
    for funcionario in funcionarios:
        existente = (
            supabase.table("token_resposta")
            .select("id")
            .eq("pesquisa_id", pesquisa_id)
            .eq("funcionario_id", funcionario["id"])
            .maybe_single()
            .execute()
            .data
        )
        if existente:
            continue  # já processado numa execução anterior — idempotência

        token = (
            supabase.table("token_resposta")
            .insert({"pesquisa_id": pesquisa_id, "funcionario_id": funcionario["id"], "expira_em": expira_em})
            .execute()
            .data[0]
        )
        fila_de_envio.append((funcionario, token))

    # ---- Passo 2: envia os e-mails em paralelo controlado (a parte lenta) ----
    emails_enviados = 0
    emails_com_erro = 0

    def _enviar_um(item):
        funcionario, token = item
        link = f"{BASE_URL_FRONTEND}/pulse/{token['codigo']}"
        enviar_email(
            destinatario_email=funcionario["email"],
            destinatario_nome=funcionario["nome"],
            assunto="Pesquisa de Clima e Bem-estar — sua participação é importante",
            corpo_html=f"""
                <p>Olá, {funcionario['nome']}!</p>
                <p>Você foi convidado a participar de uma pesquisa rápida e anônima sobre o
                ambiente de trabalho. Leva menos de 5 minutos.</p>
                <p><a href="{link}">Responder pesquisa</a></p>
                <p>Este link é pessoal e expira em {prazo_horas} horas.</p>
            """,
        )

    with ThreadPoolExecutor(max_workers=MAX_ENVIOS_SIMULTANEOS) as executor:
        futuros = {executor.submit(_enviar_um, item): item for item in fila_de_envio}
        for futuro in as_completed(futuros):
            funcionario, _ = futuros[futuro]
            try:
                futuro.result()
                emails_enviados += 1
            except Exception as e:
                emails_com_erro += 1
                print(f"[enviar_pesquisa] Erro ao enviar para {funcionario['email']}: {e}")

    supabase.table("pesquisa").update(
        {"status": "enviada", "enviada_em": datetime.now(timezone.utc).isoformat()}
    ).eq("id", pesquisa_id).execute()

    return {
        "pesquisa_id": pesquisa_id,
        "nome": pesquisa["nome"],
        "funcionarios_totais": len(funcionarios),
        "emails_enviados": emails_enviados,
        "emails_com_erro": emails_com_erro,
    }

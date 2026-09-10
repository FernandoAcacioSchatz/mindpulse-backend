"""
Rotas de administração da plataforma — SÓ o dono do Radar (você)
tem acesso, nunca o RH de um cliente.

Propositalmente NÃO existe nenhuma rota aqui que devolva dados de
pesquisa/resposta/indicador de qualquer empresa — a única coisa que
esse módulo faz é PROVISIONAR (criar empresa + primeiro login),
nunca visualizar conteúdo sensível de cliente. Ver Documento 3
(regras de anonimato) — isso vale também pra você.
"""
import secrets
import string
from datetime import datetime, timezone

from fastapi import HTTPException

from clients.supabase_client import supabase


def gerar_senha_temporaria(tamanho: int = 14) -> str:
    alfabeto = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alfabeto) for _ in range(tamanho))


def provisionar_empresa(empresa_nome: str, empresa_cnpj: str | None, rh_nome: str, rh_email: str) -> dict:
    # 1. Cria a empresa
    empresa = supabase.table("empresa").insert({
        "nome": empresa_nome, "cnpj": empresa_cnpj,
    }).execute().data[0]

    # 2. Cria o login (via Admin API — só funciona com service_role key)
    senha_temporaria = gerar_senha_temporaria()
    try:
        resultado_auth = supabase.auth.admin.create_user({
            "email": rh_email,
            "password": senha_temporaria,
            "email_confirm": True,  # não exige confirmação por e-mail
        })
    except Exception as e:
        # limpa a empresa criada no passo 1, pra não deixar lixo pela metade
        supabase.table("empresa").delete().eq("id", empresa["id"]).execute()

        texto_erro = str(e)
        if "already been registered" in texto_erro or "already registered" in texto_erro:
            mensagem = f"O e-mail {rh_email} já está cadastrado em outra empresa. Use um e-mail diferente para esse RH."
        else:
            mensagem = "Não foi possível criar o login. Tente novamente em instantes."

        raise HTTPException(400, mensagem)

    auth_user_id = resultado_auth.user.id

    # 3. Vincula o login à empresa
    usuario_rh = supabase.table("usuario_rh").insert({
        "empresa_id": empresa["id"],
        "nome": rh_nome,
        "email": rh_email,
        "auth_user_id": auth_user_id,
        "papel": "rh",
    }).execute().data[0]

    return {
        "empresa_id": empresa["id"],
        "empresa_nome": empresa["nome"],
        "usuario_rh_id": usuario_rh["id"],
        "login_email": rh_email,
        "senha_temporaria": senha_temporaria,
        "aviso": "Envie essas credenciais pro cliente por um canal seguro. Ele deve trocar e-mail e senha em 'Meu Perfil' no primeiro acesso.",
    }


def atualizar_status_lead(lead_id: str, campo: str, marcar: bool, email_admin: str) -> dict:
    """
    Marca (ou desmarca) um lead como visto ou respondido, sempre
    gravando quem fez isso e quando -- nunca um campo de texto livre
    pra digitar nome, pra não ter "João" e "joao" como pessoas
    diferentes no rastro de auditoria.
    """
    if campo not in ("visto", "respondido"):
        raise HTTPException(400, "Campo inválido -- use 'visto' ou 'respondido'.")

    coluna_por = f"{campo}_por"
    coluna_em = f"{campo}_em"

    dados = {
        coluna_por: email_admin if marcar else None,
        coluna_em: datetime.now(timezone.utc).isoformat() if marcar else None,
    }

    resultado = supabase.table("lead").update(dados).eq("id", lead_id).execute().data
    if not resultado:
        raise HTTPException(404, "Lead não encontrado.")
    return resultado[0]


def salvar_observacao_lead(lead_id: str, observacoes: str) -> dict:
    """Anotação livre sobre o lead -- o que já foi combinado, retorno
    do cliente, próximo passo, etc. Sobrescreve o texto anterior (é
    1 campo de anotação corrente, não um histórico de comentários)."""
    resultado = supabase.table("lead").update({"observacoes": observacoes}).eq("id", lead_id).execute().data
    if not resultado:
        raise HTTPException(404, "Lead não encontrado.")
    return resultado[0]

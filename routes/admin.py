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
        raise HTTPException(400, f"Não foi possível criar o login: {e}")

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

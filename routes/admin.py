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


def listar_empresas() -> list[dict]:
    """
    Visão operacional de todas as empresas clientes -- quantidade de
    funcionário e de ciclo, e o status do ciclo mais recente. NUNCA
    devolve score, indicador, sentimento ou qualquer resultado de
    pesquisa -- só o essencial pra saber "quem está usando o quê".
    """
    empresas = supabase.table("empresa").select("id, nome").order("nome").execute().data or []

    resultado = []
    for emp in empresas:
        total_funcionarios = (
            supabase.table("funcionario")
            .select("id", count="exact")
            .eq("empresa_id", emp["id"])
            .execute()
            .count or 0
        )

        ciclos = (
            supabase.table("ciclo")
            .select("id, criado_em, pesquisa:pesquisa(status)")
            .eq("empresa_id", emp["id"])
            .order("criado_em", desc=True)
            .execute()
            .data or []
        )

        status_recente = None
        if ciclos:
            pesquisa = ciclos[0].get("pesquisa")
            pesquisa = pesquisa[0] if isinstance(pesquisa, list) else pesquisa
            status_recente = pesquisa["status"] if pesquisa else None

        resultado.append({
            "id": emp["id"],
            "nome": emp["nome"],
            "total_funcionarios": total_funcionarios,
            "total_ciclos": len(ciclos),
            "status_ciclo_mais_recente": status_recente,
        })

    return resultado


def detalhar_empresa(empresa_id: str) -> dict:
    """
    Linha do tempo operacional de 1 empresa -- cada ciclo com status e
    taxa de resposta (quantos de quantos), sem score nem indicador.
    """
    empresa = supabase.table("empresa").select("id, nome, cnpj").eq("id", empresa_id).maybe_single().execute().data
    if not empresa:
        raise HTTPException(404, "Empresa não encontrada.")

    total_funcionarios = (
        supabase.table("funcionario")
        .select("id", count="exact")
        .eq("empresa_id", empresa_id)
        .execute()
        .count or 0
    )

    ciclos = (
        supabase.table("ciclo")
        .select("id, nome, criado_em, pesquisa:pesquisa(id, status)")
        .eq("empresa_id", empresa_id)
        .order("criado_em", desc=True)
        .execute()
        .data or []
    )

    ciclos_detalhados = []
    for c in ciclos:
        pesquisa = c.get("pesquisa")
        pesquisa = pesquisa[0] if isinstance(pesquisa, list) else pesquisa

        respondidos, total_convidados = 0, 0
        if pesquisa:
            tokens = (
                supabase.table("token_resposta")
                .select("respondido")
                .eq("pesquisa_id", pesquisa["id"])
                .execute()
                .data or []
            )
            total_convidados = len(tokens)
            respondidos = len([t for t in tokens if t["respondido"]])

        ciclos_detalhados.append({
            "id": c["id"],
            "nome": c["nome"],
            "criado_em": c["criado_em"],
            "status": pesquisa["status"] if pesquisa else None,
            "respondidos": respondidos,
            "total_convidados": total_convidados,
        })

    return {
        "id": empresa["id"],
        "nome": empresa["nome"],
        "cnpj": empresa["cnpj"],
        "total_funcionarios": total_funcionarios,
        "ciclos": ciclos_detalhados,
    }

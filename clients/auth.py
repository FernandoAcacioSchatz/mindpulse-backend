"""
Segurança do backend.

Dois esquemas de autenticação, cada um pro tipo certo de chamador:

1. JWT do Supabase (Bearer token) — para chamadas que vêm de um RH
   LOGADO na tela (ex: clicar em "Encerrar pesquisa"). Reaproveita
   o mesmo token que o Supabase Auth já emite no login — não
   inventamos um sistema de login paralelo.

2. Chave de sistema (X-API-Key) — para chamadas de sistema pra
   sistema, sem usuário envolvido: o Supabase Database Webhook
   chamando /notificar-alerta-critico, ou testes manuais dos
   endpoints de /executar/*.

Usa fastapi.security, então o /docs ganha um botão "Authorize"
de verdade — autoriza uma vez, testa todos os endpoints protegidos
sem repetir o token a cada chamada.
"""
import jwt
from jwt import PyJWKClient
from fastapi import Depends, HTTPException
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from clients.supabase_client import supabase
from config import ADMIN_EMAILS, BACKEND_API_KEY, SUPABASE_URL

_bearer_scheme = HTTPBearer(description="Token de sessão do Supabase Auth (RH logado)")
_api_key_scheme = APIKeyHeader(name="X-API-Key", description="Chave de sistema, para chamadas automatizadas")


# Seu projeto usa o sistema novo de chaves assimétricas do Supabase
# (ECC P-256) -- verificamos com a chave PÚBLICA, buscada automaticamente
# do endpoint JWKS do próprio projeto. Nenhum segredo pra guardar aqui.
_jwks_url = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
_jwk_client = PyJWKClient(_jwks_url, cache_keys=True)


def verificar_jwt_supabase(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> dict:
    """Valida o JWT emitido pelo Supabase Auth e devolve o payload decodificado."""
    try:
        chave_publica = _jwk_client.get_signing_key_from_jwt(credentials.credentials)
        return jwt.decode(
            credentials.credentials,
            chave_publica.key,
            algorithms=["ES256"],
            audience="authenticated",
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Sessão expirada — faça login novamente.")
    except Exception:
        raise HTTPException(401, "Token inválido.")


def verificar_rh_pertence_a_empresa(auth_user_id: str, empresa_id: str) -> None:
    """
    Checagem de autorização (além da autenticação acima): confirma
    que o usuário logado é RH ativo DAQUELA empresa específica.

    Necessário porque o backend usa a service_role key, que ignora
    RLS — esta função substitui manualmente a proteção que o RLS
    dá de graça pro front-end.
    """
    rh = (
        supabase.table("usuario_rh")
        .select("empresa_id, ativo")
        .eq("auth_user_id", auth_user_id)
        .maybe_single()
        .execute()
        .data
    )
    if not rh or not rh["ativo"]:
        raise HTTPException(403, "Usuário não encontrado ou inativo.")
    if rh["empresa_id"] != empresa_id:
        raise HTTPException(403, "Você não tem permissão para acessar dados dessa empresa.")


def verificar_chave_sistema(chave: str = Depends(_api_key_scheme)) -> None:
    """Protege endpoints chamados por sistema, não por um RH logado."""
    if not BACKEND_API_KEY:
        raise HTTPException(500, "BACKEND_API_KEY não configurada no servidor.")
    if chave != BACKEND_API_KEY:
        raise HTTPException(401, "Chave de API inválida.")


def verificar_admin(auth: dict = Depends(verificar_jwt_supabase)) -> dict:
    """
    Protege as rotas de /admin — exige um JWT válido E que o e-mail
    do token esteja na lista da equipe Radar (ADMIN_EMAILS).
    Nenhum RH de cliente passa por aqui, mesmo logado.
    """
    if not ADMIN_EMAILS:
        raise HTTPException(500, "ADMIN_EMAILS não configurado no servidor.")
    if auth.get("email") not in ADMIN_EMAILS:
        raise HTTPException(403, "Acesso restrito à equipe Radar.")
    return auth

import jwt
from jwt import PyJWKClient
from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from clients.supabase_client import supabase
from clients.sessoes import obter_access_token
from config import ADMIN_EMAILS, BACKEND_API_KEY, SUPABASE_URL

_bearer_scheme = HTTPBearer(description="Token de sessão do Supabase Auth (RH logado)", auto_error=False)
_api_key_scheme = APIKeyHeader(name="X-API-Key", description="Chave de sistema, para chamadas automatizadas")

NOME_COOKIE_SESSAO = "radar_sessao"


_jwks_url = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
_jwk_client = PyJWKClient(_jwks_url, cache_keys=True)


def _validar_token(token: str) -> dict:
    try:
        chave_publica = _jwk_client.get_signing_key_from_jwt(token)
        return jwt.decode(token, chave_publica.key, algorithms=["ES256"], audience="authenticated")
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Sessão expirada — faça login novamente.")
    except Exception:
        raise HTTPException(401, "Token inválido.")


def verificar_jwt_supabase(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> dict:
    token = obter_access_token(request.cookies.get(NOME_COOKIE_SESSAO))
    if not token and credentials:
        token = credentials.credentials
    if not token:
        raise HTTPException(401, "Não autenticado.")
    return _validar_token(token)


def verificar_rh_pertence_a_empresa(auth_user_id: str, empresa_id: str) -> None:
    resposta = (
        supabase.table("usuario_rh")
        .select("empresa_id, ativo")
        .eq("auth_user_id", auth_user_id)
        .maybe_single()
        .execute()
    )
    rh = resposta.data if resposta else None
    if not rh or not rh["ativo"]:
        raise HTTPException(403, "Usuário não encontrado ou inativo.")
    if rh["empresa_id"] != empresa_id:
        raise HTTPException(403, "Você não tem permissão para acessar dados dessa empresa.")


def verificar_chave_sistema(chave: str = Depends(_api_key_scheme)) -> None:
    if not BACKEND_API_KEY:
        raise HTTPException(500, "BACKEND_API_KEY não configurada no servidor.")
    if chave != BACKEND_API_KEY:
        raise HTTPException(401, "Chave de API inválida.")


def verificar_admin(auth: dict = Depends(verificar_jwt_supabase)) -> dict:
    if not ADMIN_EMAILS:
        raise HTTPException(500, "ADMIN_EMAILS não configurado no servidor.")
    if auth.get("email") not in ADMIN_EMAILS:
        raise HTTPException(403, "Acesso restrito à equipe Radar.")
    return auth

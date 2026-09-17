"""
Proxy transparente entre o navegador e o Supabase.

Por que isso existe: o token de sessão (JWT) nunca pode ser lido por
JavaScript -- nem no localStorage, nem numa variável comum -- porque
um XSS rodando na mesma página lê os dois igual. A única defesa de
verdade é o token só existir dentro de um cookie httpOnly, que o
próprio navegador anexa sozinho nas chamadas, sem o JS nunca tocar
nele.

Como o Supabase não sabe ler cookie customizado nosso, esse proxy é
quem faz a ponte: recebe a chamada do navegador (com o cookie, que
o navegador manda automático), lê o token de dentro do cookie, e só
AÍ monta o cabeçalho Authorization de verdade antes de repassar pro
Supabase de verdade. O JavaScript nunca vê o token em nenhum momento
desse processo.
"""
import httpx
from fastapi import APIRouter, Request, Response

from config import SUPABASE_URL, SUPABASE_ANON_KEY

router = APIRouter()

# 1 conexão HTTP compartilhada, criada uma vez só e reaproveitada em
# toda chamada -- antes, cada requisição abria um cliente novo
# (com pool de conexão e contexto SSL próprios), o que consumia
# memória a mais a cada chamada simultânea. Isso contribuiu pro
# backend estourar o limite de memória do Render sob uso mais
# intenso (ex: várias telas carregando dado ao mesmo tempo).
_cliente_http: httpx.AsyncClient | None = None


def _obter_cliente_http() -> httpx.AsyncClient:
    global _cliente_http
    if _cliente_http is None:
        _cliente_http = httpx.AsyncClient(timeout=30.0)
    return _cliente_http

NOME_COOKIE_ACCESS = "radar_access_token"
NOME_COOKIE_REFRESH = "radar_refresh_token"

# Em produção (Render + Vercel são domínios diferentes) o cookie
# PRECISA de SameSite=None + Secure pra ser enviado entre domínios --
# sem isso, o navegador recusa mandar o cookie de volta.
def _opcoes_cookie(request: Request) -> dict:
    """
    Em produção (Render/Vercel, sempre HTTPS) o cookie usa
    Secure+SameSite=None, obrigatório pra viajar entre domínios
    diferentes. Rodando local (Live Server + uvicorn, em HTTP puro),
    Secure faria o navegador recusar o cookie -- então usa
    SameSite=Lax sem Secure, que funciona entre portas diferentes do
    mesmo host (127.0.0.1:5500 <-> 127.0.0.1:8000). Se ajusta sozinho
    olhando o protocolo de quem chamou -- nunca precisa trocar nada
    na mão antes de subir pra produção.
    """
    https = request.url.scheme == "https"
    return dict(
        httponly=True,
        secure=https,
        samesite="none" if https else "lax",
        path="/",
    )


def _extrair_token_do_cookie(request: Request) -> str | None:
    return request.cookies.get(NOME_COOKIE_ACCESS)


async def _repassar_para_supabase(request: Request, caminho: str) -> httpx.Response:
    """Repassa a chamada pro Supabase de verdade, com o token certo.

    Copia TODOS os cabeçalhos que o navegador mandou (Prefer, Range,
    Accept-Profile, etc. -- o supabase-js manda vários além de
    apikey/Authorization, e cada um controla um comportamento
    diferente do PostgREST, tipo "me devolve a linha que acabei de
    criar"). Só remove os que não fazem sentido repassar (Host, o
    Cookie -- que é NOSSO, o Supabase não usa -- e Content-Length,
    que o httpx recalcula sozinho). Depois disso, sobrescreve
    apikey/Authorization com os valores certos."""
    token = _extrair_token_do_cookie(request)

    cabecalhos = {
        chave: valor for chave, valor in request.headers.items()
        if chave.lower() not in ("host", "cookie", "content-length", "connection")
    }
    cabecalhos["apikey"] = SUPABASE_ANON_KEY
    # Só anexa Authorization com o token se existir sessão -- sem isso,
    # a chamada segue como "anon" (é o comportamento certo pra rota
    # pública, tipo a tela de pesquisa que o funcionário responde
    # sem login).
    cabecalhos["Authorization"] = f"Bearer {token}" if token else f"Bearer {SUPABASE_ANON_KEY}"

    corpo = await request.body()
    url_destino = f"{SUPABASE_URL}/{caminho}"

    cliente = _obter_cliente_http()
    return await cliente.request(
        method=request.method,
        url=url_destino,
        params=request.query_params,
        headers=cabecalhos,
        content=corpo,
        timeout=30.0,
    )


def _resposta_repassada(resp_supabase: httpx.Response) -> Response:
    """Devolve a resposta do Supabase pro navegador, sem alterar nada."""
    return Response(
        content=resp_supabase.content,
        status_code=resp_supabase.status_code,
        media_type=resp_supabase.headers.get("content-type", "application/json"),
    )


@router.api_route("/supabase-proxy/auth/v1/token", methods=["POST"])
async def proxy_login_ou_refresh(request: Request):
    """
    Login (signInWithPassword) e renovação automática de sessão
    passam por aqui -- os dois usam o mesmo endpoint do Supabase,
    diferenciados pelo parâmetro grant_type na URL.

    Depois que o Supabase confirma a sessão, o token NUNCA volta no
    corpo da resposta -- ele é extraído aqui e vira cookie httpOnly.
    O que sobra no corpo é só o que o frontend realmente precisa pra
    saber "quem é esse usuário" (sem o token em si).
    """
    resp = await _repassar_para_supabase(request, "auth/v1/token")

    if resp.status_code != 200:
        return _resposta_repassada(resp)

    dados = resp.json()
    access_token = dados.get("access_token")
    refresh_token = dados.get("refresh_token")
    usuario = dados.get("user")

    corpo_seguro = {"user": usuario, "autenticado": bool(access_token)}
    resposta = Response(content=__import__("json").dumps(corpo_seguro), media_type="application/json")

    opcoes = _opcoes_cookie(request)
    if access_token:
        resposta.set_cookie(NOME_COOKIE_ACCESS, access_token, max_age=3600, **opcoes)
    if refresh_token:
        resposta.set_cookie(NOME_COOKIE_REFRESH, refresh_token, max_age=60 * 60 * 24 * 30, **opcoes)

    return resposta


@router.post("/supabase-proxy/auth/v1/logout")
async def proxy_logout(request: Request):
    """Invalida a sessão no Supabase E limpa os 2 cookies."""
    await _repassar_para_supabase(request, "auth/v1/logout")
    resposta = Response(status_code=204)
    resposta.delete_cookie(NOME_COOKIE_ACCESS, path="/")
    resposta.delete_cookie(NOME_COOKIE_REFRESH, path="/")
    return resposta


@router.get("/supabase-proxy/session/me")
async def sessao_atual(request: Request):
    """
    Substitui supabase.auth.getUser() -- em vez do frontend ler o
    usuário de um token que ele nunca teve acesso, ele pergunta pro
    backend "quem sou eu", e o backend responde lendo o cookie.
    """
    token = _extrair_token_do_cookie(request)
    if not token:
        return {"user": None}

    cliente = _obter_cliente_http()
    resp = await cliente.get(
        f"{SUPABASE_URL}/auth/v1/user",
        headers={"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {token}"},
        timeout=10.0,
    )
    if resp.status_code != 200:
        return {"user": None}
    return {"user": resp.json()}


@router.api_route("/supabase-proxy/rest/v1/{caminho:path}", methods=["GET", "POST", "PATCH", "DELETE", "PUT"])
async def proxy_rest(request: Request, caminho: str):
    """
    Toda consulta de dado (.from(), .rpc()) passa por aqui. Repassa
    pro Supabase de verdade, injetando o token do cookie -- o corpo
    da resposta volta inalterado, porque dado de tabela não tem
    token nenhum dentro, só o resultado da consulta em si.
    """
    resp = await _repassar_para_supabase(request, f"rest/v1/{caminho}")
    return _resposta_repassada(resp)


@router.api_route("/supabase-proxy/storage/v1/{caminho:path}", methods=["GET", "POST", "PATCH", "DELETE", "PUT"])
async def proxy_storage(request: Request, caminho: str):
    """
    Upload/download/exclusão de arquivo (evidência, etc.) usa uma
    API separada do Supabase (Storage, não REST) -- mesmo princípio
    do proxy_rest, só que repassando pra /storage/v1/ em vez de
    /rest/v1/. Faltava essa rota -- por isso upload de evidência
    dava 404 antes.
    """
    resp = await _repassar_para_supabase(request, f"storage/v1/{caminho}")
    return _resposta_repassada(resp)

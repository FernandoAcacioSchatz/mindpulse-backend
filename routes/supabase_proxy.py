import httpx
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from config import SUPABASE_URL, SUPABASE_ANON_KEY
from clients.sessoes import criar_sessao, obter_access_token, remover_sessao

router = APIRouter()

_cliente_http: httpx.AsyncClient | None = None


def _obter_cliente_http() -> httpx.AsyncClient:
    global _cliente_http
    if _cliente_http is None:
        _cliente_http = httpx.AsyncClient(timeout=30.0)
    return _cliente_http


NOME_COOKIE_SESSAO = "radar_sessao"

NOMES_COOKIES_ANTIGOS = ("radar_access_token", "radar_refresh_token")


def _limpar_cookies_antigos(resposta: Response, request: Request) -> None:
    opcoes = _opcoes_cookie(request)
    for nome in NOMES_COOKIES_ANTIGOS:
        resposta.delete_cookie(nome, path="/", secure=opcoes["secure"], samesite=opcoes["samesite"])


def _opcoes_cookie(request: Request) -> dict:
    https = request.url.scheme == "https"
    return dict(
        httponly=True,
        secure=https,
        samesite="none" if https else "lax",
        path="/",
    )


def _extrair_token_do_cookie(request: Request) -> str | None:
    session_id = request.cookies.get(NOME_COOKIE_SESSAO)
    return obter_access_token(session_id)


async def _repassar_para_supabase(request: Request, caminho: str) -> httpx.Response:
    token = _extrair_token_do_cookie(request)

    CABECALHOS_RELEVANTES = ("accept", "prefer", "range", "range-unit", "accept-profile", "content-profile", "content-type")
    cabecalhos = {
        chave: valor for chave, valor in request.headers.items()
        if chave.lower() in CABECALHOS_RELEVANTES
    }
    cabecalhos["apikey"] = SUPABASE_ANON_KEY
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
    return Response(
        content=resp_supabase.content,
        status_code=resp_supabase.status_code,
        media_type=resp_supabase.headers.get("content-type", "application/json"),
    )


@router.api_route("/supabase-proxy/auth/v1/token", methods=["POST"])
async def proxy_login_ou_refresh(request: Request):
    resp = await _repassar_para_supabase(request, "auth/v1/token")

    if resp.status_code != 200:
        return _resposta_repassada(resp)

    dados = resp.json()
    access_token = dados.get("access_token")
    refresh_token = dados.get("refresh_token")
    usuario = dados.get("user")

    corpo_seguro = {"user": usuario, "autenticado": bool(access_token)}
    resposta = Response(content=__import__("json").dumps(corpo_seguro), media_type="application/json")

    if access_token:
        session_id = criar_sessao(access_token, refresh_token)
        resposta.set_cookie(NOME_COOKIE_SESSAO, session_id, max_age=60 * 60 * 24 * 7, **_opcoes_cookie(request))
    _limpar_cookies_antigos(resposta, request)

    return resposta


@router.post("/supabase-proxy/auth/v1/logout")
async def proxy_logout(request: Request):
    await _repassar_para_supabase(request, "auth/v1/logout")
    remover_sessao(request.cookies.get(NOME_COOKIE_SESSAO))
    resposta = Response(status_code=204)
    opcoes = _opcoes_cookie(request)
    resposta.delete_cookie(NOME_COOKIE_SESSAO, path="/", secure=opcoes["secure"], samesite=opcoes["samesite"])
    _limpar_cookies_antigos(resposta, request)
    return resposta


@router.post("/supabase-proxy/recuperar-senha")
async def recuperar_senha(request: Request):
    corpo = await request.json()
    token_recuperacao = corpo.get("token")
    nova_senha = corpo.get("senha")
    if not token_recuperacao or not nova_senha:
        return JSONResponse({"error": "dados incompletos"}, status_code=400)

    cliente = _obter_cliente_http()
    resp = await cliente.put(
        f"{SUPABASE_URL}/auth/v1/user",
        headers={
            "apikey": SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {token_recuperacao}",
            "Content-Type": "application/json",
        },
        json={"password": nova_senha},
        timeout=15.0,
    )
    return _resposta_repassada(resp)


@router.api_route("/supabase-proxy/auth/v1/{caminho:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_auth_generico(request: Request, caminho: str):
    resp = await _repassar_para_supabase(request, f"auth/v1/{caminho}")
    return _resposta_repassada(resp)


@router.get("/supabase-proxy/session/me")
async def sessao_atual(request: Request):
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
    resp = await _repassar_para_supabase(request, f"rest/v1/{caminho}")
    return _resposta_repassada(resp)


@router.api_route("/supabase-proxy/storage/v1/{caminho:path}", methods=["GET", "POST", "PATCH", "DELETE", "PUT"])
async def proxy_storage(request: Request, caminho: str):
    resp = await _repassar_para_supabase(request, f"storage/v1/{caminho}")
    return _resposta_repassada(resp)

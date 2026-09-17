"""
Guarda a sessão de cada RH logado no lado do servidor -- o cookie
enviado ao navegador carrega só um identificador curto e aleatório,
nunca o token JWT em si.

Por que isso existe: o cookie chegou a carregar os 2 tokens completos
do Supabase (acesso + renovação), que juntos passam de várias
centenas de caracteres -- somado aos cabeçalhos extras que o
supabase-js manda em toda consulta (apikey, Prefer, etc.), isso
estourava o limite de tamanho de cabeçalho que o Cloudflare aceita,
causando "400 Bad Request" nas consultas de dado (mas não em chamadas
mais simples, tipo /session/me, que não carregam esse peso extra).

Limitação aceita por ora: como isso vive em memória, reiniciar o
processo do backend (deploy novo, ou o Render reiniciando sozinho)
derruba todas as sessões ativas -- todo mundo precisa logar de novo.
Pro tamanho atual do Radar, isso é aceitável; se um dia isso incomodar,
o próximo passo seria mover pra uma tabela no próprio Supabase.
"""
import secrets
import time

_SESSOES: dict[str, dict] = {}
_VALIDADE_SEGUNDOS = 60 * 60 * 24 * 7  # 7 dias -- mesmo raciocínio do refresh_token de antes


def criar_sessao(access_token: str, refresh_token: str | None) -> str:
    """Cria uma sessão nova, devolve o identificador curto pra virar cookie."""
    session_id = secrets.token_urlsafe(32)
    _SESSOES[session_id] = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "criado_em": time.time(),
    }
    return session_id


def obter_access_token(session_id: str | None) -> str | None:
    """Devolve o token de acesso de verdade a partir do identificador curto,
    ou None se a sessão não existir ou tiver expirado."""
    if not session_id:
        return None
    sessao = _SESSOES.get(session_id)
    if not sessao:
        return None
    if time.time() - sessao["criado_em"] > _VALIDADE_SEGUNDOS:
        _SESSOES.pop(session_id, None)
        return None
    return sessao["access_token"]


def remover_sessao(session_id: str | None) -> None:
    if session_id:
        _SESSOES.pop(session_id, None)

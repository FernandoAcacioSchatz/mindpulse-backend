import secrets
import time

_SESSOES: dict[str, dict] = {}
_VALIDADE_SEGUNDOS = 60 * 60 * 24 * 7


def criar_sessao(access_token: str, refresh_token: str | None) -> str:
    session_id = secrets.token_urlsafe(32)
    _SESSOES[session_id] = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "criado_em": time.time(),
    }
    return session_id


def obter_access_token(session_id: str | None) -> str | None:
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

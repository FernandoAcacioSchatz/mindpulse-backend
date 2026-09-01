"""
Cliente Supabase do backend — usa a service_role key, então ignora
RLS por completo (é por isso que o n8n conseguia ler/escrever em
qualquer tabela). Nunca exponha essa chave no front-end.
"""
import time

import httpx
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def com_nova_tentativa(func, tentativas: int = 2, espera_segundos: float = 0.5):
    """
    Roda uma chamada ao Supabase com 1 nova tentativa automática, se
    der erro de rede transitório -- comum logo depois do Render
    "acordar" de dormir, quando a conexão antiga em cache já não é
    mais válida do outro lado. Não tenta de novo pra outros tipos de
    erro (validação, permissão, etc.) -- só rede.

    Uso: com_nova_tentativa(lambda: supabase.table("x").select("*").execute())
    """
    ultimo_erro = None
    for tentativa in range(tentativas):
        try:
            return func()
        except (httpx.ReadError, httpx.ConnectError, httpx.RemoteProtocolError) as e:
            ultimo_erro = e
            if tentativa < tentativas - 1:
                print(f"[supabase_client] Erro de rede transitório, tentando de novo: {e}")
                time.sleep(espera_segundos)
    raise ultimo_erro

"""
Cliente Supabase do backend — usa a service_role key, então ignora
RLS por completo (é por isso que o n8n conseguia ler/escrever em
qualquer tabela). Nunca exponha essa chave no front-end.
"""
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

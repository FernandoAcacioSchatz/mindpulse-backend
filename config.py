"""
Configuração central — carrega as variáveis de ambiente uma vez só,
reaproveitadas em todo o resto do backend.
"""
import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

# JWT Secret do Supabase — usado pra VERIFICAR (não gerar) os tokens
# que o Supabase Auth já emite quando o RH loga. Fica em:
# Supabase → Project Settings → API → JWT Settings → JWT Secret
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
BREVO_SENDER_EMAIL = os.environ.get("BREVO_SENDER_EMAIL", "contato@mindpulse.app")

BASE_URL_FRONTEND = os.environ.get("BASE_URL_FRONTEND", "https://mindpulse-app.vercel.app")

# Lista de e-mails autorizados a chamar as rotas de /admin — a
# equipe da Radar, separado por vírgula. Nenhum RH de empresa
# cliente entra nessa lista, não importa o "papel" dentro da
# própria empresa dele.
ADMIN_EMAILS = [
    e.strip() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()
]

# Chave que protege os endpoints do backend — qualquer chamador
# (agendador externo, Supabase Database Webhook, futuramente a
# tela do RH) precisa enviar essa mesma chave no cabeçalho
# 'X-API-Key'. Gere uma string aleatória longa, nunca use um
# valor previsível.
BACKEND_API_KEY = os.environ.get("BACKEND_API_KEY", "")

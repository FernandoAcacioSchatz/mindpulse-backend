import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

RABBITMQ_URL = os.environ.get("RABBITMQ_URL", "")
RABBITMQ_URL_PUBLISHER = os.environ.get("RABBITMQ_URL_PUBLISHER", "")
RABBITMQ_URL_CONSUMIDOR = os.environ.get("RABBITMQ_URL_CONSUMIDOR", "")

if RABBITMQ_URL and (not RABBITMQ_URL_PUBLISHER or not RABBITMQ_URL_CONSUMIDOR):
    print(
        "[config] Aviso esperado: RABBITMQ_URL_PUBLISHER e/ou "
        "RABBITMQ_URL_CONSUMIDOR não configuradas -- usando a credencial "
        "única (RABBITMQ_URL) pra tudo, porque o plano gratuito da CloudAMQP "
        "não permite criar usuários novos (ver RABBITMQ_AUTORIZACAO.md)."
    )
    RABBITMQ_URL_PUBLISHER = RABBITMQ_URL_PUBLISHER or RABBITMQ_URL
    RABBITMQ_URL_CONSUMIDOR = RABBITMQ_URL_CONSUMIDOR or RABBITMQ_URL

BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
BREVO_SENDER_EMAIL = os.environ.get("BREVO_SENDER_EMAIL", "contato@mindpulse.app")

BREVO_WEBHOOK_SECRET = os.environ.get("BREVO_WEBHOOK_SECRET", "")

BASE_URL_FRONTEND = os.environ.get("BASE_URL_FRONTEND", "https://mindpulse-app.vercel.app")

ADMIN_EMAILS = [
    e.strip() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()
]

BACKEND_API_KEY = os.environ.get("BACKEND_API_KEY", "")

SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "sb_publishable_REU_k-pvp9jluFZ5PmkLLg_mGeZ0HYT")

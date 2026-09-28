import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

BREVO_API_KEY = os.environ.get("BREVO_API_KEY", "")
BREVO_SENDER_EMAIL = os.environ.get("BREVO_SENDER_EMAIL", "contato@mindpulse.app")

BASE_URL_FRONTEND = os.environ.get("BASE_URL_FRONTEND", "https://mindpulse-app.vercel.app")

ADMIN_EMAILS = [
    e.strip() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()
]

BACKEND_API_KEY = os.environ.get("BACKEND_API_KEY", "")

SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "sb_publishable_REU_k-pvp9jluFZ5PmkLLg_mGeZ0HYT")

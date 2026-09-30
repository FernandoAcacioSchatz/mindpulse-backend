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

# Connection strings do RabbitMQ (CloudAMQP) -- formato amqps://user:senha@host/vhost.
# Nunca hardcoded; configurar como variável de ambiente no Render/VM.
#
# Autorização por papel (Etapa 3 do trabalho de Sistemas Distribuídos):
# o código já está preparado pra 3 credenciais de papel distinto (admin,
# publicador, consumidor -- ver RABBITMQ_AUTORIZACAO.md pra matriz de
# permissão completa e a justificativa de cada campo), mas HOJE elas
# ainda apontam pra UMA ÚNICA credencial real. Motivo, confirmado na
# documentação oficial: gerenciar usuários/permissões no RabbitMQ só é
# liberado nos planos "dedicados" da CloudAMQP (Sassy Squirrel pra
# cima) -- o plano gratuito usado aqui (Little Lemur, compartilhado)
# não expõe essa função, então não existe hoje como criar
# radar_publisher/radar_consumidor de verdade sem upgrade pago ou sem
# trocar de broker. Ver RABBITMQ_AUTORIZACAO.md, seção "Limitação
# descoberta", pra fonte e para os dois caminhos que resolveriam isso
# de vez (upgrade de plano, ou self-host num VM próprio).
#
# - RABBITMQ_URL              -- a credencial única de hoje. Também é a
#   única usada por scripts/provisionar_topologia.py.
# - RABBITMQ_URL_PUBLISHER    -- vazio hoje (não existe usuário
#   radar_publisher ainda) -- cai automaticamente pra RABBITMQ_URL.
# - RABBITMQ_URL_CONSUMIDOR   -- vazio hoje (não existe usuário
#   radar_consumidor ainda) -- cai automaticamente pra RABBITMQ_URL.
#
# O ganho real de HOJE não é ter 3 segredos diferentes (ainda não tem)
# -- é que nenhum processo em produção (jobs, workers) declara mais
# topologia sozinho (não usa mais permissão "configure" em nada); só o
# script de provisionamento faz isso. Isso já reduz o raio de ação de
# cada processo, e o dia que os 2 usuários novos existirem (upgrade ou
# migração de broker), a mudança é só preencher as 2 variáveis abaixo
# -- nenhum código muda.
RABBITMQ_URL = os.environ.get("RABBITMQ_URL", "")
RABBITMQ_URL_PUBLISHER = os.environ.get("RABBITMQ_URL_PUBLISHER", "")
RABBITMQ_URL_CONSUMIDOR = os.environ.get("RABBITMQ_URL_CONSUMIDOR", "")

if RABBITMQ_URL and (not RABBITMQ_URL_PUBLISHER or not RABBITMQ_URL_CONSUMIDOR):
    # Esperado hoje (ver comentário acima) -- plano gratuito da CloudAMQP
    # não permite criar radar_publisher/radar_consumidor ainda. Isto NÃO
    # é um erro de configuração pra corrigir agora; é o estado normal até
    # uma eventual migração de plano/broker (RABBITMQ_AUTORIZACAO.md).
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

# Segredo simples no caminho da URL do webhook (/webhooks/brevo/{chave}) --
# a Brevo não assina os webhooks, então isso evita que alguém de fora
# descubra a URL e mande eventos falsos de entrega/bounce. Configurar a
# MESMA string ao cadastrar o webhook no painel da Brevo.
BREVO_WEBHOOK_SECRET = os.environ.get("BREVO_WEBHOOK_SECRET", "")

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

# Chave pública (anon/publishable) do Supabase -- é a mesma que hoje
# fica hardcoded no frontend (não é segredo). O proxy usa ela em
# TODA chamada repassada, no lugar da service_role -- assim RLS
# continua valendo normalmente, igual valeria se o navegador
# chamasse o Supabase direto.
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "sb_publishable_REU_k-pvp9jluFZ5PmkLLg_mGeZ0HYT")

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
# Autorização por papel (Etapa 3 do trabalho de Sistemas Distribuídos --
# antes disso, um único usuário com acesso total fazia tudo, produtor e
# consumidor, sem nenhuma separação de permissão real):
#
# - RABBITMQ_URL              -- credencial ADMIN (a original). Único uso
#   permitido: scripts/provisionar_topologia.py, rodado manualmente sempre
#   que a topologia (exchange/filas/bindings) precisa ser criada ou mudar.
#   NUNCA usada pelos processos que ficam no ar (jobs, workers, rotas).
# - RABBITMQ_URL_PUBLISHER    -- usuário "radar_publisher": só publica na
#   exchange radar.eventos (permissão write nela, configure e read vazios).
#   Usada por clients/rabbitmq_client.py::publicar_mensagens (chamada
#   pelos jobs que enfileiram convites/lembretes).
# - RABBITMQ_URL_CONSUMIDOR   -- usuário "radar_consumidor": só lê/consome
#   das filas fila.* (permissão read nelas) e só publica na exchange
#   default/nomeless (permissão write == "^$", usada pra mandar mensagem
#   pra DLQ por nome de fila). Usada pelos dois workers consumidores e
#   pelo monitor da DLQ (jobs/monitorar_dlq.py).
#
# Ver o runbook entregue junto (RABBITMQ_AUTORIZACAO.md) pros valores
# exatos de configure/write/read a cadastrar no painel do CloudAMQP.
RABBITMQ_URL = os.environ.get("RABBITMQ_URL", "")
RABBITMQ_URL_PUBLISHER = os.environ.get("RABBITMQ_URL_PUBLISHER", "")
RABBITMQ_URL_CONSUMIDOR = os.environ.get("RABBITMQ_URL_CONSUMIDOR", "")

if RABBITMQ_URL and (not RABBITMQ_URL_PUBLISHER or not RABBITMQ_URL_CONSUMIDOR):
    # Fallback só pra não quebrar um deploy antigo enquanto os usuários
    # novos não foram criados no CloudAMQP -- ver runbook. Uma vez migrado,
    # RABBITMQ_URL (admin) não deveria mais aparecer nesse print nunca.
    print(
        "[config] AVISO: RABBITMQ_URL_PUBLISHER e/ou RABBITMQ_URL_CONSUMIDOR não "
        "configuradas -- caindo de volta pra credencial admin (RABBITMQ_URL) por "
        "enquanto. Isso NÃO tem a separação de autorização da Etapa 3; crie os "
        "usuários radar_publisher/radar_consumidor no CloudAMQP e configure as "
        "duas variáveis novas assim que possível."
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

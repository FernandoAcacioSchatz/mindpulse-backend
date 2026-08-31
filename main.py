"""
Radar Backend — ponto de entrada.

Roda localmente com:
    uvicorn main:app --reload

Gatilhos, espelhando o que existia no n8n:
- Rotas HTTP (/executar/*, /encerrar-pesquisa, /notificar-*) chamadas
  externamente — pela tela do RH, por cron externo (cron-job.org),
  ou pelo Supabase Database Webhook.

O agendador interno (APScheduler) que existia aqui foi removido —
o Render gratuito "dorme" sem aviso, e um agendador que depende do
processo estar de pé no segundo exato não é confiável nesse plano.
Toda a parte de horário (enviar 8h, lembrete 8h30/11h30, encerrar
10h) agora é responsabilidade do cron-job.org, configurado
externamente — ver Documento 30. Rodar os dois ao mesmo tempo já
causou o backend disparando 3h adiantado (tratando "8h" como UTC
em vez de horário de Brasília) — não reintroduzir sem entender essa
causa primeiro.

Dois esquemas de segurança (ver clients/auth.py):
- JWT do Supabase → endpoints chamados por RH logado
- Chave de sistema → endpoints chamados por automação/webhook
"""
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from clients.auth import verificar_admin, verificar_chave_sistema, verificar_jwt_supabase, verificar_rh_pertence_a_empresa
from clients.supabase_client import supabase
from jobs import enviar_pesquisa, lembrete_diario, lembrete_segundo, encerrar_automatico
from routes import admin, encerrar_pesquisa, notificar_critico, notificar_lead
from schemas import EncerrarPesquisaPayload, NotificarCriticoPayload, NotificarLeadPayload, ProvisionarEmpresaPayload

# Origens autorizadas a chamar o backend diretamente do navegador.
# Sem isso, o navegador bloqueia a chamada mesmo com JWT correto
# (é proteção do próprio navegador, não do backend).
ORIGENS_PERMITIDAS = [
    "https://mindpulse-app.vercel.app",   # app em produção (nome original)
    "https://radar-empresa.vercel.app",   # app em produção (confirmado no navegador)
    "http://127.0.0.1:5500",              # Live Server, teste local
    "http://localhost:5500",
]


app = FastAPI(title="Radar Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGENS_PERMITIDAS,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "X-API-Key", "Content-Type"],
)


@app.middleware("http")
async def adicionar_cabecalhos_seguranca(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


@app.get("/")
def status():
    return {"status": "ok", "servico": "Radar Backend"}


# ================================================================
# Endpoints de sistema — protegidos por chave fixa (X-API-Key)
# ================================================================

@app.post("/executar/lembrete-diario", dependencies=[Depends(verificar_chave_sistema)])
def executar_lembrete_manual():
    return lembrete_diario.rodar()


@app.post("/executar/lembrete-segundo", dependencies=[Depends(verificar_chave_sistema)])
def executar_lembrete_segundo_manual():
    return lembrete_segundo.rodar()


@app.post("/executar/enviar-pesquisa", dependencies=[Depends(verificar_chave_sistema)])
def executar_enviar_pesquisa_manual():
    return enviar_pesquisa.rodar()


@app.post("/executar/encerrar-automatico", dependencies=[Depends(verificar_chave_sistema)])
def executar_encerrar_automatico_manual():
    return encerrar_automatico.rodar()


@app.post("/notificar-alerta-critico", dependencies=[Depends(verificar_chave_sistema)])
def rota_notificar_critico(payload: NotificarCriticoPayload):
    return notificar_critico.processar(payload.model_dump(mode="json"))


@app.post("/notificar-novo-lead", dependencies=[Depends(verificar_chave_sistema)])
def rota_notificar_lead(payload: NotificarLeadPayload):
    return notificar_lead.processar(payload.model_dump(mode="json"))


# ================================================================
# Endpoint chamado pelo RH logado — protegido por JWT do Supabase
# ================================================================

def _buscar_um(query):
    """
    Roda uma query .maybe_single() com segurança. Em algumas versões
    do supabase-py, .execute() devolve None direto quando não acha
    nenhuma linha, em vez de um objeto de resposta com .data=None —
    acessar .data nesse caso quebra com AttributeError. Essa função
    trata os dois comportamentos.
    """
    resposta = query.execute()
    return resposta.data if resposta else None


@app.post("/encerrar-pesquisa")
def rota_encerrar_pesquisa(payload: EncerrarPesquisaPayload, auth: dict = Depends(verificar_jwt_supabase)):
    dados = payload.model_dump(mode="json")

    ciclo = _buscar_um(supabase.table("ciclo").select("empresa_id").eq("id", dados["ciclo_id"]).maybe_single())
    if not ciclo:
        raise HTTPException(404, "Ciclo não encontrado.")

    verificar_rh_pertence_a_empresa(auth["sub"], ciclo["empresa_id"])

    return encerrar_pesquisa.processar(dados)


@app.post("/pesquisa/{pesquisa_id}/enviar")
def rota_enviar_pesquisa_agora(pesquisa_id: str, auth: dict = Depends(verificar_jwt_supabase)):
    pesquisa = _buscar_um(
        supabase.table("pesquisa").select("id, nome, ciclo_id, prazo_horas, status").eq("id", pesquisa_id).maybe_single()
    )
    if not pesquisa:
        raise HTTPException(404, "Pesquisa não encontrada.")
    if pesquisa["status"] != "agendada":
        raise HTTPException(400, "Essa pesquisa já foi enviada ou não está mais agendada.")

    ciclo = _buscar_um(supabase.table("ciclo").select("empresa_id").eq("id", pesquisa["ciclo_id"]).maybe_single())
    if not ciclo:
        raise HTTPException(404, "Ciclo não encontrado.")

    verificar_rh_pertence_a_empresa(auth["sub"], ciclo["empresa_id"])

    return enviar_pesquisa.processar_uma_pesquisa(pesquisa)


# ================================================================
# Rota de administração — só você, nunca RH de cliente
# ================================================================

@app.post("/admin/provisionar-empresa")
def rota_provisionar_empresa(payload: ProvisionarEmpresaPayload, _admin: dict = Depends(verificar_admin)):
    return admin.provisionar_empresa(
        empresa_nome=payload.empresa_nome,
        empresa_cnpj=payload.empresa_cnpj,
        rh_nome=payload.rh_nome,
        rh_email=payload.rh_email,
    )


@app.get("/admin/verificar")
def rota_verificar_admin(_admin: dict = Depends(verificar_admin)):
    """Só confirma se quem está logado é da equipe Radar — usado pela
    tela admin.html antes de mostrar o formulário de cadastro."""
    return {"autorizado": True}


@app.get("/admin/leads")
def rota_listar_leads(_admin: dict = Depends(verificar_admin)):
    """Mensagens recebidas pelo formulário de contato do site comercial.
    Passa pelo backend (service_role) porque a tabela 'lead' não tem
    política de leitura — só de escrita, de propósito (formulário
    público não deveria conseguir LER contato de outra pessoa)."""
    leads = supabase.table("lead").select("*").order("criado_em", desc=True).execute().data
    return {"leads": leads}

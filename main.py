from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from clients.auth import verificar_admin, verificar_chave_sistema, verificar_jwt_supabase, verificar_rh_pertence_a_empresa
from clients.supabase_client import supabase
from jobs import enviar_pesquisa, lembrete_diario, lembrete_segundo, encerrar_automatico
from routes import admin, encerrar_pesquisa, notificar_critico, notificar_lead, supabase_proxy
from schemas import AtualizarStatusLeadPayload, EncerrarPesquisaPayload, NotificarCriticoPayload, NotificarLeadPayload, ProvisionarEmpresaPayload, SalvarObservacaoLeadPayload

ORIGENS_PERMITIDAS = [
    "https://mindpulse-app.vercel.app",
    "https://radar-empresa.vercel.app",
    "http://127.0.0.1:5500",
    "http://localhost:5500",
]


app = FastAPI(title="Radar Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGENS_PERMITIDAS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "PUT"],
    allow_headers=["*"],
)

app.include_router(supabase_proxy.router)


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
def executar_encerrar_automatico_manual(background_tasks: BackgroundTasks):
    background_tasks.add_task(encerrar_automatico.rodar)
    return {"status": "processamento iniciado em segundo plano"}


@app.post("/notificar-alerta-critico", dependencies=[Depends(verificar_chave_sistema)])
def rota_notificar_critico(payload: NotificarCriticoPayload):
    return notificar_critico.processar(payload.model_dump(mode="json"))


@app.post("/notificar-novo-lead", dependencies=[Depends(verificar_chave_sistema)])
def rota_notificar_lead(payload: NotificarLeadPayload):
    return notificar_lead.processar(payload.model_dump(mode="json"))


def _buscar_um(query):
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
    return {"autorizado": True}


@app.get("/admin/leads")
def rota_listar_leads(_admin: dict = Depends(verificar_admin)):
    leads = supabase.table("lead").select("*").order("criado_em", desc=True).execute().data
    return {"leads": leads}


@app.patch("/admin/leads/{lead_id}")
def rota_atualizar_status_lead(lead_id: str, payload: AtualizarStatusLeadPayload, _admin: dict = Depends(verificar_admin)):
    return admin.atualizar_status_lead(lead_id, payload.campo, payload.marcar, _admin["email"])


@app.put("/admin/leads/{lead_id}/observacoes")
def rota_salvar_observacao_lead(lead_id: str, payload: SalvarObservacaoLeadPayload, _admin: dict = Depends(verificar_admin)):
    return admin.salvar_observacao_lead(lead_id, payload.observacoes)


@app.get("/admin/empresas")
def rota_listar_empresas(_admin: dict = Depends(verificar_admin)):
    return {"empresas": admin.listar_empresas()}


@app.get("/admin/empresas/{empresa_id}")
def rota_detalhar_empresa(empresa_id: str, _admin: dict = Depends(verificar_admin)):
    return admin.detalhar_empresa(empresa_id)

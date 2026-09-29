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
from datetime import datetime, timezone

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from clients.auth import verificar_admin, verificar_chave_sistema, verificar_jwt_supabase, verificar_rh_pertence_a_empresa
from clients.supabase_client import supabase
from config import BREVO_WEBHOOK_SECRET
from jobs import enviar_pesquisa, lembrete_diario, lembrete_segundo, encerrar_automatico
from routes import admin, encerrar_pesquisa, notificar_critico, notificar_lead, supabase_proxy
from schemas import AtualizarStatusLeadPayload, EncerrarPesquisaPayload, NotificarCriticoPayload, NotificarLeadPayload, ProvisionarEmpresaPayload, SalvarObservacaoLeadPayload
from workers import consumidor_convites

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
    allow_credentials=True,  # obrigatório pro cookie httpOnly viajar entre domínios (Vercel <-> Render)
    allow_methods=["GET", "POST", "PATCH", "DELETE", "PUT"],
    allow_headers=["*"],  # aceita qualquer cabeçalho pedido -- evita ficar descobrindo nome por nome
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
def executar_encerrar_automatico_manual(background_tasks: BackgroundTasks):
    # Chama o Gemini + PLN, pode levar bem mais que 30s com várias
    # pesquisas de uma vez -- alguns serviços de cron gratuito têm
    # tempo limite curto e não configurável (ex: cron-job.org, 30s
    # fixo). Responde rápido aqui, processa de verdade depois, em
    # segundo plano -- o cron não fica esperando o trabalho pesado.
    background_tasks.add_task(encerrar_automatico.rodar)
    return {"status": "processamento iniciado em segundo plano"}


@app.post("/executar/processar-fila-convites", dependencies=[Depends(verificar_chave_sistema)])
def executar_processar_fila_convites():
    # Consumidor da fila do RabbitMQ (ver workers/consumidor_convites.py).
    # Drena um lote e responde -- pensado pra ser chamado por um cron
    # externo a cada poucos minutos (mesmo esquema do cron-job.org que
    # já mantém o backend acordado), não pra ficar escutando pra sempre
    # (Render free não tem processo persistente de graça). Roda direto
    # aqui, sem BackgroundTasks: um lote de 50 mensagens é rápido, e
    # devolver o resultado (quantas enviadas/reencaminhadas/mortas) é
    # útil pra acompanhar no painel do cron-job.org.
    return consumidor_convites.processar_lote()


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
def rota_encerrar_pesquisa(
    payload: EncerrarPesquisaPayload,
    background_tasks: BackgroundTasks,
    auth: dict = Depends(verificar_jwt_supabase),
):
    dados = payload.model_dump(mode="json")

    # Checagens de autorização continuam síncronas (são rápidas) --
    # só o processamento pesado (indicadores, ML, chamada ao Gemini)
    # vai pra segundo plano. Antes essa rota travava a requisição até
    # tudo terminar (pode passar de 30s, às vezes bem mais); se o RH
    # trocasse de tela do app antes disso, a resposta de sucesso/erro
    # nunca aparecia pra ele -- e como o proxy na frente do Render
    # também pode cortar a conexão numa chamada tão longa, no fim
    # parecia que "não tinha acontecido nada". Mesmo padrão que já é
    # usado em /executar/encerrar-automatico.
    ciclo = _buscar_um(supabase.table("ciclo").select("empresa_id").eq("id", dados["ciclo_id"]).maybe_single())
    if not ciclo:
        raise HTTPException(404, "Ciclo não encontrado.")

    verificar_rh_pertence_a_empresa(auth["sub"], ciclo["empresa_id"])

    background_tasks.add_task(encerrar_pesquisa.processar, dados)
    return {"status": "processamento iniciado em segundo plano"}


@app.post("/pesquisa/{pesquisa_id}/enviar", status_code=202)
def rota_enviar_pesquisa_agora(pesquisa_id: str, auth: dict = Depends(verificar_jwt_supabase)):
    # 202 Accepted (Etapa 2.a/2.c do trabalho de mensageria): o corpo da
    # resposta já sai com o lote_id assim que as mensagens são publicadas
    # na fila -- ninguém espera nenhum e-mail terminar de ser enviado pra
    # receber essa resposta. O RH consulta o progresso depois em
    # GET /pesquisa/lote/{lote_id}/status.
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


@app.get("/pesquisa/lote/{lote_id}/status")
def rota_status_lote(lote_id: str, auth: dict = Depends(verificar_jwt_supabase)):
    """
    Consulta de progresso do lote (Etapa 2.c): o frontend chama isso
    periodicamente (a cada ~2s) depois do 202, até `concluido` virar
    true, em vez de ficar esperando uma única requisição travada.
    """
    itens = (
        supabase.table("envio_lote_item")
        .select("status, pesquisa_id")
        .eq("lote_id", lote_id)
        .execute()
        .data
    )
    if not itens:
        raise HTTPException(404, "Lote não encontrado.")

    pesquisa_id = itens[0]["pesquisa_id"]
    pesquisa = _buscar_um(supabase.table("pesquisa").select("ciclo_id").eq("id", pesquisa_id).maybe_single())
    if not pesquisa:
        raise HTTPException(404, "Pesquisa do lote não encontrada.")
    ciclo = _buscar_um(supabase.table("ciclo").select("empresa_id").eq("id", pesquisa["ciclo_id"]).maybe_single())
    if not ciclo:
        raise HTTPException(404, "Ciclo não encontrado.")
    verificar_rh_pertence_a_empresa(auth["sub"], ciclo["empresa_id"])

    contagem = {"pendente": 0, "enviado": 0, "falhou": 0, "entregue": 0, "devolvido": 0}
    for item in itens:
        contagem[item["status"]] = contagem.get(item["status"], 0) + 1

    return {
        "lote_id": lote_id,
        "total": len(itens),
        "contagem": contagem,
        # "concluido" olha só pra fila de envio (pendente == 0) -- não
        # espera confirmação de entrega/bounce do webhook, que pode
        # demorar minutos e não deveria travar a barra de progresso.
        "concluido": contagem["pendente"] == 0,
    }


@app.post("/webhooks/brevo/{chave}")
async def rota_webhook_brevo(chave: str, request: Request):
    """
    Confirmação de entrega ao destinatário (Etapa 2.c, item 3) -- a
    Brevo chama isso minutos depois do envio, informando se entregou ou
    se voltou (bounce). Correlaciona com a linha certa pela tag que
    mandamos junto no envio (ver clients/brevo_client.py e
    workers/consumidor_convites.py) -- é o envio_lote_item.id.

    Sem JWT nem X-API-Key (a Brevo não manda nenhum dos dois) -- a
    própria URL, com essa chave, é a proteção. Configurar a mesma
    string em BREVO_WEBHOOK_SECRET e no cadastro do webhook no painel
    da Brevo.
    """
    if not BREVO_WEBHOOK_SECRET or chave != BREVO_WEBHOOK_SECRET:
        raise HTTPException(401, "Chave de webhook inválida.")

    payload = await request.json()
    evento = payload.get("event")
    tags = payload.get("tags") or []
    if not tags:
        return {"status": "ignorado", "motivo": "sem tag de correlação"}

    envio_item_id = tags[0]

    if evento == "delivered":
        novo_status = "entregue"
    elif evento in ("hard_bounce", "soft_bounce", "blocked", "invalid_email"):
        novo_status = "devolvido"
    else:
        return {"status": "ignorado", "motivo": f"evento '{evento}' não tratado"}

    supabase.table("envio_lote_item").update(
        {"status": novo_status, "atualizado_em": datetime.now(timezone.utc).isoformat()}
    ).eq("id", envio_item_id).execute()

    return {"status": "ok"}


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


@app.patch("/admin/leads/{lead_id}")
def rota_atualizar_status_lead(lead_id: str, payload: AtualizarStatusLeadPayload, _admin: dict = Depends(verificar_admin)):
    """Marca (ou desmarca) um lead como visto ou respondido -- sempre
    grava quem fez isso e quando, usando o e-mail de quem está logado."""
    return admin.atualizar_status_lead(lead_id, payload.campo, payload.marcar, _admin["email"])


@app.put("/admin/leads/{lead_id}/observacoes")
def rota_salvar_observacao_lead(lead_id: str, payload: SalvarObservacaoLeadPayload, _admin: dict = Depends(verificar_admin)):
    """Anotação livre sobre o lead."""
    return admin.salvar_observacao_lead(lead_id, payload.observacoes)


@app.get("/admin/empresas")
def rota_listar_empresas(_admin: dict = Depends(verificar_admin)):
    """Visão operacional de todas as empresas -- funcionários, ciclos,
    status do ciclo mais recente. Nunca devolve score/indicador."""
    return {"empresas": admin.listar_empresas()}


@app.get("/admin/empresas/{empresa_id}")
def rota_detalhar_empresa(empresa_id: str, _admin: dict = Depends(verificar_admin)):
    """Linha do tempo de ciclos de 1 empresa -- status e taxa de
    resposta de cada um. Nunca devolve score/indicador."""
    return admin.detalhar_empresa(empresa_id)

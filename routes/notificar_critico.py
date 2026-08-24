"""
Equivalente ao workflow n8n 'Notificar Alerta Critico (v2 corrigido)' —
migração completa.

Continua sendo chamado pelo Supabase Database Webhook (evento
INSERT na tabela relatorio_ia) — só troca a URL de destino do
webhook pra apontar pra este backend em vez do n8n.
"""
from clients.supabase_client import supabase
from clients.brevo_client import enviar_email
from config import BASE_URL_FRONTEND


def processar(payload: dict) -> dict:
    record = payload.get("record", {})

    if record.get("prioridade") != "alta":
        return {"acao": "nenhuma", "motivo": "prioridade nao e alta"}

    ciclo_id = record["ciclo_id"]
    ciclo = supabase.table("ciclo").select("empresa_id").eq("id", ciclo_id).single().execute().data
    empresa_id = ciclo["empresa_id"]

    usuarios_rh = (
        supabase.table("usuario_rh")
        .select("nome, email")
        .eq("empresa_id", empresa_id)
        .eq("ativo", True)
        .execute()
        .data
    )

    supabase.table("alerta").insert({
        "ciclo_id": ciclo_id,
        "tipo": "comentario_critico",
        "descricao": f"A IA identificou prioridade ALTA na análise deste ciclo. "
                      f"Resumo: {record.get('resumo_executivo', '')}",
    }).execute()

    emails_enviados = 0
    for rh in usuarios_rh:
        enviar_email(
            destinatario_email=rh["email"],
            destinatario_nome=rh["nome"],
            assunto="⚠️ Alerta crítico identificado no último ciclo",
            corpo_html=f"""
                <p>Olá, {rh['nome']}!</p>
                <p>A análise do último ciclo de monitoramento identificou
                <strong>prioridade alta</strong> nos comentários ou indicadores coletados.</p>
                <p><strong>Resumo:</strong> {record.get('resumo_executivo', '')}</p>
                <p>Recomendamos revisar o painel de Alertas o quanto antes.</p>
                <p><a href="{BASE_URL_FRONTEND}/#/alertas">Abrir painel de alertas</a></p>
            """,
        )
        emails_enviados += 1

    return {"acao": "notificado", "usuarios_notificados": emails_enviados}

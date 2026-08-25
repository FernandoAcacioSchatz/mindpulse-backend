"""
Encerramento automático de pesquisas vencidas.

Roda todo dia às 10h (depois do lembrete às 8h e do envio às 9h) —
verifica pesquisas com status 'enviada' cujo prazo já passou
(enviada_em + prazo_horas), e encerra sozinho: reaproveita a MESMA
função que o botão manual usa (routes/encerrar_pesquisa.processar),
sem duplicar nenhuma lógica de cálculo.

Também pode ser disparado manualmente via POST /executar/encerrar-automatico,
útil pra testar sem esperar o horário.
"""
from datetime import datetime, timezone

from clients.supabase_client import supabase
from routes.encerrar_pesquisa import processar as processar_encerramento


def rodar() -> dict:
    agora = datetime.now(timezone.utc)

    pesquisas = (
        supabase.table("pesquisa")
        .select("id, nome, ciclo_id, enviada_em, prazo_horas")
        .eq("status", "enviada")
        .execute()
        .data
    )

    encerradas = []
    erros = []

    for pesquisa in pesquisas:
        if not pesquisa.get("enviada_em"):
            continue  # nunca foi enviada de verdade, não deveria estar 'enviada' -- pula por segurança

        enviada_em = datetime.fromisoformat(pesquisa["enviada_em"])
        prazo_horas = pesquisa.get("prazo_horas") or 72
        horas_passadas = (agora - enviada_em).total_seconds() / 3600

        if horas_passadas < prazo_horas:
            continue  # ainda dentro do prazo, não mexe

        try:
            resultado = processar_encerramento({"pesquisa_id": pesquisa["id"], "ciclo_id": pesquisa["ciclo_id"]})
            encerradas.append({"pesquisa_id": pesquisa["id"], "nome": pesquisa["nome"], **resultado})
        except Exception as e:
            erros.append({"pesquisa_id": pesquisa["id"], "erro": str(e)})
            print(f"[encerrar_automatico] Erro ao encerrar {pesquisa['id']}: {e}")

    resultado_geral = {
        "pesquisas_verificadas": len(pesquisas),
        "encerradas": len(encerradas),
        "erros": len(erros),
        "detalhes": encerradas,
    }
    print(f"[encerrar_automatico] {resultado_geral}")
    return resultado_geral

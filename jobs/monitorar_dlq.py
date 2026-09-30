"""
Monitoramento da fila morta (Etapa 5 do trabalho de Sistemas
Distribuídos -- boas práticas de integridade na troca de mensagens).

Antes deste job, uma mensagem que esgotava as tentativas e caía em
fila.enviar_convite.dlq ficava parada lá sem ninguém saber -- só se
alguém entrasse manualmente no painel do CloudAMQP e conferisse. Isso
é justamente o tipo de falha "silenciosa" que um sistema de mensageria
em produção não pode ter: convite de pesquisa que nunca chegou, sem
que ninguém do time percebesse.

O que este job faz: confere quantas mensagens estão paradas na DLQ
(consulta "passiva" -- só lê o contador, não consome nem apaga nada) e,
se houver pelo menos uma, dispara um e-mail de alerta pra equipe
(config.ADMIN_EMAILS) via Brevo, com a contagem e o nome da fila.

Chamado por HTTP (POST /executar/monitorar-dlq, protegido por
X-API-Key), no mesmo esquema de cron externo dos outros jobs
(cron-job.org) -- sugestão: a cada 10-15 minutos.

Simplificação deliberada (documentada, não escondida): o alerta dispara
TODA VEZ que o job roda e a DLQ não está vazia, sem "cooldown" -- ou
seja, enquanto ninguém tratar as mensagens mortas, a equipe recebe um
e-mail a cada execução do cron. Suficiente pro escopo do trabalho
(garante que a falha não passa despercebida); uma evolução natural
seria guardar em Supabase a hora do último alerta e só reavisar depois
de um intervalo maior, ou depois que a contagem mudar.

Autorização por papel (Etapa 3): usa RABBITMQ_URL_CONSUMIDOR -- a
mesma credencial restrita dos workers consumidores, que já tem
permissão de leitura em fila.* (inclui a DLQ). Não precisa de nenhuma
credencial nova.
"""
from clients.brevo_client import enviar_email
from clients.rabbitmq_client import FILA_DLQ, conectar_consumidor
from config import ADMIN_EMAILS


def _consultar_profundidade_dlq() -> int:
    """
    Passive declare: só CONSULTA a fila (não cria, não altera, não
    consome nenhuma mensagem) e devolve quantas mensagens estão
    paradas nela agora.
    """
    conexao = conectar_consumidor()
    try:
        canal = conexao.channel()
        resposta = canal.queue_declare(queue=FILA_DLQ, passive=True)
        return resposta.method.message_count
    finally:
        conexao.close()


def _montar_alerta(quantidade: int) -> tuple[str, str]:
    assunto = f"[Radar] {quantidade} convite(s) parado(s) na fila morta"
    corpo_html = f"""
        <p>A fila <code>{FILA_DLQ}</code> tem <strong>{quantidade}</strong>
        mensagem(ns) que esgotaram as tentativas de envio e precisam de
        investigação manual (e-mail inválido, Brevo rejeitando, etc.).</p>
        <p>Confira no painel do CloudAMQP (RabbitMQ Manager → Queues and
        Streams → {FILA_DLQ}) o conteúdo de cada mensagem antes de decidir
        reprocessar ou descartar.</p>
    """
    return assunto, corpo_html


def rodar() -> dict:
    quantidade = _consultar_profundidade_dlq()

    if quantidade == 0:
        resultado = {"mensagens_na_dlq": 0, "alerta_enviado": False}
        print(f"[monitorar_dlq] {resultado}")
        return resultado

    assunto, corpo_html = _montar_alerta(quantidade)
    destinatarios_notificados = []
    for email_admin in ADMIN_EMAILS:
        try:
            enviar_email(
                destinatario_email=email_admin,
                destinatario_nome="Equipe Radar",
                assunto=assunto,
                corpo_html=corpo_html,
            )
            destinatarios_notificados.append(email_admin)
        except Exception as e:
            print(f"[monitorar_dlq] Falha ao alertar {email_admin}: {e}")

    resultado = {
        "mensagens_na_dlq": quantidade,
        "alerta_enviado": bool(destinatarios_notificados),
        "notificados": destinatarios_notificados,
    }
    print(f"[monitorar_dlq] {resultado}")
    return resultado

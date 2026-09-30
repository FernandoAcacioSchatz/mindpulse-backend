"""
Versão "rodando continuamente" do consumidor de convites (Etapa 2.a do
trabalho: processo novo, separado do servidor principal, rodando pra
sempre). Feito pra rodar numa VM própria (Oracle Cloud Always Free),
nunca no Render -- o free tier de lá não sustenta processo contínuo.

Diferença pro workers/consumidor_convites.py (que continua existindo,
sem mexer): aquele lá faz "drena um lote e sai", chamado por HTTP por
um cron externo. Esse aqui usa canal.consume(), que bloqueia esperando
mensagem chegar -- o processo nunca termina sozinho. Se a conexão cair
(rede, restart do broker, etc.), reconecta sozinho e continua de onde
parou, sem precisar de nada externo chamando ele de novo.
"""
import json
import time
from datetime import datetime, timezone

from clients.brevo_client import enviar_email
from clients.rabbitmq_client import (
    FILA_DLQ,
    FILA_PRINCIPAL,
    MAX_TENTATIVAS,
    conectar,
    declarar_topologia,
    tentativas_anteriores,
)
from clients.supabase_client import supabase
from config import BASE_URL_FRONTEND

ESPERA_APOS_QUEDA_S = 5


def _montar_email(msg: dict) -> tuple[str, str]:
    link = f"{BASE_URL_FRONTEND}/pulse/{msg['token_codigo']}"
    corpo_html = f"""
        <p>Olá, {msg['funcionario_nome']}!</p>
        <p>Você foi convidado a participar de uma pesquisa rápida e anônima sobre o
        ambiente de trabalho. Leva menos de 5 minutos.</p>
        <p><a href="{link}">Responder pesquisa</a></p>
        <p>Este link é pessoal e expira em {msg['prazo_horas']} horas.</p>
    """
    return "Pesquisa de Clima e Bem-estar — sua participação é importante", corpo_html


def _ja_enviado(token_id: str) -> bool:
    resposta = (
        supabase.table("token_resposta")
        .select("convite_enviado_em")
        .eq("id", token_id)
        .maybe_single()
        .execute()
    )
    linha = resposta.data if resposta else None
    return bool(linha and linha.get("convite_enviado_em"))


def _marcar_enviado(token_id: str) -> None:
    supabase.table("token_resposta").update(
        {"convite_enviado_em": datetime.now(timezone.utc).isoformat()}
    ).eq("id", token_id).execute()


def _atualizar_status_item(envio_item_id: str | None, status: str, mensagem_id_brevo: str = None, erro: str = None) -> None:
    if not envio_item_id:
        return
    dados = {"status": status, "atualizado_em": datetime.now(timezone.utc).isoformat()}
    if mensagem_id_brevo is not None:
        dados["mensagem_id_brevo"] = mensagem_id_brevo
    if erro is not None:
        dados["erro"] = erro[:500]
    supabase.table("envio_lote_item").update(dados).eq("id", envio_item_id).execute()


def _processar_mensagem(canal, metodo, propriedades, corpo: bytes) -> None:
    msg = json.loads(corpo)
    token_id = msg.get("token_id")
    envio_item_id = msg.get("envio_item_id")

    if token_id and _ja_enviado(token_id):
        canal.basic_ack(delivery_tag=metodo.delivery_tag)
        print(f"[consumidor_continuo] {msg.get('funcionario_email')} já tinha sido enviado -- ignorando duplicata.")
        return

    try:
        assunto, corpo_html = _montar_email(msg)
        resposta_brevo = enviar_email(
            destinatario_email=msg["funcionario_email"],
            destinatario_nome=msg["funcionario_nome"],
            assunto=assunto,
            corpo_html=corpo_html,
            tags=[envio_item_id] if envio_item_id else None,
        )
        if token_id:
            _marcar_enviado(token_id)
        _atualizar_status_item(envio_item_id, "enviado", mensagem_id_brevo=resposta_brevo.get("messageId"))
        canal.basic_ack(delivery_tag=metodo.delivery_tag)
        print(f"[consumidor_continuo] {msg.get('funcionario_email')} -> enviado.")
    except Exception as e:
        tentativa_atual = tentativas_anteriores(propriedades) + 1
        if tentativa_atual >= MAX_TENTATIVAS:
            canal.basic_publish(exchange="", routing_key=FILA_DLQ, body=corpo, properties=propriedades)
            canal.basic_ack(delivery_tag=metodo.delivery_tag)
            _atualizar_status_item(envio_item_id, "falhou", erro=str(e))
            print(f"[consumidor_continuo] {msg.get('funcionario_email')} -> DLQ após {tentativa_atual} tentativas: {e}")
        else:
            canal.basic_nack(delivery_tag=metodo.delivery_tag, requeue=False)
            print(f"[consumidor_continuo] {msg.get('funcionario_email')} -> retry (tentativa {tentativa_atual}): {e}")


def rodar_para_sempre() -> None:
    while True:
        conexao = None
        try:
            conexao = conectar()
            canal = conexao.channel()
            declarar_topologia(canal)
            canal.basic_qos(prefetch_count=10)
            print("[consumidor_continuo] Conectado, esperando mensagens...")

            for metodo, propriedades, corpo in canal.consume(FILA_PRINCIPAL, auto_ack=False):
                _processar_mensagem(canal, metodo, propriedades, corpo)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"[consumidor_continuo] Conexão caiu ou erro inesperado, reconectando em {ESPERA_APOS_QUEDA_S}s: {e}")
            time.sleep(ESPERA_APOS_QUEDA_S)
        finally:
            try:
                if conexao is not None and conexao.is_open:
                    conexao.close()
            except Exception:
                pass


if __name__ == "__main__":
    rodar_para_sempre()

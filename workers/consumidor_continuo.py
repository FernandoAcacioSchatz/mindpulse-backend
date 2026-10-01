import json
import time
from datetime import datetime, timezone

from clients.brevo_client import enviar_email
from clients.rabbitmq_client import (
    FILA_DLQ,
    FILA_PRINCIPAL,
    FILA_PRIORITARIA,
    MAX_TENTATIVAS,
    conectar_consumidor,
    tentativas_anteriores,
)
from clients.supabase_client import supabase
from config import BASE_URL_FRONTEND

ESPERA_APOS_QUEDA_S = 5
ESPERA_SEM_MENSAGEM_S = 1

CAMPO_ENVIADO_POR_TIPO = {
    "convite": "convite_enviado_em",
    "lembrete_1": "lembrete1_enviado_em",
    "lembrete_2": "lembrete2_enviado_em",
}


def _montar_email_convite(msg: dict) -> tuple[str, str]:
    link = f"{BASE_URL_FRONTEND}/pulse/{msg['token_codigo']}"
    corpo_html = f"""
        <p>Olá, {msg['funcionario_nome']}!</p>
        <p>Você foi convidado a participar de uma pesquisa rápida e anônima sobre o
        ambiente de trabalho. Leva menos de 5 minutos.</p>
        <p><a href="{link}">Responder pesquisa</a></p>
        <p>Este link é pessoal e expira em {msg['prazo_horas']} horas.</p>
    """
    return "Pesquisa de Clima e Bem-estar — sua participação é importante", corpo_html


def _montar_email_lembrete(msg: dict, numero: int) -> tuple[str, str]:
    agora = datetime.now(timezone.utc)
    expira = datetime.fromisoformat(msg["expira_em"])
    horas_restantes = max(0, round((expira - agora).total_seconds() / 3600))
    link = f"{BASE_URL_FRONTEND}/pulse/{msg['token_codigo']}"

    if numero == 1:
        assunto = "Lembrete: sua pesquisa ainda está aberta"
        texto = "Notamos que você ainda não respondeu à pesquisa de clima e bem-estar."
    else:
        assunto = "Último lembrete: sua pesquisa fecha em breve"
        texto = "Esse é o último lembrete -- sua resposta ainda não chegou."

    corpo_html = f"""
        <p>Olá, {msg['funcionario_nome']}!</p>
        <p>{texto}
        Faltam aproximadamente {horas_restantes} horas para o link expirar.</p>
        <p><a href="{link}">Responder agora</a></p>
        <p>Leva menos de 5 minutos e sua resposta é anônima.</p>
    """
    return assunto, corpo_html


def _ja_enviado(token_id: str, tipo: str) -> bool:
    campo = CAMPO_ENVIADO_POR_TIPO.get(tipo, "convite_enviado_em")
    resposta = (
        supabase.table("token_resposta")
        .select(campo)
        .eq("id", token_id)
        .maybe_single()
        .execute()
    )
    linha = resposta.data if resposta else None
    return bool(linha and linha.get(campo))


def _marcar_enviado(token_id: str, tipo: str) -> None:
    campo = CAMPO_ENVIADO_POR_TIPO.get(tipo, "convite_enviado_em")
    supabase.table("token_resposta").update(
        {campo: datetime.now(timezone.utc).isoformat()}
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


def _processar_mensagem(canal, metodo, propriedades, corpo: bytes, fila_de_origem: str) -> None:
    msg = json.loads(corpo)
    tipo = msg.get("tipo", "convite")
    token_id = msg.get("token_id")
    envio_item_id = msg.get("envio_item_id")

    if token_id and _ja_enviado(token_id, tipo):
        canal.basic_ack(delivery_tag=metodo.delivery_tag)
        print(f"[consumidor_continuo] {msg.get('funcionario_email')} ({tipo}) já tinha sido enviado -- ignorando duplicata.")
        return

    try:
        if tipo == "convite":
            assunto, corpo_html = _montar_email_convite(msg)
        elif tipo == "lembrete_1":
            assunto, corpo_html = _montar_email_lembrete(msg, numero=1)
        elif tipo == "lembrete_2":
            assunto, corpo_html = _montar_email_lembrete(msg, numero=2)
        else:
            raise ValueError(f"Tipo de mensagem desconhecido: {tipo!r}")

        resposta_brevo = enviar_email(
            destinatario_email=msg["funcionario_email"],
            destinatario_nome=msg["funcionario_nome"],
            assunto=assunto,
            corpo_html=corpo_html,
            tags=[envio_item_id] if envio_item_id else None,
        )
        if token_id:
            _marcar_enviado(token_id, tipo)
        if tipo == "convite":
            _atualizar_status_item(envio_item_id, "enviado", mensagem_id_brevo=resposta_brevo.get("messageId"))

        canal.basic_ack(delivery_tag=metodo.delivery_tag)
        print(f"[consumidor_continuo] {msg.get('funcionario_email')} ({tipo}) -> enviado.")
    except Exception as e:
        tentativa_atual = tentativas_anteriores(propriedades, fila_de_origem) + 1
        if tentativa_atual >= MAX_TENTATIVAS:
            canal.basic_publish(exchange="", routing_key=FILA_DLQ, body=corpo, properties=propriedades)
            canal.basic_ack(delivery_tag=metodo.delivery_tag)
            if tipo == "convite":
                _atualizar_status_item(envio_item_id, "falhou", erro=str(e))
            print(f"[consumidor_continuo] {msg.get('funcionario_email')} ({tipo}) -> DLQ após {tentativa_atual} tentativas: {e}")
        else:
            canal.basic_nack(delivery_tag=metodo.delivery_tag, requeue=False)
            print(f"[consumidor_continuo] {msg.get('funcionario_email')} ({tipo}) -> retry (tentativa {tentativa_atual}): {e}")


def rodar_para_sempre() -> None:
    while True:
        conexao = None
        try:
            conexao = conectar_consumidor()
            canal = conexao.channel()
            canal.basic_qos(prefetch_count=10)
            print("[consumidor_continuo] Conectado, esperando mensagens...")

            while True:
                metodo, propriedades, corpo = canal.basic_get(queue=FILA_PRIORITARIA, auto_ack=False)
                fila_de_origem = FILA_PRIORITARIA

                if metodo is None:
                    metodo, propriedades, corpo = canal.basic_get(queue=FILA_PRINCIPAL, auto_ack=False)
                    fila_de_origem = FILA_PRINCIPAL

                if metodo is None:
                    conexao.sleep(ESPERA_SEM_MENSAGEM_S)
                    continue

                _processar_mensagem(canal, metodo, propriedades, corpo, fila_de_origem)
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

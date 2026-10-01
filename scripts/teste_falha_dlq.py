import json
import time

import pika

from clients.rabbitmq_client import EXCHANGE, ROUTING_KEY_NORMAL, conectar_publicador

MAX_TENTATIVAS = 3
ESPERA_ENTRE_TENTATIVAS_S = 1.0


def publicar_mensagem_quebrada() -> None:
    mensagem = {
        "tipo": "convite",
        "teste_dlq": True,
    }
    corpo = json.dumps(mensagem).encode("utf-8")

    publicado = False
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        print(f"[teste_falha_dlq] Conectando como publicador (tentativa {tentativa}/{MAX_TENTATIVAS})...")
        conexao = conectar_publicador()
        try:
            canal = conexao.channel()
            canal.confirm_delivery()
            canal.basic_publish(
                exchange=EXCHANGE,
                routing_key=ROUTING_KEY_NORMAL,
                body=corpo,
                properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
                mandatory=True,
            )
            publicado = True
        except (pika.exceptions.UnroutableError, pika.exceptions.NackError) as e:
            print(f"[teste_falha_dlq] Broker recusou a mensagem (tentativa {tentativa}/{MAX_TENTATIVAS}): {e}")
            publicado = False
        except Exception as e:
            print(f"[teste_falha_dlq] Erro ao publicar (tentativa {tentativa}/{MAX_TENTATIVAS}): {e}")
            publicado = False
        finally:
            conexao.close()

        if publicado:
            break

        if tentativa < MAX_TENTATIVAS:
            print(
                f"[teste_falha_dlq] Falha real ao publicar -- "
                f"tentando de novo em {ESPERA_ENTRE_TENTATIVAS_S}s..."
            )
            time.sleep(ESPERA_ENTRE_TENTATIVAS_S)

    if not publicado:
        print(
            f"[teste_falha_dlq] Desisti depois de {MAX_TENTATIVAS} tentativas -- "
            "dessa vez é uma falha de verdade (veja o erro de cada tentativa "
            "acima): conexão caindo ou o broker recusando a mensagem. Confira "
            "RABBITMQ_URL/RABBITMQ_URL_PUBLISHER e se o serviço no Render está "
            "no ar antes de rodar de novo."
        )
        return

    print(f"[teste_falha_dlq] Mensagem de teste publicada: {mensagem}")
    print(
        "[teste_falha_dlq] Agora acompanhe os logs do consumidor no Render "
        "(o backend só roda lá, a thread contínua é iniciada por main.py) e o "
        "painel do CloudAMQP (fila.enviar_convite -> fila.enviar_convite.retry "
        "-> de volta -> 3x -> fila.enviar_convite.dlq). Deve levar entre ~70 e "
        "~100 segundos se o consumidor contínuo estiver rodando."
    )


if __name__ == "__main__":
    publicar_mensagem_quebrada()

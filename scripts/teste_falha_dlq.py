"""
Script de teste (rodar manualmente) -- demonstra AO VIVO o caminho de
falha completo: publica de propósito 1 mensagem sem os campos
obrigatórios direto na fila principal e deixa o consumidor de verdade
processá-la até ela cair na DLQ (Etapa 4 do trabalho: "caso de uso
representativo... com entradas, processamento e saídas esperadas").

Entrada: uma mensagem JSON válida (chega na fila normalmente -- o
publicador não valida o conteúdo, só publica) mas incompleta: só tem
"tipo": "convite", sem funcionario_nome/funcionario_email/token_codigo/
prazo_horas.

Processamento esperado, TODO ele feito pelo consumidor que já está
rodando de verdade (workers/consumidor_continuo.py, ou o chamado via
POST /executar/processar-fila-convites -- não precisa rodar nada além
deste script):
    1ª entrega -> _montar_email_convite tenta ler msg["token_codigo"],
                  estoura KeyError -> consumidor NÃO dá ack -> nack ->
                  dead-letter automático manda pra fila.enviar_convite.retry
    (espera TTL_RETRY_MS = 30s)
    2ª entrega -> mesmo KeyError -> retry de novo
    (espera mais 30s)
    3ª entrega -> mesmo KeyError -> x-death já mostra 3 rejeições dessa
                  fila -> consumidor publica manualmente na DLQ e SÓ AÍ
                  dá ack (mensagem sai da fila principal de vez)

Saída esperada: fila.enviar_convite.dlq com +1 mensagem, corpo igual
ao publicado aqui, e o header x-death com o histórico das 3 rejeições
(visível no painel do CloudAMQP, aba da fila -> "Get Message(s)").

Tempo total esperado: ~70-100s entre rodar este script e a mensagem
aparecer na DLQ, DESDE QUE exista um consumidor rodando continuamente
(workers/consumidor_continuo.py) ou sendo chamado por cron com
intervalo menor que 30s. Se o único consumidor em uso for o
"drena e sai" via cron (POST /executar/processar-fila-convites) com
intervalo maior que isso, cada chamada avança uma tentativa -- pode
levar até N execuções do cron pra fechar o ciclo, não ~100s corridos.

Autorização por papel (Etapa 3): publica com RABBITMQ_URL_PUBLISHER --
a MESMA credencial restrita usada em produção por
clients/rabbitmq_client.py::publicar_mensagens. Não precisa de
nenhuma credencial especial pra rodar este teste -- prova que o
publicador consegue colocar uma mensagem na fila (é o trabalho dele),
mesmo essa mensagem sendo inválida; validar o conteúdo é
responsabilidade do consumidor, não do transporte.

Como rodar (da raiz do projeto):
    python -m scripts.teste_falha_dlq
"""
import json

import pika

from clients.rabbitmq_client import EXCHANGE, ROUTING_KEY_NORMAL, conectar_publicador


def publicar_mensagem_quebrada() -> None:
    mensagem = {
        "tipo": "convite",
        "teste_dlq": True,
        # De propósito SEM funcionario_nome / funcionario_email /
        # token_codigo / prazo_horas -- qualquer consumidor real que
        # tentar montar o e-mail a partir disso estoura KeyError.
    }
    corpo = json.dumps(mensagem).encode("utf-8")

    print("[teste_falha_dlq] Conectando como publicador (RABBITMQ_URL_PUBLISHER)...")
    conexao = conectar_publicador()
    try:
        canal = conexao.channel()
        canal.confirm_delivery()
        publicado = canal.basic_publish(
            exchange=EXCHANGE,
            routing_key=ROUTING_KEY_NORMAL,
            body=corpo,
            properties=pika.BasicProperties(content_type="application/json", delivery_mode=2),
            mandatory=True,
        )
    finally:
        conexao.close()

    if not publicado:
        print("[teste_falha_dlq] O broker NÃO confirmou o recebimento -- tente rodar de novo.")
        return

    print(f"[teste_falha_dlq] Mensagem de teste publicada: {mensagem}")
    print(
        "[teste_falha_dlq] Agora acompanhe os logs do consumidor (Render/Railway ou "
        "journalctl -u radar-consumidor -f na VM) e o painel do CloudAMQP "
        "(fila.enviar_convite -> fila.enviar_convite.retry -> de volta -> "
        "3x -> fila.enviar_convite.dlq). Deve levar entre ~70 e ~100 segundos "
        "se o consumidor contínuo estiver rodando."
    )


if __name__ == "__main__":
    publicar_mensagem_quebrada()

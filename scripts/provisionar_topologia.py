"""
Script de provisionamento (rodar manualmente) -- cria/confirma a
topologia inteira do RabbitMQ: exchange, filas, bindings, retry e DLQ
(ver clients/rabbitmq_client.py::declarar_topologia pro desenho
completo).

Etapa 3 do trabalho de Sistemas Distribuídos (autorização): este é o
ÚNICO lugar do projeto que usa (ou deveria usar) a credencial admin
(RABBITMQ_URL, acesso total ao vhost). Todo o resto -- jobs que
publicam, workers que consomem, o monitor da DLQ -- já foi escrito pra
usar credenciais de papel restrito (RABBITMQ_URL_PUBLISHER /
RABBITMQ_URL_CONSUMIDOR), mas essas ainda NÃO existem de verdade hoje
(o plano gratuito da CloudAMQP não permite criar usuário novo -- ver
RABBITMQ_AUTORIZACAO.md), então na prática tudo roda com a mesma
credencial admin por enquanto. Mesmo assim, rodar este script continua
sendo a única situação em que essa credencial deveria ser usada
manualmente -- nunca dentro de um processo que fica no ar.

Quando rodar:
- Na primeira vez que o projeto for provisionado num vhost novo.
- Sempre que um argumento de alguma fila mudar (TTL, dead-letter,
  routing key) -- nesse caso, apague a fila manualmente no painel do
  CloudAMQP ANTES de rodar de novo (RabbitMQ recusa redeclarar uma fila
  existente com argumentos diferentes -- erro PRECONDITION_FAILED).

Como rodar (da raiz do projeto, com o .env de admin configurado):
    python -m scripts.provisionar_topologia
"""
from clients.rabbitmq_client import (
    EXCHANGE,
    FILA_DLQ,
    FILA_PRINCIPAL,
    FILA_PRIORITARIA,
    FILA_RETRY,
    FILA_RETRY_PRIORITARIA,
    conectar_admin,
    declarar_topologia,
)


def provisionar() -> None:
    print("[provisionar_topologia] Conectando com a credencial ADMIN (RABBITMQ_URL)...")
    conexao = conectar_admin()
    try:
        canal = conexao.channel()
        declarar_topologia(canal)
        print("[provisionar_topologia] Topologia OK:")
        print(f"  exchange           : {EXCHANGE}")
        print(f"  fila principal     : {FILA_PRINCIPAL}")
        print(f"  fila retry         : {FILA_RETRY}")
        print(f"  fila prioritaria   : {FILA_PRIORITARIA}")
        print(f"  fila retry priorit.: {FILA_RETRY_PRIORITARIA}")
        print(f"  fila DLQ           : {FILA_DLQ}")
        print(
            "[provisionar_topologia] Pronto. Enquanto radar_publisher/radar_consumidor "
            "não existirem de verdade (ver RABBITMQ_AUTORIZACAO.md), não precisa rodar "
            "mais nada aqui -- pode seguir pro deploy e pros testes de falha/monitoramento."
        )
    finally:
        conexao.close()


if __name__ == "__main__":
    provisionar()

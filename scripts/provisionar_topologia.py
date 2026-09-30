"""
Script de provisionamento (rodar manualmente) -- cria/confirma a
topologia inteira do RabbitMQ: exchange, filas, bindings, retry e DLQ
(ver clients/rabbitmq_client.py::declarar_topologia pro desenho
completo).

Etapa 3 do trabalho de Sistemas Distribuídos (autorização): este é o
ÚNICO lugar do projeto que ainda usa a credencial admin (RABBITMQ_URL,
acesso total ao vhost). Todo o resto -- jobs que publicam, workers que
consomem, o monitor da DLQ -- usa credenciais novas, muito mais
restritas (RABBITMQ_URL_PUBLISHER / RABBITMQ_URL_CONSUMIDOR, ver
config.py e RABBITMQ_AUTORIZACAO.md). Rodar este script é a ÚNICA
situação em que a credencial admin deveria ser usada -- nunca num
processo que fica no ar.

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
            "[provisionar_topologia] Pronto. Confira no painel do CloudAMQP que os "
            "usuários radar_publisher e radar_consumidor têm SÓ as permissões do "
            "RABBITMQ_AUTORIZACAO.md -- eles não precisam (e não devem) conseguir "
            "rodar este script."
        )
    finally:
        conexao.close()


if __name__ == "__main__":
    provisionar()

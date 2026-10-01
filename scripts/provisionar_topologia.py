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

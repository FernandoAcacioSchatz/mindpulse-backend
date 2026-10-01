# Mensageria com RabbitMQ — Autorização, Teste de Falha (DLQ) e Monitoramento

**Disciplina:** Sistemas Distribuídos — FURB — Prof. Gabriel Castellani
**Trabalho:** Mensageria (RabbitMQ) aplicada ao Radar
**Autor:** Fernando Acácio Schatz, Yuri Oliveira di Golfeto, Bruno 
**Etapas cobertas por este documento:** 3 (Autorização), 4 (Exemplo de uso — caminho de falha) e 5 (Boas práticas — monitoramento)
**Data:** 30/09/2026

---

## 0. Contexto (recapitulando as Etapas 1 e 2, já entregues)

As Etapas 1 e 2 definiram o cenário e a arquitetura usados neste trabalho, aplicados ao envio de convites de pesquisa do **Radar** (plataforma de monitoramento de risco psicossocial e conformidade com a NR-1):

- **Cenário**: quando o RH de uma empresa-cliente dispara um ciclo de pesquisa, o Radar precisa enviar um e-mail de convite para centenas de funcionários de uma vez. Fazer isso de forma síncrona (esperar cada e-mail ser enviado antes de responder a requisição HTTP) não escala e trava a aplicação. A solução adotada foi mensageria assíncrona.
- **Arquitetura**: um broker RabbitMQ hospedado no CloudAMQP, com uma exchange **direta** (`radar.eventos`) e duas rotas por routing key:
  - `email.normal` → envio inicial do convite → `fila.enviar_convite`
  - `email.prioritario` → lembretes próximos do prazo → `fila.enviar_convite.prioritaria`

  Cada fila principal tem sua própria fila de retry (TTL de 30s + dead-letter automático de volta pra fila principal). A confirmação da mensagem (**ack manual**) só acontece depois que o provedor de e-mail (Brevo) confirma o envio de verdade — se falhar, a mensagem nunca é confirmada, e a própria fila cuida do reenvio. O sistema também confere **idempotência** (já existe token para aquele funcionário?) antes de enfileirar, para nunca duplicar o mesmo convite.

As Etapas 3, 4 e 5 abaixo **não alteram nada dessa arquitetura** — elas completam o que já existia com segurança, tratamento formal de falha definitiva e observabilidade.

---

## 1. Etapa 3 — Autorização (separação de papel produtor/consumidor)

**Lacuna original**: uma única credencial de acesso total ao vhost (configure + write + read em tudo) era usada por todo mundo — quem publica convite, quem consome e processa, e quem cria a topologia. Não existia nenhuma separação de permissão por papel.

**O que foi implementado** (princípio do menor privilégio, na camada de aplicação):

- `clients/rabbitmq_client.py` agora expõe 3 funções de conexão distintas: `conectar_admin()`, `conectar_publicador()` e `conectar_consumidor()`.
- A criação da topologia (exchange, filas, bindings — que exige a permissão `configure`) foi isolada em `scripts/provisionar_topologia.py`, rodado manualmente, uma única vez. **Nenhum processo em execução contínua** (jobs que publicam, workers que consomem) usa mais permissão `configure` em nada — só utilizam os recursos que já existem.
- `config.py` já lê 3 variáveis de ambiente distintas (`RABBITMQ_URL`, `RABBITMQ_URL_PUBLISHER`, `RABBITMQ_URL_CONSUMIDOR`), cada uma pensada para um usuário RabbitMQ de papel restrito.

**Matriz de permissão alvo** (baseada na documentação oficial do RabbitMQ sobre controle de acesso — [rabbitmq.com/docs/access-control](https://www.rabbitmq.com/docs/access-control)):

| Usuário | Configure | Write | Read |
|---|---|---|---|
| `radar_publisher` | *(vazio)* | `^radar\.eventos$` | *(vazio)* |
| `radar_consumidor` | `^fila\..*$` | `^amq\.default$` | `^fila\..*$` |

(`amq.default` é o nome interno que o RabbitMQ usa pra representar a exchange padrão/sem nome, usada pelo consumidor para rotear manualmente uma mensagem até a DLQ.)

**Limitação de infraestrutura descoberta**: ao tentar criar os usuários `radar_publisher` e `radar_consumidor` de verdade no painel do CloudAMQP, constatamos que o plano gratuito usado neste projeto (**Little Lemur**, compartilhado) não permite gerenciar usuários, vhosts ou permissões — essa função só existe nos planos pagos ("dedicados"):

> "It is only possible to manage users, virtual hosts and permissions on dedicated plans. A dedicated plan is Sassy Squirrel or any plan larger than Sassy Squirrel." — [CloudAMQP FAQ](https://www.cloudamqp.com/docs/faq.html)

Por isso, hoje as 3 variáveis de ambiente apontam para a mesma credencial única — mas a separação de responsabilidades já está pronta no código. No dia em que as credenciais novas existirem (upgrade de plano pago, ou self-host do broker), a migração é só preencher as 2 variáveis de ambiente — **nenhuma linha de código muda**.

---

## 2. Etapa 4 — Exemplo de uso: caminho de falha ao vivo (DLQ)

**Objetivo**: demonstrar, com um caso real rodando, o que acontece quando uma mensagem não pode ser processada de jeito nenhum — da entrada até a saída.

**Script de teste**: `scripts/teste_falha_dlq.py` publica, de propósito, uma mensagem incompleta (`{"tipo": "convite", "teste_dlq": true}`, sem os campos `funcionario_nome`/`funcionario_email`/`token_codigo`/`prazo_horas`) direto na fila principal, e deixa o consumidor real processá-la.

**Entrada → Processamento → Saída observados**:

1. **Entrada**: mensagem JSON incompleta publicada em `fila.enviar_convite` (routing key `email.normal`).
2. **Processamento**: o consumidor tenta montar o e-mail, não encontra os campos obrigatórios, estoura exceção e dá `nack`. O dead-letter-exchange da própria fila move a mensagem automaticamente para `fila.enviar_convite.retry`, onde ela espera 30 segundos (TTL) antes de voltar. Isso se repete — o RabbitMQ registra cada passagem no header nativo `x-death`, sem precisar de nenhum contador manual no código.
3. Na 3ª tentativa de entrega (confirmada pelo `x-death`), o consumidor publica manualmente o corpo original — preservando o histórico de `x-death` — em `fila.enviar_convite.dlq`, e só então confirma a saída da fila principal.
4. **Saída**: mensagem residindo na fila morta, auditável pelo painel de administração.

**Evidência capturada** (painel do CloudAMQP, `fila.enviar_convite.dlq` → "Get Message(s)"):

```
Routing Key: fila.enviar_convite.dlq
Headers:
  x-death:
    - count: 2, queue: fila.enviar_convite.retry, reason: expired
    - count: 2, queue: fila.enviar_convite,       reason: rejected, routing-keys: email.normal
  x-first-death-reason: rejected   (queue: fila.enviar_convite, exchange: radar.eventos)
  x-last-death-reason:  expired    (queue: fila.enviar_convite.retry)
Payload: {"tipo": "convite", "teste_dlq": true}
```

Essas duas contagens de `2` representam as 2 rejeições anteriores à mensagem que finalmente foi roteada manualmente (a 3ª tentativa de entrega é justamente quando `MAX_TENTATIVAS = 3` é atingido e o consumidor para de deixar o ciclo automático se repetir). No momento da captura, a fila morta tinha **9 mensagens** acumuladas de execuções repetidas do teste — todas com o mesmo payload e o mesmo padrão de `x-death`, reforçando que o comportamento é determinístico e reproduzível, não um acidente isolado.

**Tempo observado**: compatível com o esperado (~70–100s por ciclo completo), já que o `workers/consumidor_continuo.py` roda como thread contínua dentro do próprio serviço no Render.

---

## 3. Etapa 5 — Boas práticas: monitoramento e alerta da fila morta

**Objetivo**: evitar que uma mensagem presa na DLQ passe despercebida — a falha "silenciosa" que um sistema de mensageria em produção não pode ter.

**Implementação**: `jobs/monitorar_dlq.py` faz uma consulta **passiva** (`queue_declare(passive=True)`) na `fila.enviar_convite.dlq` — só lê o contador de mensagens, não consome nem altera nada — usando a credencial de papel restrito do consumidor (não precisa de nenhuma credencial nova). Se houver pelo menos 1 mensagem, dispara um e-mail de alerta via Brevo para cada endereço configurado em `ADMIN_EMAILS`. Exposto como `POST /executar/monitorar-dlq` (protegido por `X-API-Key`), pensado para ser chamado periodicamente por um agendador externo (cron-job.org), no mesmo esquema dos outros jobs do projeto.

**Execução real e resultado observado**:

```
POST /executar/monitorar-dlq
→ {"mensagens_na_dlq": 9, "alerta_enviado": true,
   "notificados": ["fernandoacacioschatz@gmail.com", "faschatz@furb.br"]}
```

O e-mail de alerta ("[Radar] 9 convite(s) parado(s) na fila morta") chegou de fato às duas caixas de entrada configuradas, confirmando o ciclo completo: detecção → alerta → possibilidade de intervenção manual (reprocessar ou descartar).

---

## 4. Achado adicional durante os testes: bug real de verificação de confirmação

Rodar o teste de falha repetidamente (Etapa 4) expôs um bug real no projeto, fora do escopo original das 3 lacunas, mas que vale registrar como parte do processo:

O script (e a função de produção `clients/rabbitmq_client.py::publicar_mensagens()`, usada pelo envio real de convites) guardava o retorno de `canal.basic_publish(...)` numa variável e checava `if publicado:`. Pela documentação oficial do `pika` ([pika.readthedocs.io](https://pika.readthedocs.io/en/stable/examples/blocking_delivery_confirmations.html)), com `confirm_delivery()` ativo esse método **nunca** devolve `True`/`False` — sempre devolve `None`. Quem indica sucesso é a **ausência de exceção**, não o valor de retorno. Resultado: toda publicação era tratada como "não confirmada", mesmo as que tinham funcionado — o script reconectava e tentava de novo (podendo publicar a mesma mensagem mais de uma vez), e a função de produção devolvia `False` para quem chamou mesmo com a mensagem já enfileirada. É provável que isso explique um comportamento intermitente observado antes no projeto (tokens de convite ficando "pendentes" mesmo com o e-mail já na fila).

Corrigido nos dois arquivos: a lógica agora marca sucesso quando `basic_publish` não lança exceção, e trata `pika.exceptions.UnroutableError`/`NackError` como as únicas falhas reais. Validado após a correção: a publicação de teste foi confirmada já na 1ª tentativa, sem nenhum retry.

---

## 5. Arquivos entregues

- `config.py` — 3 variáveis de ambiente de credencial, com fallback documentado.
- `clients/rabbitmq_client.py` — conexões por papel; topologia isolada; bug de confirmação corrigido.
- `scripts/provisionar_topologia.py` — provisionamento manual (único uso da credencial admin).
- `scripts/teste_falha_dlq.py` — teste de falha ao vivo; bug de confirmação corrigido.
- `workers/consumidor_continuo.py` / `workers/consumidor_convites.py` — usam a credencial de papel consumidor.
- `jobs/monitorar_dlq.py` — monitoramento/alerta da DLQ.
- `main.py` — rota `POST /executar/monitorar-dlq`.
- `.env.example` — documenta as variáveis novas.
- `RABBITMQ_AUTORIZACAO.md` — roteiro técnico detalhado de execução.
- Este documento (`ETAPAS_3_4_5_MENSAGERIA.md`) e os prints do painel CloudAMQP (anexos à entrega).

## 6. Conclusão

As 3 lacunas identificadas nas Etapas 3–5 foram fechadas e comprovadas com execução real, não apenas em teoria: separação de papel implementada em código (com uma restrição real de infraestrutura identificada, documentada com fonte oficial, e um caminho de migração pronto); caminho de falha reproduzido ao vivo múltiplas vezes com evidência auditável via `x-death`; e monitoramento validado de ponta a ponta, com alerta de e-mail realmente entregue. O processo de testar ao vivo (Etapa 4) ainda revelou e permitiu corrigir um bug real de confiabilidade na publicação de mensagens, reforçando na prática por que times de sistemas distribuídos testam caminhos de falha deliberadamente em vez de assumir que o caminho feliz é suficiente.

# Autorização real no RabbitMQ, teste de falha (DLQ) e monitoramento

Este documento é o roteiro pra fechar as 3 lacunas da Etapa 3-5 do
trabalho de Sistemas Distribuídos (mensageria): autorização de verdade
(separação de papel produtor/consumidor), um exemplo ao vivo do
caminho de falha (DLQ) e monitoramento/alerta sobre a fila morta.

O código já está pronto (ver lista de arquivos no final). O que falta
é você fazer, no painel do CloudAMQP: **criar os 2 usuários novos** e
**trocar as variáveis de ambiente** onde o backend roda. Depois disso,
os scripts de teste fazem o resto.

---

## 1. O que mudou e por quê

Antes: uma única credencial (usuário/senha do CloudAMQP) com acesso
total ao vhost -- o mesmo usuário publicava, consumia, criava e
apagava filas. Não existia separação nenhuma de permissão por papel.
Isso é exatamente a lacuna de "autorização" que o enunciado pede na
Etapa 3.

Agora: 3 credenciais, cada uma só com o que precisa (princípio do
menor privilégio):

| Credencial | Usado por | Pra quê |
|---|---|---|
| **admin** (a original, `RABBITMQ_URL`) | só `scripts/provisionar_topologia.py`, rodado manualmente por você | criar/alterar exchange, filas e bindings |
| **radar_publisher** (`RABBITMQ_URL_PUBLISHER`) | jobs que enfileiram convite/lembrete (`clients/rabbitmq_client.py::publicar_mensagens`) | só publicar na exchange |
| **radar_consumidor** (`RABBITMQ_URL_CONSUMIDOR`) | os dois workers consumidores + o monitor da DLQ | só ler das filas e mandar mensagem morta pra DLQ |

A credencial admin **nunca mais** é usada por um processo que fica no
ar -- só nesse script manual. Isso também muda um detalhe técnico: os
workers e os jobs **não redeclaram mais a topologia a cada conexão**
(isso exigia permissão `configure`, que as credenciais novas não têm).
A topologia passa a ser responsabilidade exclusiva do script de
provisionamento.

## 2. Matriz de permissões exata

Baseado na documentação oficial do RabbitMQ sobre controle de acesso
([rabbitmq.com/docs/access-control](https://www.rabbitmq.com/docs/access-control)):
`basic.publish` exige `write` na exchange; `basic.consume`/`basic.get`
exigem `read` na fila; a exchange padrão (sem nome) é tratada
internamente como o recurso `amq.default` pra fins de permissão; e
verificações "passive" (usadas pelo monitor pra só *consultar* a
profundidade da DLQ sem alterar nada) exigem pelo menos uma das três
permissões no recurso.

| Usuário | Configure | Write | Read |
|---|---|---|---|
| `radar_publisher` | *(vazio)* | `^radar\.eventos$` | *(vazio)* |
| `radar_consumidor` | `^fila\..*$` | `^amq\.default$` | `^fila\..*$` |

Por que cada campo:
- **radar_publisher.write = `^radar\.eventos$`** -- só publica na
  exchange principal. Não lê nenhuma fila (nem a DLQ), não cria nem
  apaga nada.
- **radar_consumidor.read = `^fila\..*$`** -- lê `fila.enviar_convite`,
  `fila.enviar_convite.prioritaria` e `fila.enviar_convite.dlq` (usada
  só pela consulta passiva do monitor). Não lê nada fora do prefixo
  `fila.`.
- **radar_consumidor.write = `^amq\.default$`** -- é o mínimo pra
  conseguir fazer `basic_publish(exchange="", routing_key=FILA_DLQ)`
  (como o consumidor manda a mensagem morta pra DLQ). Repare que isso
  NÃO dá acesso de escrita à exchange `radar.eventos` -- o consumidor
  continua sem conseguir agir como produtor.
- **radar_consumidor.configure = `^fila\..*$`** -- só entra por causa
  da consulta passiva do monitor da DLQ (`queue_declare(passive=True)`).
  Dependendo da versão do RabbitMQ do seu plano CloudAMQP, uma consulta
  passiva pode exigir isso além de `read` -- deixar os dois cobre as
  duas situações sem abrir mão do escopo (`fila.*`, nunca a exchange).

## 3. Passo a passo no painel do CloudAMQP

1. Entre na instância do CloudAMQP → botão **RabbitMQ Manager** (abre
   a interface de administração do RabbitMQ, em outra aba).
2. Aba **Admin** → **Add a user**:
   - Username: `radar_publisher` / Password: gere uma senha forte →
     **Add user**.
   - Clique no usuário recém-criado → em **Permissions**, escolha o
     vhost do projeto → cole os 3 campos da tabela acima (linha do
     publisher) → **Set permission**.
   - Repita pra `radar_consumidor` com a linha do consumidor.
3. Anote as duas connection strings novas. O formato é o mesmo de
   sempre, só trocando usuário/senha:
   ```
   amqps://radar_publisher:SENHA_AQUI@SEU-HOST.cloudamqp.com/SEU-VHOST
   amqps://radar_consumidor:SENHA_AQUI@SEU-HOST.cloudamqp.com/SEU-VHOST
   ```
   (host e vhost são os MESMOS da sua `RABBITMQ_URL` atual -- só
   usuário e senha mudam.)

## 4. Onde trocar as variáveis de ambiente

Você tem processos rodando em mais de um lugar (ver `STACK.md` /
`radar-consumidor.service`) -- atualize o `.env` (ou as env vars do
painel) em **todos**:

- **Render/Railway** (API + thread do `consumidor_continuo`, se ainda
  estiver assim): painel do serviço → Environment/Variables → adicionar
  `RABBITMQ_URL_PUBLISHER` e `RABBITMQ_URL_CONSUMIDOR`. Pode manter
  `RABBITMQ_URL` (admin) lá também, sem problema -- só não é mais usada
  em nenhum código que roda nesse serviço, exceto se você rodar o
  script de provisionamento a partir dele.
- **VM Oracle Cloud** (`workers/consumidor_continuo.py` via
  `radar-consumidor.service`): editar `/home/ubuntu/mindpulse-backend/.env`
  acrescentando as duas linhas novas, depois `sudo systemctl restart
  radar-consumidor`.
- **Seu `.env` local**, se for rodar os scripts de teste da sua máquina.

## 5. Ordem de execução (importante seguir essa ordem)

1. Criar os 2 usuários no CloudAMQP (seção 3).
2. Com a credencial **admin** ainda configurada (a `RABBITMQ_URL` de
   sempre), rodar, uma vez:
   ```
   python -m scripts.provisionar_topologia
   ```
   Isso garante que exchange/filas/bindings já existem ANTES de trocar
   o código -- essencial, porque o código novo não declara mais nada
   sozinho.
3. Atualizar os arquivos do projeto com os arquivos entregues (lista na
   seção 8) e configurar `RABBITMQ_URL_PUBLISHER`/`RABBITMQ_URL_CONSUMIDOR`
   em todo lugar (seção 4).
4. Deploy normal (do seu jeito de sempre).
5. Validar: disparar `POST /executar/enviar-pesquisa` (ou qualquer fluxo
   que publique) e conferir nos logs que NENHUM erro de permissão
   apareceu. Se aparecer `ACCESS_REFUSED`/`PERMISSION_DENIED`, revise a
   regex daquele campo no CloudAMQP (o erro do RabbitMQ diz exatamente
   qual operação e recurso foram negados).

## 6. Rodar o teste de falha ao vivo (Etapa 4)

Com tudo já migrado e um consumidor rodando (a thread contínua, o
serviço na VM, ou o cron chamando `/executar/processar-fila-convites`
com intervalo curto):

```
python -m scripts.teste_falha_dlq
```

Isso publica 1 mensagem de propósito incompleta (só com `"tipo":
"convite"`, sem os campos que o consumidor precisa pra montar o
e-mail). O script explica no terminal o que esperar. Resumindo:

- **Entrada**: mensagem JSON incompleta na fila `fila.enviar_convite`.
- **Processamento**: o consumidor tenta montar o e-mail, estoura
  `KeyError`, faz `nack` -- a própria fila manda pro retry (TTL 30s) e
  isso se repete 3x (contado pelo header `x-death`, nativo do
  RabbitMQ). Na 3ª falha, o consumidor publica manualmente o corpo
  original na DLQ e só aí confirma a saída da fila principal.
- **Saída esperada**: `fila.enviar_convite.dlq` com +1 mensagem.

O que capturar como evidência pra Etapa 4:
- Print do painel CloudAMQP (RabbitMQ Manager → Queues and Streams)
  mostrando a contagem da DLQ subindo de 0 pra 1.
- As linhas de log do consumidor (`[consumidor_continuo] ... -> retry
  (tentativa 1/2)`, depois `-> DLQ após 3 tentativas`).
- Opcional: "Get Message(s)" na DLQ pelo painel, mostrando o corpo
  original e o header `x-death` com as 3 rejeições.

Tempo total esperado: ~70-100s se o consumidor contínuo estiver
rodando (dá pra simplesmente esperar e atualizar o painel).

## 7. Testar o monitor/alerta da DLQ (Etapa 5)

Depois que a mensagem de teste já estiver na DLQ (seção 6), dispare o
monitor manualmente (pelo Swagger em `/docs`, Postman, ou curl):

```
curl -X POST https://SEU-BACKEND/executar/monitorar-dlq \
  -H "X-API-Key: SUA_BACKEND_API_KEY"
```

Resposta esperada: `{"mensagens_na_dlq": 1, "alerta_enviado": true,
"notificados": [...]}` e um e-mail chegando nos endereços de
`ADMIN_EMAILS` avisando da mensagem parada. Configure esse endpoint no
cron-job.org (mesmo esquema dos outros `/executar/*`) com um intervalo
de 10-15 minutos pra virar monitoramento contínuo de verdade, não só
manual.

## 8. Arquivos entregues nesta etapa

- `mindpulse-backend/config.py` -- 3 credenciais RabbitMQ em vez de 1.
- `mindpulse-backend/clients/rabbitmq_client.py` -- conexões separadas
  por papel; `declarar_topologia` isolada pro script admin.
- `mindpulse-backend/scripts/provisionar_topologia.py` -- novo.
- `mindpulse-backend/scripts/teste_falha_dlq.py` -- novo.
- `mindpulse-backend/workers/consumidor_continuo.py` -- usa credencial
  de consumidor.
- `mindpulse-backend/workers/consumidor_convites.py` -- usa credencial
  de consumidor.
- `mindpulse-backend/jobs/monitorar_dlq.py` -- novo.
- `mindpulse-backend/main.py` -- nova rota `POST /executar/monitorar-dlq`.
- `mindpulse-backend/.env.example` -- documenta as variáveis novas.
- `mindpulse-backend/RABBITMQ_AUTORIZACAO.md` -- este arquivo.

## 9. Texto pronto pra colar no documento (Etapas 3-5)

### Etapa 3 -- Requisitos de segurança (autorização)

> A autenticação é feita por usuário/senha do CloudAMQP em conexão
> `amqps://` (TLS). A autorização segue o princípio do menor
> privilégio, com 3 credenciais de papel distinto no mesmo vhost: uma
> credencial administrativa, usada apenas no provisionamento manual da
> topologia (criação de exchange, filas e bindings) e nunca por um
> processo em produção; uma credencial de produtor, com permissão de
> escrita restrita à exchange `radar.eventos` e nenhuma permissão de
> leitura; e uma credencial de consumidor, com permissão de leitura
> restrita às filas com prefixo `fila.` e permissão de escrita restrita
> à exchange padrão (usada apenas para encaminhar manualmente uma
> mensagem à fila morta). Nenhuma das credenciais de aplicação tem
> permissão `configure`, ou seja, nenhum processo em produção consegue
> criar, alterar ou apagar exchanges e filas -- apenas usá-las.

### Etapa 4 -- Exemplo de uso: caminho de falha

> **Entrada**: mensagem JSON publicada na fila `fila.enviar_convite`
> sem os campos obrigatórios para montar o e-mail do convite.
> **Processamento**: o consumidor tenta montar o e-mail e falha
> (exceção); a mensagem é rejeitada (`nack`) e o dead-letter-exchange
> da própria fila a move automaticamente para
> `fila.enviar_convite.retry`, onde aguarda 30 segundos (TTL) antes de
> retornar à fila principal. O RabbitMQ registra cada rejeição no
> header nativo `x-death`. Após a 3ª tentativa malsucedida, o
> consumidor publica manualmente o corpo original (preservando o
> histórico de `x-death`) na fila `fila.enviar_convite.dlq`.
> **Saída esperada**: a mensagem passa a residir na fila morta, visível
> e auditável pelo painel de administração, sem perda de dados e sem
> impedir o processamento das demais mensagens da fila principal.

### Etapa 5 -- Boas práticas: monitoramento da fila morta

> Para evitar que uma falha recorrente passe despercebida, um job
> agendado consulta periodicamente (a cada 10-15 minutos) a
> profundidade da fila morta por meio de uma consulta passiva (que não
> altera nem consome mensagens) e, ao detectar ao menos uma mensagem
> parada, envia um alerta por e-mail à equipe responsável via Brevo,
> permitindo intervenção manual (reprocessamento ou descarte) antes que
> o problema se acumule.

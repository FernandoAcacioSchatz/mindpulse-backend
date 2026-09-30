# Autorização no RabbitMQ, teste de falha (DLQ) e monitoramento

Este documento é o roteiro pra fechar as 3 lacunas da Etapa 3-5 do
trabalho de Sistemas Distribuídos (mensageria): autorização
(separação de papel produtor/consumidor), um exemplo ao vivo do
caminho de falha (DLQ) e monitoramento/alerta sobre a fila morta.

**Atualização importante**: ao tentar criar os usuários novos no
CloudAMQP, descobrimos que o plano gratuito não permite isso (seção 2
explica). Os itens 2 (teste de falha) e 3 (monitoramento) não são
afetados por isso -- seguem funcionando normalmente com a credencial
única de sempre. Já o item 1 (autorização) teve que ser adaptado: o
código já está pronto pra separação de papel, mas ela só vira real
quando/se você criar as credenciais novas (seção 2 explica os
caminhos). O que sobra pra fazer AGORA está resumido na seção 5.

---

## 1. O que foi identificado (a lacuna original)

Antes: uma única credencial (usuário/senha do CloudAMQP) com acesso
total ao vhost -- o mesmo usuário publicava, consumia, criava e
apagava filas. Não existia separação nenhuma de permissão por papel.
Essa é a lacuna de "autorização" que o enunciado pede na Etapa 3.

## 2. Limitação descoberta: o plano gratuito não deixa criar usuários

Ao tentar seguir o plano original (criar 2 usuários novos no painel
"Admin" do RabbitMQ Manager), o botão "Add a user" simplesmente não
aparece. Não é erro de configuração -- é uma restrição documentada da
própria CloudAMQP:

> "It is only possible to manage users, virtual hosts and permissions
> on dedicated plans. A dedicated plan is Sassy Squirrel or any plan
> larger than Sassy Squirrel." -- [CloudAMQP FAQ](https://www.cloudamqp.com/docs/faq.html)

O plano usado neste projeto é o **Little Lemur** (gratuito,
compartilhado com outros clientes no mesmo cluster) -- exatamente a
categoria que a CloudAMQP exclui dessa funcionalidade. Faz sentido do
ponto de vista deles: dar a um usuário do plano grátis a permissão
`administrator` do RabbitMQ (necessária pra criar/gerenciar outros
usuários) daria a ele visibilidade sobre um cluster compartilhado com
outras contas.

**Dois caminhos existem pra resolver isso de verdade**, se você quiser
ir além do que este documento cobre hoje:

1. **Upgrade pago** pro plano Sassy Squirrel (a partir de ~US$19/mês)
   -- libera o Admin de usuários sem sair da CloudAMQP nem migrar nada.
2. **Self-host o broker** (RabbitMQ via Docker, por exemplo) na sua VM
   Oracle Cloud Always Free -- a mesma que já roda o
   `workers/consumidor_continuo.py` via `radar-consumidor.service`.
   Nela você tem acesso de administrador total, sem custo, mas dá
   trabalho extra (instalar, abrir porta/firewall na Oracle Cloud,
   migrar a connection string em todo lugar) que não cabe no prazo de
   hoje.

Nenhum dos dois é necessário pra entregar o trabalho -- ver seção 3.

## 3. O que já está resolvido, mesmo sem os usuários novos

O código entregue (zip anterior) já foi reorganizado seguindo o
princípio do menor privilégio, mesmo rodando hoje com uma única
credencial real:

- **`clients/rabbitmq_client.py`** agora tem 3 funções de conexão
  (`conectar_admin`, `conectar_publicador`, `conectar_consumidor`) e a
  criação da topologia (exchange/filas/bindings, que exige permissão
  `configure`) foi isolada num script separado
  (`scripts/provisionar_topologia.py`). **Nenhum processo que fica no
  ar (jobs, workers) usa mais permissão `configure` em nada** -- só
  usa os recursos que já existem.
- **`config.py`** já lê 3 variáveis de ambiente distintas
  (`RABBITMQ_URL`, `RABBITMQ_URL_PUBLISHER`, `RABBITMQ_URL_CONSUMIDOR`).
  Hoje, como as duas últimas não existem ainda, ele cai de volta pra
  credencial única sozinho (e avisa isso no log -- esperado, não é
  erro).
- No dia em que você criar `radar_publisher`/`radar_consumidor` (por
  qualquer um dos 2 caminhos da seção 2), a migração é só preencher
  essas 2 variáveis de ambiente -- **nenhuma linha de código muda**.

## 3.1 Matriz de permissão -- o desenho alvo (pra quando as credenciais existirem)

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

Se um dia você seguir o caminho 1 ou 2 da seção 2, o passo a passo é:
criar os 2 usuários (Admin → Add a user), colar essas 3 regexes em
cada um (Permissions → escolher o vhost), gerar as 2 connection
strings novas (mesmo host/vhost de hoje, só trocando usuário/senha) e
preencher `RABBITMQ_URL_PUBLISHER`/`RABBITMQ_URL_CONSUMIDOR` no
Render/Railway e no `.env` da VM Oracle.

## 4. O texto da Etapa 3 já reflete isso (seção 9) -- nada a esconder

Pra um trabalho de Sistemas Distribuídos, identificar e documentar uma
restrição real de infraestrutura (com a fonte oficial citada) é, em si,
uma conclusão de arquitetura válida -- diferente de simplesmente não
ter percebido o problema. O texto pronto da seção 9 já está escrito
nesse tom: honesto sobre o estado atual, claro sobre o que foi
projetado e por que ainda não está 100% ativo.

## 5. O que fazer agora (resumo prático)

1. Nada a fazer no CloudAMQP -- não existe usuário novo pra criar hoje.
2. Aplicar os arquivos do zip entregue (sobrescreve os 6 existentes,
   adiciona os 5 novos -- ver seção 8).
3. Rodar **uma vez**, com a `RABBITMQ_URL` de sempre já configurada:
   ```
   python -m scripts.provisionar_topologia
   ```
   (garante que a topologia existe -- o código novo não cria mais nada
   sozinho em tempo de execução).
4. Deploy normal, do seu jeito de sempre. Nenhuma variável de ambiente
   nova é *obrigatória* -- `RABBITMQ_URL_PUBLISHER`/`RABBITMQ_URL_CONSUMIDOR`
   ficando vazias é esperado, e o aviso que aparece no log confirma
   isso (não é erro).
5. Validar: disparar qualquer fluxo que publique (ex.:
   `POST /executar/enviar-pesquisa`) e conferir que não apareceu
   nenhum erro nos logs.
6. Seguir pras seções 6 e 7 (teste de falha e monitoramento) -- essas
   não dependem de nada da autorização, podem ser feitas já.

## 6. Rodar o teste de falha ao vivo (Etapa 4)

Com um consumidor rodando (a thread contínua, o serviço na VM, ou o
cron chamando `/executar/processar-fila-convites` com intervalo
curto):

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

- `mindpulse-backend/config.py` -- lê as 3 variáveis, cai pra 1 sozinho.
- `mindpulse-backend/clients/rabbitmq_client.py` -- conexões separadas
  por papel; `declarar_topologia` isolada pro script admin.
- `mindpulse-backend/scripts/provisionar_topologia.py` -- novo.
- `mindpulse-backend/scripts/teste_falha_dlq.py` -- novo.
- `mindpulse-backend/workers/consumidor_continuo.py` -- usa
  `conectar_consumidor()`.
- `mindpulse-backend/workers/consumidor_convites.py` -- usa
  `conectar_consumidor()`.
- `mindpulse-backend/jobs/monitorar_dlq.py` -- novo.
- `mindpulse-backend/main.py` -- nova rota `POST /executar/monitorar-dlq`.
- `mindpulse-backend/.env.example` -- documenta as variáveis novas.
- `mindpulse-backend/RABBITMQ_AUTORIZACAO.md` -- este arquivo.

## 9. Texto pronto pra colar no documento (Etapas 3-5)

### Etapa 3 -- Requisitos de segurança (autorização)

> A autenticação é feita por usuário/senha do CloudAMQP em conexão
> `amqps://` (TLS). Para a autorização, o projeto adota o princípio do
> menor privilégio na camada de aplicação: a criação da topologia
> (exchange, filas e bindings), que exige permissão administrativa
> (`configure`), foi isolada em um script de provisionamento executado
> manualmente; nenhum processo em execução contínua (produtores ou
> consumidores) declara ou altera topologia em tempo de execução --
> apenas utiliza os recursos já existentes. O código já está
> estruturado para três credenciais de papel distinto no mesmo vhost
> (administrativa, produtor com permissão de escrita restrita à
> exchange principal, e consumidor com permissão de leitura restrita às
> filas da aplicação), documentadas com a matriz completa de permissões
> `configure`/`write`/`read` de cada uma.
>
> Durante a implementação, identificou-se uma restrição da
> infraestrutura utilizada: o provedor gerenciado (CloudAMQP) reserva a
> criação de usuários e permissões adicionais aos planos pagos
> ("dedicados"), não a disponibilizando no plano gratuito compartilhado
> usado neste projeto -- restrição documentada na própria FAQ do
> provedor. Por esse motivo, as três credenciais de papel distinto
> ainda não estão ativas com segredos diferentes em produção; a
> separação de responsabilidades já implementada no código, porém,
> permite que essa migração ocorra sem nenhuma alteração de software,
> bastando provisionar as credenciais (via upgrade de plano ou
> hospedagem própria do broker) e configurá-las como variáveis de
> ambiente.

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

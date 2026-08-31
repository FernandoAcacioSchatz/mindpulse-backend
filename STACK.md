# Stack do Radar

Ferramentas, serviços e bibliotecas usadas no backend do Radar, organizadas por função — documento de apoio para pitch.

## 1. Linguagem & Framework

- **Python** — linguagem de todo o backend.
- **FastAPI** — framework web que expõe as rotas (`/executar/*`, `/admin/*`, webhooks) e gera a documentação interativa em `/docs`.
- **Uvicorn** — servidor ASGI que roda a aplicação em produção.
- **Pydantic** — valida o formato e os tipos de cada payload recebido antes de qualquer regra de negócio rodar.

## 2. Banco de Dados & Autenticação

- **Supabase** — banco Postgres principal, acessado pelo backend com a chave `service_role`, que ignora as políticas de RLS.
- **Supabase Auth** — emite o token de sessão quando um RH faz login no app.
- **PyJWT + cryptography** — valida esse token no backend usando a chave pública do projeto (ES256, via JWKS); nenhum segredo de assinatura fica guardado no backend.

## 3. Inteligência Artificial

- **Google Gemini** (`gemini-3.6-flash`) — chamado por um endpoint compatível com a API da OpenAI, gera o resumo executivo e as recomendações de cada ciclo de pesquisa.
- **scikit-learn** — classificador KNN treinado para dar uma segunda opinião sobre o índice de bem-estar por setor e empresa, ao lado do cálculo determinístico.
- **Classificador de regras** (regex, próprio) — detecta comentários de risco (assédio, risco à vida) por padrões de texto, 100% local e explicável, sem enviar comentário nenhum a uma API externa.
- **pandas · numpy · joblib** — preparam os dados de treino e carregam os modelos já treinados em produção.

## 4. Comunicação

- **Brevo** — dispara os e-mails transacionais: convite de pesquisa, lembretes e alertas críticos ao RH.
- **httpx** — cliente HTTP usado para chamar a API da Brevo.

## 5. Infraestrutura & Automação

- **Railway** — hospeda o backend em produção.
- **cron-job.org** — dispara os horários fixos (envio, lembretes, encerramento) de fora do processo; substituiu um agendador interno que falhava quando o servidor "dormia".
- **Vercel** — hospeda o app web que o RH usa para acompanhar os ciclos; consome este backend, mas fica fora deste repositório.

## 6. Segurança

- **Chave de API própria** (`X-API-Key`) — protege as chamadas de sistema para sistema (agendador, webhooks).
- **JWT do Supabase** — protege as chamadas feitas por um RH logado no app.
- **CORS + cabeçalhos de segurança** — origens permitidas, HSTS, `X-Frame-Options` e afins, configurados diretamente no FastAPI.
- **python-dotenv** — carrega as chaves e segredos de variáveis de ambiente, fora do código-fonte.

## Nota para o pitch

O Radar está em transição: o backend em Python descrito acima está substituindo, peça por peça, um conjunto de fluxos que rodava no **n8n** (automação no-code). As duas coisas rodam em paralelo até cada peça ser validada em produção — um sinal de maturidade técnica que vale citar: o produto nasceu rápido e está sendo reconstruído em uma base própria, testável e auditável, sem parar de funcionar no meio do caminho.

Vale destacar também a escolha deliberada de manter os classificadores de risco (comentários sensíveis, qualidade de resposta) como regras explicáveis em vez de caixas-pretas de IA: em uma auditoria trabalhista, toda sinalização crítica precisa vir com o motivo exato.

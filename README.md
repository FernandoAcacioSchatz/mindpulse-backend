# MindPulse Backend (Python)

Esqueleto do backend que vai substituir o n8n, uma peça de cada vez —
conforme o plano do Documento 12.

## Rodando localmente

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt

copy .env.example .env         # Windows (ou "cp" no Git Bash/Mac/Linux)
# preenche o .env com suas chaves reais

uvicorn main:app --reload
```

Acessa `http://127.0.0.1:8000` — deve responder `{"status": "ok", ...}`.

Testa o job já migrado sem esperar o horário:
```bash
curl -X POST http://127.0.0.1:8000/executar/lembrete-diario
```

## Estrutura

```
mindpulse-backend/
├── main.py                       # FastAPI + agendador
├── config.py                     # variáveis de ambiente
├── clients/                      # conexões externas (Supabase, OpenAI, Brevo)
├── jobs/                         # equivalentes aos Schedule Trigger do n8n
├── routes/                       # equivalentes aos Webhook do n8n
└── ml/                           # checagem de qualidade de resposta
```

## Status da migração

| Peça | Status | Arquivo |
|---|---|---|
| Lembrete Diário | ✅ Migrado e funcional | `jobs/lembrete_diario.py` |
| Enviar Pesquisa | ⬜ Esqueleto pronto, lógica pendente | `jobs/enviar_pesquisa.py` |
| Encerrar Pesquisa + IA | ⬜ Esqueleto pronto, lógica pendente | `routes/encerrar_pesquisa.py` |
| Notificar Alerta Crítico | ⬜ Esqueleto pronto, lógica pendente | `routes/notificar_critico.py` |
| Checagem de qualidade (novo, não existia no n8n) | ✅ Implementado (Fase 1) | `ml/qualidade_resposta.py` |

## Pré-requisito pendente no banco

Rodar `19-coluna-iniciado-em.sql` no Supabase — sem essa coluna, a
checagem de qualidade não consegue calcular tempo de preenchimento
(só o desvio padrão das respostas, que já funciona sem ela).

## Deploy (quando chegar a hora)

Mesma lógica do n8n: Railway, com uma variável de ambiente adicional
de porta (`$PORT`, o Railway já injeta sozinha) e o comando de start:
```
uvicorn main:app --host 0.0.0.0 --port $PORT
```

## Importante: não desliga o n8n ainda

Esse backend roda **em paralelo** com o n8n até cada peça estar migrada
e testada individualmente. Só desativa o workflow equivalente no n8n
depois que a versão Python correspondente já rodou de verdade, sem
erro, pelo menos uma vez em produção.

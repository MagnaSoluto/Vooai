# Fase 0 local — carteira + billing FourDev (desligado por padrão)

## Modo atual: API gratuita

```bash
export VOOAI_BILLING_ENABLED=0   # default — sem Bearer, sem débito no /search
```

Use assim enquanto a cota SerpAPI (~50 testes) durar. Conta/recarga PIX já existem, mas não bloqueiam busca.

## Quando for cobrar

```bash
export VOOAI_BILLING_ENABLED=1
# Mesmos nomes do SDR (projeto irmão):
export BILLING_API_URL=http://127.0.0.1:8380          # local barber
# export BILLING_API_URL=http://billing-api:8080      # box
export BILLING_API_TOKEN=...
```

Detalhe do PSP: [`billing-fourdev.md`](billing-fourdev.md) · SDR: `../SDR/docs/BILLING-CHECKOUT.md`.

| Ambiente | URL |
|----------|-----|
| **FourDev / box** | `VOOAI_DATABASE_URL=postgresql://sdr:…@postgres:5432/vooai` |
| Laptop com SDR docker | `postgresql://sdr:sdr_dev_password@127.0.0.1:5432/vooai` |
| Sem Postgres | omitir URL → **SQLite** `data/vooai_billing.sqlite` (só dev) |

**Não** aponte para o database `sdr` — crie o DB `vooai`.

```bash
# sobe Postgres do SDR se ainda não estiver up
cd ../SDR && docker compose up -d postgres

# cria DB + schema
cd ../vooai && ./pipelines/init_postgres_vooai.sh

export VOOAI_DATABASE_URL=postgresql://sdr:sdr_dev_password@127.0.0.1:5432/vooai
export VOOAI_BILLING_ENABLED=1
export REDIS_URL=redis://127.0.0.1:6379/0
```

## Fluxo API

```bash
cd apps/api && .venv/bin/uvicorn app.main:app --reload --port 8000

curl -s -X POST localhost:8000/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"voce@vooai.local"}' | jq .

TOKEN=...
curl -s -X POST localhost:8000/wallet/topup -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"amount_brl":2}' | jq .

curl -s localhost:8000/pricing | jq '{db,billing_enabled,quote}'
```

## Regras (só com `VOOAI_BILLING_ENABLED=1`)

| Evento | Débito? |
|--------|---------|
| Busca entregue (miss SerpAPI) | Sim |
| Busca entregue (cache hit) | Sim (não gasta SerpAPI — margem nossa) |
| Falha e busca **não** entregue (502/503/400/erro) | Estorno |
| Saldo baixo | HTTP **402** (sem débito) |

Com billing **off** (default agora): `/search` livre, sem token.

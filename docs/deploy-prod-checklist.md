# Checklist — subir VooAI em produção (box FourDev)

Depois do desenvolvimento local. Ordem barata e segura.

## 1. Postgres `vooai`

No host com o Postgres SDR:

```bash
./pipelines/init_postgres_vooai.sh
# ou na box: POSTGRES_HOST=… ./pipelines/init_postgres_vooai.sh
```

Confirme: `\l` mostra `vooai`.

## 2. Env da API (`/opt/vooai/api.env`)

```bash
SERPAPI_API_KEY=...
VOOAI_BILLING_ENABLED=0
VOOAI_DATABASE_URL=postgresql://sdr:SENHA@postgres:5432/vooai
REDIS_URL=redis://vooai-redis:6379/0
VOOAI_QUOTE_CACHE_TTL_SEC=1200
VOOAI_SERPAPI_COST_BRL=0.08
VOOAI_ADMIN_TOKEN=...gerado...
VOOAI_DATA_DIR=/data
VOOAI_SPEC_DIR=/data/Spec
# Billing FourDev (obrigatório em prod para PIX)
BILLING_API_URL=http://billing-api:8080
BILLING_API_TOKEN=...mesmo do /opt/billing/app.env...
```

No **billing** (`/opt/billing/app.env`): `VOOAI_BASE_URL=http://vooai-api:8000` (ou URL pública `/api`).

## 3. Build + deploy imagens

```bash
# local
docker build -f apps/api/Dockerfile -t vooai/api:latest .
docker build -f apps/web/Dockerfile --build-arg VITE_API_URL=https://vooai.magnasoluto.com.br/api -t vooai/web:latest apps/web
# push ECR + scripts/deploy-box.sh (como já feito no MVP)
```

Compose da box já inclui `vooai-redis`. Garantir `VOOAI_DATABASE_URL` no env_file.

## 4. Crontab fábrica (barato)

Instalar `pipelines/crontab.example` no host (repo em `/opt/vooai/repo`).

Smoke:

```bash
python -m pipelines.ingest_anac_vra --poll
python -m pipelines.collect_quotes --dry-run --max-routes 1
```

## 5. Validação HTTP

```bash
curl -s https://HOST/api/health | jq .
curl -s https://HOST/api/pricing | jq '{db,billing_enabled,table}'
# register → topup → search com Bearer
```

## 6. Front

- Conta: `/conta`
- Busca sem token + billing on → redireciona para conta
- KPIs: custo da busca / cache grátis / saldo

## 7. AdSense (opcional)

Build web com `VITE_ADSENSE_CLIENT` + `VITE_ADSENSE_SLOT`.

## 8. Pós-go-live

- [ ] Alerta cota SerpAPI 80%
- [ ] Trocar stub topup por Mercado Pago PIX
- [ ] Backup Postgres `vooai`
- [ ] Monitorar `/health` + margem mensal (§9 do plano)

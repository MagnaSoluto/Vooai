# VooAI — fábrica barata na box AWS (sem Glue, sem Kafka, fora da API de produto)

## Por que não Glue / não API?

| Opção | Veredito |
|-------|----------|
| **AWS Glue** | Caro e overkill (~9 GB batch mensal + cotações leves). |
| **ETL via `/search` da API** | Mistura serving com fábrica; timeout, cota e débito de carteira. |
| **Cron + Python + Polars na mesma EC2** | **Escolhido** — custo ≈ zero além da box e SerpAPI. |
| **Redis** | Cache de cotação + (futuro) fila RQ — não Kafka. |
| **Databricks Free** | Opcional para treino pesado 08/09; não no path do request. |

## Jobs

| Módulo | Cadência | O que faz |
|--------|----------|-----------|
| `pipelines.ingest_anac_vra` | 1×/semana | Poll ANAC dados abertos → `SoR_voos_operacoes` |
| `pipelines.collect_quotes` | 1–2×/dia | SerpAPI → `SoR_cotacoes` (rotas MVP) |
| `pipelines.etl_quotes` | após collect | SoR → `SoT_cotacoes` + `Spec/spec_cotacoes` |
| `pipelines.publish_spec` | após etl | Reload API (`/admin/reload-spec`) |
| `pipelines/run_heavy_etl.sh` | mensal (mês VRA novo) | nbconvert 08+09 (CPU/RAM) |

## Local

```bash
# Redis (cache da API)
docker compose up -d redis

# Poll ANAC (sem baixar se já tem)
python3 -m pipelines.ingest_anac_vra --poll

# Baixar mês mais recente faltante
python3 -m pipelines.ingest_anac_vra --latest

# Collector (precisa SERPAPI_API_KEY)
export SERPAPI_API_KEY=...
python3 -m pipelines.collect_quotes --max-routes 2   # teste barato
python3 -m pipelines.etl_quotes
python3 -m pipelines.publish_spec --no-reload

# Nightly completo (leve)
python3 -m pipelines.run_nightly --max-routes 15
```

## Crontab na box (`crontab -e`)

Ver `pipelines/crontab.example`.

## Env

| Var | Uso |
|-----|-----|
| `SERPAPI_API_KEY` | Collector + API |
| `VOOAI_DATA_DIR` | Root data (default `./data`) |
| `VOOAI_SPEC_DIR` | Spec |
| `VOOAI_ADMIN_TOKEN` | Auth do `/admin/reload-spec` |
| `VOOAI_RELOAD_URL` | Default `http://vooai-api:8000/admin/reload-spec` na box |
| `REDIS_URL` | Cache da API (não do ETL) |

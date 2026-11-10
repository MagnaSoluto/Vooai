# Collectors — cotações

A implementação viva está em **`pipelines/`** (fábrica barata na box AWS).

| Antes (stub) | Agora |
|--------------|--------|
| Script a implementar | `python -m pipelines.collect_quotes` |
| SoR destino | `data/SoR/SoR_cotacoes/dt=YYYY-MM-DD/*.parquet` |
| Cadência | 1–2×/dia — ver `pipelines/crontab.example` |

ANAC VRA: `python -m pipelines.ingest_anac_vra --poll|--latest`

ETL leve cotações: `python -m pipelines.etl_quotes`  
Heavy ANAC→Spec: `pipelines/run_heavy_etl.sh` (mensal)

Documentação: [`pipelines/README.md`](../pipelines/README.md) e [`docs/plano-producao-completo.md`](../docs/plano-producao-completo.md).

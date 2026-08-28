---
name: vooai-lakehouse
description: >-
  Camadas Bronze/Silver/Gold VooAI no Databricks Free, Delta, dicionário e
  sync git↔workspace. Use when designing tables, feature engineering,
  export Gold, or mentioning lakehouse/Delta/Unity no projeto Facu.
---

# Lakehouse (Databricks Free)

Arquitetura: `docs/arquitetura.md`. Dicionário: `docs/dicionario-de-dados.md`.

| Camada | Papel |
|--------|--------|
| Bronze | Bruto JSON/CSV → Delta |
| Silver | IATA, datas, nulos, dedup, features |
| Gold | Preços, KPIs ANAC, previsão, `action` |

Catálogo sugerido: `vooai.bronze|silver|gold`.

Ponte produto: `scripts/export_gold.py` → `data/gold/*.csv`. API não consulta o cluster por request no MVP. Amostras: `data/gold/sample/`.

Sync: `scripts/sync_notebooks.md`. Governança simulada (catálogo, LGPD, classificação). Sem OCI.

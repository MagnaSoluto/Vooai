---
name: vooai-api
description: >-
  FastAPI VooAI: SerpAPI Google Flights + Spec parquet. Use when
  editing apps/api, /search, /airports, /reliability, /models/metrics.
---

# API FastAPI

Path: `apps/api`.

- `GET /search?origin=&dest=&date=` — cotação SerpAPI + join `spec_modelos_risco`
- `GET /airports?q=` — resolução cidade/IATA via SoT aeroportos
- `GET /health` — Spec path, janela de datas, flag SerpAPI
- Env: `SERPAPI_API_KEY`, `VOOAI_SPEC_DIR`, `VOOAI_DATA_DIR`
- Não treina ML. Lê parquet Spec/SoT.
- Ação COMPRAR/AGUARDAR/MONITORAR: regra ±5% vs preço estimado/mediana

Subir: `uvicorn app.main:app --reload --port 8000`.

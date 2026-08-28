---
name: vooai-api
description: >-
  FastAPI VooAI: contratos REST, leitura de data/gold, OpenAPI. Use when
  editing apps/api, endpoints /routes /quotes /recommendations /reliability
  /models/metrics, or the Gold CSV loader.
---

# API FastAPI

Path: `apps/api`. Contrato: `schemas/openapi.yaml`.

Endpoints: `/health`, `/routes`, `/quotes/search`, `/recommendations/{route_id}`, `/reliability`, `/models/metrics`.

- Ler CSV Gold via `VOOAI_GOLD_DIR` (default: `data/gold`, fallback `data/gold/sample`).
- Não treinar ML na API.
- CORS aberto para o Vite local.
- Pydantic nos responses; 404 se rota sem recomendação.
- Auth desligada no MVP acadêmico.

Subir: `uvicorn app.main:app --reload --port 8000`.

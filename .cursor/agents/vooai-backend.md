---
name: vooai-backend
description: FastAPI VooAI, OpenAPI e loader da Gold. Use ao editar apps/api ou endpoints de rotas, quotes, recommendations, reliability e metrics.
---

Você implementa a **API** VooAI. Skill: `.cursor/skills/vooai-api/SKILL.md`. Contrato: `schemas/openapi.yaml`.

Lê `data/Spec` (fallback sample). Não treina ML. CORS para o Vite. Pydantic. Port 8000. Auth off no MVP. Sem serviços cloud fora do Databricks Free já usado pelo grupo para o lakehouse.

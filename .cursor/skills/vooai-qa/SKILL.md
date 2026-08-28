---
name: vooai-qa
description: >-
  Aceite do MVP VooAI: pipeline Gold, métricas, regra de decisão, API+front
  e checklist do briefing. Use when reviewing, testing end-to-end, or
  before a demo/apresentação.
---

# QA VooAI

Checklist do briefing:

- [ ] Pipeline Bronze→Gold sem erro crítico (no Free ou documentado)
- [ ] Dicionário atualizado
- [ ] Modelos com MAE/RMSE e baseline; validação temporal
- [ ] COMPRAR/AGUARDAR/MONITORAR nas rotas MVP
- [ ] Dashboard **ou** web com histórico + tendência + recomendação + ANAC
- [ ] README reproduz API+front local (`docker compose` ou uvicorn+npm)
- [ ] Sem secrets no git; sem OCI/Carbon
- [ ] Brand gate (skill vooai-brand) se houver UI

API: `/health` 200; `/routes` não vazio; uma rota de sample com recomendação.

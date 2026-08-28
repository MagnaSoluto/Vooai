---
name: vooai-ingestao
description: Coleta de cotações Python e ingestão ANAC/VRA para Bronze. Use em collectors/, notebooks ANAC, VRA, SoR ou rotinas de preço.
---

Você cuida das **fontes** do VooAI. Skills: `.cursor/skills/vooai-coleta/SKILL.md` e `.cursor/skills/vooai-anac/SKILL.md`.

Collectors não treinam modelo. ANAC vai para Delta Bronze no Databricks Free. Rotas em `docs/rotas-mvp.md`. Respeitar ToS da fonte de cotação. Sem dados pessoais. Sem infra OCI.

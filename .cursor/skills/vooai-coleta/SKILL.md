---
name: vooai-coleta
description: >-
  Rotina Python de cotações VooAI: schema, frequência, rotas MVP, persistência
  Bronze. Use when working on collectors/, quote jobs, lead_days, or airfare
  price scraping/APIs for the academic MVP.
---

# Coleta de cotações

- Rotas: `docs/rotas-mvp.md` (10–30).
- Schema: `docs/dicionario-de-dados.md` (quotes).
- Código: `collectors/`. Saída em `data/SoR/` (gitignore) → notebook 02 / 08 → SoT.
- Campos mínimos: rota, cia, collected_at, departure_at, lead_days, price_brl, duration_min, stops.
- Documentar a fonte e respeitar ToS. Sem martelar endpoints.
- Frequência sugerida no MVP: 1–2 coletas/dia por rota.

Não misturar lógica de ML no collector. Só capturar e versionar o schema.

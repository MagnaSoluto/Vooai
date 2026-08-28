---
name: vooai-anac
description: >-
  Ingestão ANAC VRA e bases SoR para KPIs de atraso/cancelamento e malha.
  Use when editing notebooks ANAC, VRA, SoR_*, reliability ranking, or
  ingestao-anac.ipynb.
---

# ANAC / VRA

- Notebooks: `notebooks/ingestao-anac.ipynb`, `notebooks/01_ingestao_anac.ipynb`.
- Bases do briefing: SoR_microdados, SoR_municipios, SoR_origens_destino, SoR_tarifas_aereas, SoR_voos_operacoes + VRA.
- Destino: Bronze no Databricks Free (Delta), não Unity corporativo de outro projeto.
- Indicadores Gold: `delay_rate`, `cancel_rate`, `reliability_rank` por cia e, se houver N, por rota.
- Ajustar URLs reais gov.br/ANAC; o protótipo atual é placeholder de path.
- Sem dados pessoais. Encoding típico latin-1 / separador `;` em microdados.

Ranking: menor atraso+cancelamento no recorte, com `sample_flights` visível.

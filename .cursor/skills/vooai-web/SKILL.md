---
name: vooai-web
description: >-
  Front VooAI React+Vite: Home, Resultado, Detalhe, Sobre; tokens do brand
  book. Use when editing apps/web, landing, search, recommendation UI.
---

# Front React + Vite

Path: `apps/web`. Tokens: skill `vooai-brand` + `branding/vooai-brand-book.html`.

Telas: Home (marca + busca), Resultado (preço + ação + confiabilidade), Detalhe (histórico/tendência), Sobre (método ±5% e fontes).

- Lista ranqueada **não** só por menor preço.
- `VITE_API_URL` (default http://localhost:8000).
- Sem cards no hero. Sem Inter/Roboto. Sem paleta fora do book.
- Estados loading / empty / error visíveis.

Skill brand é gate obrigatório antes de merge visual.

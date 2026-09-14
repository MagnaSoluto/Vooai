---
name: vooai-web
description: >-
  Front VooAI React+Vite: Home, Resultado (board), Sobre; tokens do brand
  book. Use when editing apps/web, landing, search, recommendation UI.
---

# Front React + Vite

Path: `apps/web`. Tokens: skill `vooai-brand` + `branding/vooai-brand-book.html`.

Telas: Home (marca + busca cidade/IATA), Resultado (KPIs + score + tabela + lateral), Sobre (método Spec + SerpAPI).

- Lista ranqueada por sinal + score + preço (não só menor preço).
- `VITE_API_URL` → `GET /search`.
- Sem cards no hero. Sem Inter/Roboto. Sem paleta fora do book.
- Estados loading / empty / error visíveis.

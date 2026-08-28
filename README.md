# VooAI

Sinal claro para comprar ou esperar. Projeto acadêmico (Mackenzie — Hands-On Fundamentos de Dados) que integra cotações de passagens nacionais, histórico ANAC e modelos de preço para recomendar **COMPRAR**, **AGUARDAR** ou **MONITORAR**.

Este repositório Git é a **fonte de verdade**. O Databricks Free Edition é só compute, Delta Lake e dashboard acadêmico.

## Monorepo

| Pasta | Função |
|-------|--------|
| [`apps/api`](apps/api) | FastAPI — consome Gold exportada |
| [`apps/web`](apps/web) | React + Vite — produto |
| [`branding`](branding) | Brand book HTML |
| [`collectors`](collectors) | Scripts Python de cotação |
| [`data`](data) | Exports locais (volumes pesados no `.gitignore`) |
| [`docs`](docs) | Briefing, arquitetura, dicionário |
| [`notebooks`](notebooks) | Ingestão, EDA, ML (sincronizar com o Free) |
| [`schemas`](schemas) | Contratos JSON |
| [`scripts`](scripts) | Sync Databricks + export Gold |
| [`.cursor`](.cursor) | Skills e agentes do projeto |

## Arquitetura

Desenho oficial: [`docs/arquitetura.md`](docs/arquitetura.md). Briefing: [`docs/Briefing_Projeto_Voo_V4.pdf`](docs/Briefing_Projeto_Voo_V4.pdf).

Fluxo: fontes → Bronze → Silver → Gold (Databricks Free) → dashboard AI/BI **e** export `data/gold/` → API → web.

## Rodar a plataforma local

Pré-requisitos: Python 3.11+, Node 20+, Docker opcional.

```bash
# API
cd apps/api
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Front (outro terminal)
cd apps/web
npm install
npm run dev
```

Ou:

```bash
docker compose up --build
```

- API: http://localhost:8000/docs
- Web: http://localhost:5173
- Brand book: abrir [`branding/vooai-brand-book.html`](branding/vooai-brand-book.html) no navegador

Sem cluster Databricks, a API lê as amostras em [`data/gold/sample`](data/gold/sample). Com Gold real, rode [`scripts/export_gold.py`](scripts/export_gold.py) (ver [`scripts/sync_notebooks.md`](scripts/sync_notebooks.md)).

## Marca

Tokens e regras visuais: [`branding/vooai-brand-book.html`](branding/vooai-brand-book.html). O front não inventa paleta nem fonte fora do book.

## Agentes e skills

Versionados em `.cursor/`. Índice: skill `vooai-orquestracao`. Não usar stacks OCI/Carbon neste repositório.

## Escopo do MVP

- 10–30 rotas nacionais
- Regra inicial ±5% na variação prevista
- Confiabilidade operacional (atraso/cancelamento ANAC)
- Sem dados pessoais

# VooAI

Sinal claro para comprar ou esperar. Cotações ao vivo (Google Flights / SerpAPI) cruzadas com a Spec de risco e preço materializada em parquet.

## Monorepo

| Pasta | Função |
|-------|--------|
| [`apps/api`](apps/api) | FastAPI — SerpAPI + Spec parquet |
| [`apps/web`](apps/web) | React + Vite — busca e resultado |
| [`branding`](branding) | Brand book HTML |
| [`data`](data) | `SoR` / `SoT` / `Spec` (gitignore) |
| [`notebooks`](notebooks) | `08` ETL · `09` modelagem · `10` simulador |
| [`docs`](docs) | Briefing, arquitetura, [deploy acadêmico](docs/deploy-academico.md) |

## Fluxo

SoR → SoT → Spec (notebooks) → API (`/search`) junta Google Flights + `spec_modelos_risco` → web.

## Rodar local

Pré-requisitos: `SERPAPI_API_KEY`, pastas `data/SoT` (aeroportos) e `data/Spec` (parquet Gold). Detalhe e deploy na box FourDev/SDR: [`docs/deploy-academico.md`](docs/deploy-academico.md).

```bash
# API
cd apps/api
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # preencher SERPAPI_API_KEY
uvicorn app.main:app --reload --port 8000

# Front
cd apps/web
npm install
npm run dev
```

Atalho macOS: `open scripts/dev-up.command` · Compose: `docker compose up --build`

- API: http://localhost:8000/docs
- Web: http://localhost:5173

Janela da Spec: `GET /health` (`gold_date_min` / `gold_date_max`). MVP atual = malha doméstica BR; internacional documentado na seção 5 do runbook.

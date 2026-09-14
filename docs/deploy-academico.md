# Deploy acadêmico VooAI

Runbook para o MVP da disciplina: app de ponta a ponta (busca → SerpAPI → Spec → UI), deploy curto prazo na infra FourDev/SDR **sem Postgres**, e requisitos para voos **internacionais**.

| | |
|--|--|
| API | FastAPI `:8000` |
| Web | Vite `:5173` |
| Dados runtime | parquet em `data/SoT` + `data/Spec` |
| Lakehouse | Databricks Free (fora da box) |

Endpoints reais: `GET /health`, `/airports`, `/search` (alias `/quotes/search`), `/flights/detail`, `/reliability`, `/dashboard` (`/dashboard/summary`), `/models/metrics`.

---

## 1. Objetivo e escopo

### 1.1 Objetivo

- Rodar o monorepo para **aceite acadêmico / demo**.
- Reutilizar a box AWS do SDR (ECS + ALB + rede), isolando o VooAI como serviços próprios + volume de parquet.
- Deixar explícito o que é **doméstico BR hoje** e o que falta para **internacional 100%**.

### 1.2 Dentro do escopo acadêmico

- Containers (ou processos) `api` + `web`.
- Volume com `SoT_aeroportos` + Spec Gold.
- Segredo `SERPAPI_API_KEY`; envs `VOOAI_DATA_DIR` / `VOOAI_SPEC_DIR`.
- Demo em rotas domésticas (ex.: GRU↔GIG, SSA, BSB) dentro da janela `gold_date_*`.

### 1.3 Fora de escopo (neste horizonte)

- Produção SaaS (auth, multi-tenant, SLA, DR).
- Migrar Spec → Postgres / schemas `sdr` / `crm`.
- HostGator / shared hosting PHP.
- API falando com Databricks em runtime (só consome export em disco).

### 1.4 Decisão de dados (fechada)

Runtime = **Polars + parquet**. Compose de referência:

```yaml
# docker-compose.yml (resumo)
volumes:
  - ./data:/data:ro
environment:
  VOOAI_DATA_DIR: /data
  VOOAI_SPEC_DIR: /data/Spec
```

Se a API gravar consultas em `Spec/spec_resultados/`, o mount da Spec na box precisa ser **rw** (o compose local usa `:ro`).

---

## 2. Checklist “roda 100%” local

### 2.1 Pré-requisitos

- Python **3.12+**, Node **20+**
- Chave SerpAPI válida (free ~**250** buscas/mês — planejar a demo)
- Árvore `data/` populada (seção 4)

### 2.2 Dados mínimos (bloqueantes)

| Path | Uso |
|------|-----|
| `data/SoT/SoT_aeroportos/aeroportos_*.parquet` | `/airports` + resolução de origem/destino (~346 IATAs BR no snapshot atual) |
| `data/Spec/spec_modelos_risco/spec_modelos_risco_*.parquet` | Gold risco/preço (~40 MB) |
| `data/Spec/spec_companhias/historico_companhias_*.parquet` | Confiabilidade / ranking (recomendado) |
| `data/Spec/spec_metricas_modelos/metricas_*.parquet` | `/models/metrics` (opcional) |

Sem Spec/SoT: `/search` e `/airports` → **503**; `/health` ainda responde, mas `gold_file` / datas podem vir nulos.

### 2.3 API

```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # preencher SERPAPI_API_KEY
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- Docs: http://127.0.0.1:8000/docs  
- CORS no MVP: `allow_origins=["*"]` (`main.py`)

`.env.example`:

```text
SERPAPI_API_KEY=
VOOAI_SPEC_DIR=../../data/Spec
VOOAI_DATA_DIR=../../data
```

### 2.4 Web

```bash
cd apps/web
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

- UI: http://127.0.0.1:5173  
- Base da API: `VITE_API_URL` (default `http://127.0.0.1:8000` em `src/api.js`)

### 2.5 Atalho macOS

```bash
open scripts/dev-up.command
```

Abre Terminal.app com API + Vite. Exige `.venv` e `node_modules` já instalados, e `apps/api/.env` com a chave.

### 2.6 Docker Compose

```bash
export SERPAPI_API_KEY=...
docker compose up --build
```

- `api`: `:8000`, healthcheck em `/health`
- `web`: `:5173`, `depends_on` api healthy

**Atenção remoto:** `VITE_API_URL=http://localhost:8000` só serve no browser da mesma máquina. Na box use a URL pública da API.

### 2.7 Smoke test

1. `GET /health` → `status=ok`, `serpapi_configured=true`, `gold_file` + `gold_date_min` / `gold_date_max` preenchidos  
2. `GET /airports?q=sao` → hits BR  
3. `GET /search?origin=GRU&dest=GIG&date=YYYY-MM-DD` com data **dentro** da janela Spec → ofertas  
4. Front Home → Resultado sem erro de rede  

### 2.8 Falhas comuns

| Sintoma | Causa típica |
|---------|----------------|
| `serpapi_configured: false` | env sem `SERPAPI_API_KEY` |
| 400 “fora do período materializado na Spec” | data fora de `gold_date_*` |
| 400 “fora da malha doméstica BR” | IATA/cidade ausente em `SoT_aeroportos` |
| 502 / RuntimeError SerpAPI | chave, cota ou erro HTTP |
| 503 FileNotFoundError | Spec/SoT no path errado |
| Front sem dados | `VITE_API_URL` ou API down |

---

## 3. Deploy curto prazo na box FourDev / SDR

### 3.1 Princípio

Compartilhar **orquestração e rede** (ECS + ALB + VPC). VooAI = dois serviços + volume de arquivos — **não** um schema no Postgres do SDR.

### 3.2 Serviços (modelo ECS — referência)

Para a box atual (EC2 + Caddy), use o script [`scripts/deploy-box.sh`](../scripts/deploy-box.sh): imagens `vooai-api` / `vooai-web` na rede `sdr-box_default`, Caddy em `vooai.magnasoluto.com.br` com `/api/*` → API e resto → SPA.

**`vooai-api`**

- Imagem: `deploy/box/Dockerfile.api`
- Porta interna: `8000`
- Env: `SERPAPI_API_KEY` em `/opt/vooai/api.env`, `VOOAI_DATA_DIR=/data`, `VOOAI_SPEC_DIR=/data/Spec`
- Mount: `/opt/vooai/data` → `/data`
- Health: `GET /health` (via `https://vooai.magnasoluto.com.br/api/health`)

**`vooai-web`**

- Imagem: `deploy/box/Dockerfile.web` (nginx + `npm run build`)
- Build-arg: `VITE_API_URL=https://vooai.magnasoluto.com.br/api`

**Caddy (já na box SDR)**

- Host: `vooai.magnasoluto.com.br` (DNS Magnasoluto → EIP `44.223.137.178`)
- `handle_path /api/*` → `vooai-api:8000`
- demais paths → `vooai-web:80`

### 3.3 Secrets

- `SERPAPI_API_KEY` só em secret store — nunca no git  
- Template: `apps/api/.env.example`

### 3.4 Volume de dados na box

Copiar (rsync / artifact CI) no mínimo:

- `SoT/SoT_aeroportos/*.parquet`
- `Spec/spec_modelos_risco/*.parquet`
- demais Spec usadas se a demo incluir Dashboard / Reliability

Ordem de tamanho: Spec risco ~**40 MB**; SoT aeroportos é leve. `SoT_tarifas` / histórico bruto **não** são necessários no runtime da API.

### 3.5 O que não fazer

- Criar tabelas VooAI no Postgres EC2 (`sdr` / `crm`) neste horizonte  
- Migrar Spec para SQL só para “ficar igual ao SDR”  
- Subir no HostGator / cPanel  
- Expor token Databricks na task da API  
- Deixar `VITE_API_URL=http://localhost:8000` no deploy remoto  

### 3.6 Paridade local ↔ box

| Aspecto | Local | Box |
|---------|-------|-----|
| Código | git | imagem ECS do mesmo git |
| Dados | `./data` | volume `/data` |
| Spec | parquet | parquet |
| Segredo | `.env` | AWS secret → env |
| Prontidão | `curl /health` | ALB + `/health` |

---

## 4. Dados: layout, export, gitignore

### 4.1 Layout (`data/README.md`)

| Pasta | Papel | API lê? |
|-------|--------|---------|
| `data/SoR/` | Bronze ANAC | Não |
| `data/SoT/` | Silver | Sim — aeroportos |
| `data/Spec/` | Gold | Sim — risco, cias, métricas, resultados |

Resolução de pastas: `apps/api/app/paths.py` (`latest_glob` = arquivo mais recente do padrão).

### 4.2 Renovar Spec

1. Notebooks: `08_etl_…` → `09_modelagem_risco` → (ref.) `10_simulador_voos`  
2. Sync: [`scripts/sync_notebooks.md`](../scripts/sync_notebooks.md)  
3. Copiar parquet para `data/Spec` (e aeroportos em `data/SoT` se mudou)  
4. **Restart** da API (`@lru_cache` em paths/dims)  
5. Conferir novos `gold_file` / `gold_date_*` em `/health`

### 4.3 Gitignore

`data/SoR/*`, `data/SoT/*`, `data/Spec/*` — exceções: `.gitkeep` e `data/README.md`.  
Não versionar parquet nem `.env` com chave.

### 4.4 Por que não Postgres agora

Zero migração de schema, zero acoplamento ao Postgres do SDR, mesmo artefato que o lakehouse já materializa. Renovação = copiar arquivos.

---

## 5. Doméstico hoje × internacional 100%

### 5.1 Estado atual (doméstico BR)

- **Autocomplete / resolução:** só `SoT_aeroportos` (malha BR / serviço regular; `pais=BR`).
- IATA de 3 letras fora da dimensão → erro **antes** da SerpAPI:

  > `Aeroporto '…' fora da malha doméstica BR. Use cidade ou IATA brasileiro.`

  (`resolver_local_para_iatas` em `spec_store.py`)

- **Spec de risco:** VRA/ANAC → municípios e cias domésticas; dashboard = malha doméstica.
- **Janela:** `date` ∈ `[gold_date_min, gold_date_max]`.
- **SerpAPI** (`gflights.py`): `currency=BRL`, `hl=pt-br`, `gl=br` — o motor Google Flights **aceita IATA mundial**; o gargalo é a dim BR + Spec ANAC.
- **Deep links:** Google Flights estável; cias BR (Gol desligado por instabilidade do B2C); internacionais que operam no BR = mapa parcial + fallback.

### 5.2 O que já é “mundial” na prática

| Camada | Internacional hoje |
|--------|--------------------|
| SerpAPI Google Flights | Sim, **se** receber IATA válido |
| UI / `/airports` / resolver | Não (só BR) |
| Join Spec risco/preço | Só doméstico; senão `status_match_gold=sem_match_exato` e scores nulos (**depois** de cotar) |
| Deep link cia | Parcial |
| Cota SerpAPI | ~250/mês — `flex_dates` e ida-volta multiplicam requests |

### 5.3 Requisitos para internacional 100%

1. **Dimensão mundial de aeroportos** em `SoT_aeroportos` (OurAirports / OpenFlights / similar): IATA, cidade, país, nome.  
2. **Suavizar `resolver_local_para_iatas`:** aceitar IATA presente na dim mundial; mensagem clara se desconhecido; opcional pass-through de IATA ISO sem linha Spec.  
3. **Degradação graceful de produto:** trecho internacional = preço/horários SerpAPI **sem** scores ANAC; copy do tipo “confiabilidade operacional disponível para malha doméstica BR”.  
4. **Modelo de preço Spec** permanece BR até haver features globais (fora do curto prazo).  
5. **Params SerpAPI:** manter BRL/`gl=br` ok para persona BR voando ao exterior; parametrizar mercado só se a UI exigir.  
6. **Deep links:** expandir mapa de cias; manter fallback Google Flights.  
7. **Cota:** plano pago ou cache; medir requests com `flex_dates` + ida-volta (até 3 chamadas por âncora).  
8. **Aceite internacional:** GRU→LIS / GRU→MIA; `/airports` resolve; `/search` retorna preço; UI sem crash sem histórico ANAC.

### 5.4 Não prometer na banca deste MVP

- Spec mundial equivalente à ANAC  
- Modelo de preço internacional com a mesma profundidade do doméstico  
- Multi-moeda além de BRL na UI  

### 5.5 Critério “roda 100%” neste documento

**Health verde + search doméstico com ofertas + front renderizando**, com Spec/SoT no volume e SerpAPI válida.  
Internacional 100% = **fase documentada** (esta seção), não bloqueante do aceite doméstico.

---

## 6. Operação contínua

### 6.1 Spec

Pipeline notebooks → copiar parquet → restart API → validar `/health`.

### 6.2 SerpAPI

- Free ~250/mês  
- Ida = 1 request; ida-volta com combo pode ser até **3**; flex multiplica  
- Antes da banca: conferir painel SerpAPI  

### 6.3 Health

Interpretar campos (`serpapi_configured`, `gold_date_*`), não só HTTP 200.  
Front: `getHealth()` (página Sobre).

### 6.4 CORS

Dev/`*`: ok. Box com hosts separados: `*` ainda funciona; endurecer listando a origem do front se a política FourDev exigir.

### 6.5 Observabilidade mínima

Logs stdout da task uvicorn. Não misturar com pipelines SDR. Contar mentalmente chamadas SerpAPI no dia da demo.

---

## 7. Checklist de demo / aceite

### 7.1 Ambiente

- [ ] `data/SoT` + `data/Spec` presentes  
- [ ] `SERPAPI_API_KEY` + cota ok  
- [ ] API e web no ar (local ou ALB)  
- [ ] `/health`: `serpapi_configured=true`, datas Spec preenchidas  

### 7.2 Caminho feliz (doméstico)

- [ ] Autocomplete (ex. São Paulo → GRU/CGH/VCP)  
- [ ] Busca ida na janela Spec → preços BRL  
- [ ] Match Spec: scores/ação; sem match: UI tolera `sem_match_exato`  
- [ ] Ida-volta (se na demo)  
- [ ] Deep link compra sem crash  
- [ ] Dashboard/Sobre com janela Spec  

### 7.3 Negativos esperados (mostrar domínio)

- [ ] IATA internacional (ex. `LIS`) → mensagem malha doméstica BR (**comportamento atual**)  
- [ ] Data fora da Spec → 400 com período  
- [ ] Sem SerpAPI → health false / search falha de forma clara  

### 7.4 Narrativa (30–60 s)

1. Databricks Free materializa Spec parquet (ANAC + modelos).  
2. API não usa Postgres do SDR: lê Spec/SoT e cota Google Flights via SerpAPI.  
3. Deploy acadêmico na mesma box ECS/ALB do FourDev/SDR, isolado do CRM.  
4. Internacional: motor de cotação já é mundial; falta dim de aeroportos + UX de degradação ANAC-only.

---

## Apêndice A — Variáveis de ambiente

| Variável | Onde | Função |
|----------|------|--------|
| `SERPAPI_API_KEY` | API | Cotação Google Flights |
| `VOOAI_DATA_DIR` | API | Raiz `data/` (Docker: `/data`) |
| `VOOAI_SPEC_DIR` | API | Pasta Spec |
| `VOOAI_GOLD_DIR` | API | Alias legado de Spec |
| `VITE_API_URL` | Web | Base URL da API no browser |

## Apêndice B — Arquivos de referência

| Path | Papel |
|------|--------|
| [`docker-compose.yml`](../docker-compose.yml) | api + web + volume dados |
| [`apps/api/app/main.py`](../apps/api/app/main.py) | rotas e CORS |
| [`apps/api/app/spec_store.py`](../apps/api/app/spec_store.py) | parquet + resolver doméstico |
| [`apps/api/app/gflights.py`](../apps/api/app/gflights.py) | cliente SerpAPI |
| [`apps/api/app/paths.py`](../apps/api/app/paths.py) | pastas |
| [`scripts/dev-up.command`](../scripts/dev-up.command) | subida local macOS |
| [`scripts/sync_notebooks.md`](../scripts/sync_notebooks.md) | Databricks → disco |
| [`docs/arquitetura.md`](arquitetura.md) | visão lakehouse |
| [`docs/rotas-mvp.md`](rotas-mvp.md) | rotas domésticas do MVP |
| [`data/README.md`](../data/README.md) | política de pastas |

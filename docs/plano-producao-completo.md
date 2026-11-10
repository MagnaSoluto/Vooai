# VooAI — Plano completo: dados dinâmicos, monetização e produção

Documento de esboço do produto pós-MVP acadêmico. Complementa [`arquitetura.md`](arquitetura.md) e [`deploy-academico.md`](deploy-academico.md).  
**Não substitui** o lakehouse acadêmico: evolui o monorepo de “Spec congelada + busca viva” para **fábrica contínua + produto pago + escala**.

---

## 1. Visão em uma frase

O VooAI passa a ser um produto em que **(1)** a ciência de dados roda em cadências realistas por fonte, **(2)** o usuário paga créditos por busca viva, **(3)** Ads cobrem margem residual, e **(4)** a infra aguenta milhares de hits de UI com cotação viva sob cache, fila e backpressure.

---

## 2. Princípios (não negociar)

| # | Princípio |
|---|-----------|
| 1 | **Cadências separadas** — ANAC ≠ série de preços ≠ Spec ≠ cotação viva do `/search`. |
| 2 | **API não treina** — batch na box materializa; serving só lê Spec + chama SerpAPI. |
| 3 | **Preço = custo SerpAPI** — carteira debita por crédito consumido (com piso por tipo). |
| 4 | **Degradação honesta** — sem Spec match ou sem saldo → mensagem clara, sem inventar score. |
| 5 | **Git = contrato** — collectors, notebooks, schemas e jobs versionados; dumps grandes fora do Git. |
| 6 | **Barato por padrão** — sem Glue, sem Kafka, sem EMR. Cron + Polars + Redis na mesma EC2. |

### 2.1 Decisão de orquestração (custo)

| Opção | Usar? | Motivo |
|-------|-------|--------|
| AWS Glue / EMR / MWAA | **Não** | Volume ~9 GB mensal + cotações leves — custo fixo alto demais. |
| ETL pela API de produto (`/search`) | **Não** | Mistura serving, gasta cota/carteira, timeout. |
| **Cron + `pipelines/*` na box** | **Sim** | Mesma EC2; custo ≈ disco + SerpAPI. |
| Redis | **Sim** | Cache de cotação; fila leve depois (RQ) — não Kafka. |
| Databricks Free | Opcional | Treino pesado 08/09; não no request path. |
| nbconvert 08/09 na box | Mensal | Só quando VRA novo e RAM ok (`pipelines/run_heavy_etl.sh`). |

Código: [`pipelines/README.md`](../pipelines/README.md).

---

## 3. Arquitetura-alvo (ponta a ponta)

```text
┌─────────────────────────────────────────────────────────────────────────┐
│ FONTES                                                                   │
│  ANAC (VRA/tarifas/microdados)     SerpAPI Google Flights                │
└──────────────┬──────────────────────────────┬────────────────────────────┘
               │                              │
               ▼                              ▼
┌──────────────────────────┐    ┌─────────────────────────────────────────┐
│ JOB ANAC (semanal/mensal)│    │ JOB COLLECTOR (1–2×/dia, rotas MVP)     │
│ download → SoR           │    │ quotes → SoR_cotacoes                   │
└──────────────┬───────────┘    └──────────────────┬──────────────────────┘
               │                                   │
               └─────────────┬─────────────────────┘
                             ▼
               ┌─────────────────────────────┐
               │ JOB ETL 08 → SoT (Silver)    │
               │ JOB ML  09 → Spec (Gold)     │  diário ou pós-ANAC
               │ PUBLISH Spec → volume/S3     │
               │ RELOAD API (invalidate Spec) │
               └──────────────┬──────────────┘
                              │
┌─────────────────────────────┴───────────────────────────────────────────┐
│ SERVING — box AWS (Caddy + Docker)                                       │
│  Caddy → Web (React) + /api/* → FastAPI                                  │
│       ├─ Redis (OBRIGATÓRIO):                                            │
│       │    • cache de cotação TTL 20 min (mesmo trecho = mesmo resultado)│
│       │    • rate limit / sessão                                         │
│       │    • fila leve futura (RQ/lists) — sem Kafka                     │
│       ├─ Postgres (Fase 0): users, wallets, ledger                       │
│       └─ Spec parquet (volume /data)                                     │
│  AdSense + Mercado Pago                                                  │
└──────────────────────────────────────────────────────────────────────────┘
```

**Sem Kafka.** Na box, Redis cobre cache + (depois) fila barata. Kafka só faria sentido com dezenas de serviços — overkill aqui.

**Separação crítica:** preço ao usuário = **cache Redis + SerpAPI no miss** (minutos). Ciência de dados = **batch SoR→SoT→Spec** (horas/dias/mês).

### 3.1 Cache de cotação (já no código)

| Item | Valor |
|------|--------|
| Env | `VOOAI_QUOTE_CACHE_TTL_SEC` (default **1200** = 20 min) |
| Backend | `REDIS_URL` → Redis; sem Redis → memória (dev) |
| Chave | IATAs canônicos + data ida + volta + flex |
| Hit | **não** chama SerpAPI; `cache_hit=true`; carteira **ainda debita** (margem nossa) |
| Miss | SerpAPI + grava Redis; `pricing.charged=true`, `serpapi_spent=true` |

**Por que 20 minutos:** tarifas no mesmo OD+data costumam ficar estáveis dezenas de minutos; abaixo de ~10 min gasta crédito à toa; acima de ~45–60 min risco de preço stale e sinal COMPRAR errado. Faixa de mercado 15–30 min → default 20.

Endpoints: `GET /health` (redis_ok, ttl), `GET /pricing` (tabela), `/search` retorna `cache_hit` + `pricing`.

---

## 4. Cadências (calendário operacional)

| Job | Trigger | Entrada | Saída | Notas |
|-----|---------|---------|-------|-------|
| **ANAC ingest** | Semanal (poll) + mensal (load) | gov.br / dump | `data/SoR/*` | VRA/tarifas são **mensais**; 30 min é inútil |
| **Collector preços** | 1–2×/dia (ex. 06:00 e 18:00 BRT) | SerpAPI × rotas MVP | `SoR_cotacoes/` | 15 rotas × 1 ida ≈ 15–30 créditos/dia |
| **ETL Silver (08)** | Diário 02:00 **ou** após ANAC novo | SoR | SoT | Incremental quando possível |
| **Gold/Spec (09)** | Após ETL OK (ou semanal) | SoT + quotes | Spec parquet + joblib | Retreino completo ≠ a cada collector |
| **Publish Spec** | Após 09 OK | Spec | S3/volume API + invalidate | Smoke `/health` |
| **Cotação viva** | On-demand `/search` | SerpAPI | Resposta + ledger | **Sempre** debita; cache Redis 20 min só corta custo SerpAPI |
| **Hint Spec** | On-demand (já existe) | Spec mediana ±3d | `nearby_hint` | **Zero** crédito SerpAPI |

### Por que **não** “estudo completo a cada 30 min”

- ANAC não publica a cada 30 min.
- Rematerializar Spec (~1,27 M linhas + treino) a cada 30 min custa compute e **não** melhora o sinal na mesma proporção.
- 15 rotas × 48 slots/dia ≫ cota SerpAPI free e pressiona qualquer plano pago.

**Interpretação correta de “dinâmico”:**  
fábrica **sempre agendada** + Spec **fresca o bastante** (≤ 24–48 h) + preço de mercado **ao vivo na busca** (com cache curto).

### Opção futura “quase tempo real” (só cotação)

Se no futuro quiser poll de 30 min **só nas top N rotas** (ex. 5):

- 5 rotas × 48/dia = 240 créditos/dia → exige plano SerpAPI alto.
- Só faz sentido com receita de carteira já cobrindo o custo.
- **Não** entra no go-live inicial.

---

## 5. Monetização

### 5.1 Carteira (core) — margem mínima **30%**

Custo base: SerpAPI Developer ≈ **R$ 0,08 / crédito** (`VOOAI_SERPAPI_COST_BRL`).  
Fórmula: `preço = ceil_centavos(créditos × custo / (1 − 0,30))`.

| Tipo | Créditos | Custo | Preço (≥30% margem) |
|------|----------|-------|---------------------|
| Ida | 1 | R$ 0,08 | **R$ 0,12** |
| Ida-volta | 3 | R$ 0,24 | **R$ 0,35** |
| Flex ida | 7 | R$ 0,56 | **R$ 0,80** |
| Flex ida-volta | 12 | R$ 0,96 | **R$ 1,38** |
| Recarga mínima | — | — | **R$ 5,00** |

- UX: “Esta busca custa R$ X” (`GET /pricing` + campo `pricing` no `/search`).
- Toda consulta **entregue** debita (`pricing.charged=true`). Cache hit: `serpapi_spent=false` (ganho nosso).
- Estorno **somente** se a API falhar e a busca não for entregue (502 SerpAPI, Spec ausente, validação, erro inesperado).
- Código: `apps/api/app/pricing.py` + débito/estorno em `main._do_search`.

Regra: preço ≥ custo / 0,70 (margem ≥ 30%). Não baixar tabela sem revisar `VOOAI_SERPAPI_COST_BRL`.

### 5.2 AdSense

- Home, Sobre, Resultado (fora do board de sinal).
- Proibido: overlay no COMPRAR/AGUARDAR ou no CTA principal.

### 5.3 Depois (Fase 3+)

- Afiliado cia/OTA no CTA “ver oferta”.
- Plano Pro (assinatura com N buscas/mês).
- B2B white-label.

---

## 5.4 Localmente viável (agora)

```bash
# na raiz do monorepo
docker compose up -d redis   # ou compose completo
# API local:
export REDIS_URL=redis://127.0.0.1:6379/0
export VOOAI_QUOTE_CACHE_TTL_SEC=1200
cd apps/api && uvicorn app.main:app --reload --port 8000
```

Sem Redis: a API cai para **cache em memória** (ok para dev single-process).  
Box: `deploy/box/docker-compose.yml` sobe `vooai-redis` + API com `REDIS_URL`.

---

## 6. Fases de entrega

### Fase −1 — Fábrica de dados dinâmica *(pré-requisito de produto vivo)*

**Objetivo:** SoR→SoT→Spec deixa de ser “rodamos na banca” e passa a ter jobs.

| # | Entrega | Done when |
|---|---------|-----------|
| −1.1 | `pipelines.collect_quotes` → `SoR_cotacoes/` | **FEITO** |
| −1.2 | `pipelines.ingest_anac_vra` | **FEITO** (poll + download mês faltante) |
| −1.3 | `pipelines.run_nightly` + `crontab.example` | **FEITO** (cron na box) |
| −1.4 | `pipelines.publish_spec` | **FEITO** |
| −1.5 | `POST /admin/reload-spec` | **FEITO** |
| −1.6 | `pipelines/README.md` + §2.1 deste plano | **FEITO** |
| −1.7 | `etl_quotes` SoR→SoT→Spec cotacoes | **FEITO** (leve, diário) |
| −1.8 | Heavy 08/09 via `run_heavy_etl.sh` | **FEITO** (mensal / opcional) |

**Fora de escopo −1:** carteira, Ads, multi-réplica.

---

### Fase 0 — Monetização mínima *(go-live comercial)*

| # | Entrega | Done when |
|---|---------|-----------|
| 0.1 | Auth (register/login + Bearer token) | **FEITO** (SQLite; magic link depois) |
| 0.2 | Postgres `vooai` (SQLite só fallback) | **FEITO** — `VOOAI_DATABASE_URL` + `pipelines/init_postgres_vooai.sh` |
| 0.3 | Recarga stub mín. R$ 5 | **FEITO** (`POST /wallet/topup`); PIX depois |
| 0.4 | Débito pré-SerpAPI + estorno 502 | **FEITO** |
| 0.5 | Cache Redis cotação | **FEITO** — TTL 20 min |
| 0.6 | Rate limit Redis/memória | **FEITO** |
| 0.7 | AdSense no front | **FEITO** (env opcional; Método/Conta) |
| 0.8 | Front auth/carteira/custo busca | **FEITO** (`/conta`, Nav, Home, Results) |
| 0.9 | SerpAPI plano pago + alerta 80% cota | ops no go-live |
| 0.10 | PIX via **Billing API FourDev** (não Asaas direto) | **FEITO** — ver [`billing-fourdev.md`](billing-fourdev.md) |

Doc local: [`fase-0-billing-local.md`](fase-0-billing-local.md).

**Política de cache × cobrança:** toda consulta debita; cache hit só evita gasto SerpAPI (margem nossa).
---

### Fase 1 — Sobreviver a tráfego real

| # | Entrega |
|---|---------|
| 1.1 | Fila + workers SerpAPI (concorrência fixa, ex. 20–50) |
| 1.2 | API em 2+ réplicas (ECS/Fargate ou ASG) + ALB |
| 1.3 | Spec em S3/EFS; Redis compartilhado |
| 1.4 | CDN (CloudFront) no front |
| 1.5 | Métricas: créditos/dia, margem, p95 `/search`, taxa 402/502 |
| 1.6 | Circuit breaker: fila cheia → “tente em 30s” ou modo “só Spec histórico” |

---

### Fase 2 — Milhares de requisições (hits) em paralelo

| # | Entrega |
|---|---------|
| 2.1 | Autoscaling API por CPU/RPS |
| 2.2 | Read replicas Postgres se ledger pesar |
| 2.3 | Soft cap flex no plano free da carteira |
| 2.4 | Fraud basics (device, velocity, bloqueio scraper) |
| 2.5 | Status page + alertas Slack/e-mail |

“Milhares ao mesmo tempo” = principalmente **UI + Spec + cache**. Cotação viva permanece **limitada** pela fila SerpAPI e pelo preço.

---

### Fase 3 — Produto maduro

| # | Entrega |
|---|---------|
| 3.1 | Afiliados / deep link cia |
| 3.2 | Plano Pro mensal |
| 3.3 | Internacional (cotação ok; Spec risco = roadmap ANAC/outro) |
| 3.4 | Feature store / retreino automático com drift monitoring |

---

## 7. Modelo de dados (serving) — novo

```text
users          id, email, provider, created_at
wallets        user_id, balance_brl, updated_at
ledger         id, user_id, kind(credit|debit|refund), amount, reason, search_id?, mp_payment_id?
searches       id, user_id, origin, dest, date, trip_type, flex, credits_used, price_charged, cache_hit, status
quotes_cache   key_hash, payload_json, expires_at   (ou só Redis)
```

Spec/SoT continuam em parquet (ou Delta no lakehouse). **Não** migrar Gold inteiro para Postgres no início.

Bronze novo:

```text
data/SoR/SoR_cotacoes/yyyy/mm/dd/route_id=.../*.parquet
  route_id, origin, dest, carrier, collected_at, departure_at,
  lead_days, price_brl, duration_min, stops, trip_type, source=serpapi
```

---

## 8. Orquestração sugerida (mínima e barata)

### Opção recomendada no início

| Ambiente | Ferramenta |
|----------|------------|
| Batch leve (collector, publish) | **cron** na box **ou** GitHub Actions schedule |
| ETL/ML pesado | Databricks Jobs (Free enquanto couber) **ou** container nightly na box |
| Segredos | `SERPAPI_API_KEY`, DB URL, MP tokens — nunca no Git |

### Pseudocron

```text
0 6,18 * * *   collect_quotes.py --routes docs/rotas-mvp.md
0 4 * * 1      ingest_anac.py --poll-only
0 3 2 * *      ingest_anac.py --load-latest   # dia 2 do mês (ajustar)
0 2 * * *      run_etl_08 && run_ml_09 && publish_spec.py
```

Ajustar horários ao fuso e à cota SerpAPI.

---

## 9. Unit economics (guarda-chuva)

```text
margem_busca = preço_cobrado
             − (créditos_serpapi × custo_crédito)
             − (taxa_pagamento amortizada na recarga)
             − (infra / nº buscas do mês)
```

Gates mensais:

1. Margem bruta média das buscas **> 25%**.
2. Cache hit ratio **> 30%** após 2 semanas.
3. Custo SerpAPI **< 60%** da receita de carteira.
4. AdSense = bônus (não entra no break-even mínimo).

---

## 10. Riscos e mitigações

| Risco | Mitigação |
|-------|-----------|
| Cota SerpAPI estoura | Plano pago + alerta + cache + limite flex |
| Preço baixo demais no flex | Tabela §5.1 (não usar R$ 0,15–0,20 em RT/flex) |
| Spec stale | Publish diário + `/health` com `gold_date_*` na UI |
| ANAC atrasa mês | Spec continua no último mês; UI avisa janela |
| Abuse de conta free | Recarga mín. R$ 5 + rate limit + KYC leve depois |
| Databricks Free insuficiente | Mover 08/09 para container nightly na box/ECS |

---

## 11. Mapa de pastas (o que nasce)

```text
collectors/
  collect_quotes.py          # −1.1
  ingest_anac.py             # −1.2
  README.md                  # cadências
apps/api/app/
  wallet.py / auth.py        # 0.x
  cache_quotes.py            # 0.5
  admin_reload.py            # −1.5
scripts/
  publish_spec.py            # −1.4
  run_nightly_pipeline.sh    # −1.3
docs/
  plano-producao-completo.md # este arquivo
  arquitetura.md             # atualizar diagrama na −1.6
deploy/
  (compose prod: api, web, redis, worker)
```

---

## 12. Ordem de implementação (checklist executável)

1. [ ] **−1.1** Collector de cotações (rotas MVP → SoR)
2. [ ] **−1.5** Reload Spec na API (desbloqueia publish)
3. [ ] **−1.4** Publish Spec
4. [ ] **−1.2** Ingest ANAC
5. [ ] **−1.3** Cron/Jobs ligando a cadeia
6. [ ] **0.1–0.4** Auth + carteira + débito
7. [ ] **0.5–0.6** Cache + rate limit
8. [ ] **0.7–0.8** AdSense + SerpAPI pago
9. [ ] **1.x** Fila, réplicas, CDN
10. [ ] **2.x / 3.x** Escala e receita adjacente

---

## 13. Definição de “projeto completo” (aceite)

O VooAI está “completo” no sentido de produto quando:

1. ANAC e cotações entram SoR **sem mão na massa** (jobs).
2. Spec republica **automaticamente** e a API recarrega sem restart gambiarra.
3. Usuário cria conta, carrega **≥ R$ 5**, busca e vê COMPRAR/AGUARDAR/MONITORAR.
4. Cada busca viva tem custo transparente e ledger auditável.
5. Ads não atrapalham o sinal.
6. Sob pico, a UI responde; a cotação viva enfileira ou degrada com mensagem clara — **sem** derrubar a box.

Até lá, o monorepo continua excelente como **case acadêmico**; este plano é a ponte para **negócio**.

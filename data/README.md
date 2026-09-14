# Dados locais e no Git

| Pasta | Papel | No Git? |
|-------|--------|---------|
| `SoR/` | Bronze — fontes ANAC brutas | Não (~GB). Só `.gitkeep` |
| `SoT/` | Silver — tarifas/histórico | Não (bruto). **Exceção:** `SoT_aeroportos/*.parquet` |
| `Spec/` | Gold — risco, preço, KPIs, modelos | **Sim** (parquet + joblib). Exclui `spec_resultados/` |
| `bronze/Microdados` | Marcador do grupo (Santina) | Sim (placeholder) |

## Spec versionada (obrigatória para rodar a API)

Após `git clone` + `SERPAPI_API_KEY`, a API precisa de:

| Path | Uso |
|------|-----|
| `data/Spec/spec_modelos_risco/spec_modelos_risco_*.parquet` | Scores / recomendação (~40 MB) |
| `data/Spec/spec_companhias/` | Ranking de cias |
| `data/Spec/spec_atrasos/`, `spec_origens_destinos/`, `spec_datas/` | Dashboard / detalhe |
| `data/Spec/spec_metricas_modelos/` | `/models/metrics` |
| `data/Spec/spec_modelos/*.joblib` | Artefatos de treino (referência) |
| `data/SoT/SoT_aeroportos/aeroportos_*.parquet` | Autocomplete `/airports` |

**Não** versionar: `data/Spec/spec_resultados/` (consultas SerpAPI gravadas em runtime), `data/SoR/*` (volume grande), restante de `data/SoT/*`.

Renovar Spec: notebooks `08`/`09` → copiar parquet para `data/Spec/` → `git add` → commit. Detalhe operacional: [`docs/deploy-academico.md`](../docs/deploy-academico.md).

Malha atual = doméstica BR; internacional: seção 5 do runbook de deploy.

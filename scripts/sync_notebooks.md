# Como sincronizar notebooks com o Databricks Free

O Git continua sendo a fonte de verdade. O workspace Free só executa.

## Importar

1. No Databricks Free, workspace → Import.
2. Envie os `.ipynb` de `notebooks/` (um a um ou pasta zip).
3. Repos Git nativos no Free são limitados: se não houver integração, repetir o import a cada entrega relevante.
4. Ajuste o catálogo/schema no primeiro notebook (`vooai.bronze` / `silver` / `gold` ou o equivalente disponível no Free).

## Convenção de nomes

| Arquivo no git | Papel |
|----------------|-------|
| `ingestao-anac.ipynb` | Protótipo atual de download ANAC |
| `01_ingestao_anac.ipynb` | Ingestão VRA/SoR → Bronze |
| `02_ingestao_cotacoes.ipynb` | Cotações → Bronze |
| `03_bronze_silver.ipynb` | Limpeza e features |
| `04_eda.ipynb` | EDA |
| `05_ml_regressao.ipynb` | Regressão + MLflow |
| `06_ml_series.ipynb` | Séries temporais |
| `07_gold_recomendacao.ipynb` | Regra ±5% e tabelas Gold |

## Exportar Gold para a API

Ver [`export_gold.py`](export_gold.py). No MVP, baixar CSVs das tabelas Gold e colocar em `data/gold/` **ou** copiar as amostras de `data/gold/sample/`.

## Segredos

Não commitar tokens. Se o Free exigir PAT para SQL warehouse, usar `.env` local (já no `.gitignore`).

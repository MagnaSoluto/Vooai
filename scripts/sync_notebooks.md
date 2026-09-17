# Sync notebooks ↔ Databricks Free

Notebooks canônicos:

1. `08_etl_tabelas_sor_sot_spec.ipynb` — SoR → SoT / Spec agregados
2. `09_modelagem_risco.ipynb` — treino + `spec_modelos_risco_*.parquet`
3. `10_simulador_voos.ipynb` — SerpAPI + join Spec (referência da API)

A API local não exporta CSV: lê `data/Spec/spec_modelos_risco/*.parquet` e `data/SoT/SoT_aeroportos/*.parquet`.

4. `11_artigo_vooai_dado_em_valor.ipynb` — artigo TCC/Databricks (dado → valor + métricas)

Import no Free: Workspace → Import → este `.ipynb` (ou clone do Git + Upload).
Fonte markdown: `docs/apresentacao/artigo-databricks-vooai.md`.

# Dados locais (não versionados)

| Pasta | Papel |
|-------|--------|
| `SoR/` | Bronze — fontes ANAC |
| `SoT/` | Silver — aeroportos, histórico, tarifas parquet |
| `Spec/` | Gold — `spec_modelos_risco`, métricas, consultas |
| `bronze/Microdados` | Marcador do grupo (Santina); runtime usa `SoR/` |

Tudo sob `data/SoR|SoT|Spec` fica no `.gitignore`. A API lê `Spec/spec_modelos_risco/*.parquet` e `SoT/SoT_aeroportos/*.parquet`, e grava consultas em `Spec/spec_resultados/consultas_google_flights/`.

Checklist de dados para demo / box: [`docs/deploy-academico.md`](../docs/deploy-academico.md) (seções 2 e 4). Aeroportos atuais = malha doméstica BR; internacional exige expandir `SoT_aeroportos` (seção 5 do mesmo doc).

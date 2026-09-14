# Dicionário de dados (MVP)

Tipos e nomes alinhados às tabelas Spec (Gold produto) exportadas em `data/Spec/`. Evoluir após EDA.

## gold.routes

| Campo | Tipo | Fonte | Descrição |
|-------|------|-------|-----------|
| route_id | string | derivado | `{origin}_{dest}` maiúsculo, ex. `GRU_SSA` |
| origin | string | cotação / ANAC | Código IATA origem |
| destination | string | cotação / ANAC | Código IATA destino |
| origin_city | string | SoR municípios | Cidade origem |
| destination_city | string | SoR municípios | Cidade destino |
| active_mvp | boolean | escopo | Rota no conjunto 10–30 |

## gold.quotes

| Campo | Tipo | Fonte | Descrição |
|-------|------|-------|-----------|
| quote_id | string | collector | Identificador da cotação |
| route_id | string | derivado | Rota |
| airline_iata | string | cotação | Companhia |
| collected_at | datetime ISO | collector | Momento da coleta |
| departure_at | datetime ISO | cotação | Partida prevista |
| lead_days | int | derivado | Antecedência (dias) |
| price_brl | float | cotação | Tarifa observada |
| duration_min | int | cotação | Duração total |
| stops | int | cotação | Escalas |

## gold.recommendations

| Campo | Tipo | Fonte | Descrição |
|-------|------|-------|-----------|
| route_id | string | Gold | Rota |
| current_price_brl | float | última cotação | Preço atual de referência |
| hist_avg_brl | float | histórico | Média na janela de antecedência |
| predicted_change_pct | float | ML | Variação esperada (fração, ex. 0.07 = +7%) |
| action | enum | regra ±5% | `COMPRAR` / `AGUARDAR` / `MONITORAR` |
| model_confidence | float | ML | 0–1 |
| as_of | datetime ISO | job Gold | Data da recomendação |

## gold.reliability

| Campo | Tipo | Fonte | Descrição |
|-------|------|-------|-----------|
| airline_iata | string | ANAC VRA | Companhia |
| route_id | string nullable | ANAC | Rota; vazio = ranking nacional da cia |
| delay_rate | float | VRA | Fração de atrasos |
| cancel_rate | float | VRA | Fração de cancelamentos |
| reliability_rank | int | derivado | 1 = mais confiável no recorte |
| sample_flights | int | VRA | N do indicador |

## gold.model_metrics

| Campo | Tipo | Fonte | Descrição |
|-------|------|-------|-----------|
| model_name | string | MLflow | Nome do experimento |
| family | enum | ML | `regression` / `timeseries` |
| mae | float | validação | Erro absoluto médio (BRL ou pp, documentar no run) |
| rmse | float | validação | RMSE |
| r2 | float nullable | regressão | Complementar |
| trained_at | datetime ISO | MLflow | Treino |

## Tratamentos Silver (resumo)

- IATA em maiúsculas, 3 letras.
- Preço > 0; lead_days ≥ 0.
- Deduplicar cotação por rota + cia + collected_at + departure_at.
- VRA: mapear situação de voo para atraso/cancelamento conforme dicionário ANAC do ano vigente.

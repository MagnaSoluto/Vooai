> **TL;DR** — O **VooAI** não começa na tela de busca e não termina no gráfico. É um fluxo completo de engenharia de dados: **origem (ANAC VRA + cotações)** → **SoR (~9 GB brutos)** → **SoT (limpeza, IATA, features)** → **Spec / Gold (~1,27 M linhas de risco + modelos)** → **regra de negócio ±5%** → **produto (COMPRAR / AGUARDAR / MONITORAR)**. Este artigo — trabalho de conclusão do MBA em Engenharia de Dados, em colaboração com o grupo VooAI — percorre **cada camada**, as métricas reais (MAE, RMSE, ROC-AUC, prevalência) e o que isso ensina sobre transformar dado em valor (e em negócio): sem contrato na Spec, pipeline é só custo.

Você já viu a versão rasa do case de dados.

Alguém monta um dashboard, cola um scrape de preço, mostra um card verde e chama de “data-driven”. Falta o que importa: **de onde veio o fato**, **como foi tratado**, **como foi validado no tempo**, **qual decisão ele autoriza** e **o que acontece quando o match falha**.

No DataDriks isso já foi dito em [confiança](/artigos/antes-de-ser-data-driven-a-empresa-precisa-confiar-nos-dados), [pipeline](/artigos/pipeline-de-dados-nao-e-detalhe-tecnico-e-base-da-decisao) e [dashboard ≠ decisão](/artigos/dashboard-nao-e-decisao-o-que-falta-entre-o-grafico-e-a-acao). O VooAI é o case em que o grupo do MBA **fechou o arco**: da microdado ANAC até o sinal na UI.

## 1. A pergunta de negócio (antes de qualquer tabela)

Três perguntas do passageiro — e do produto:

1. Esse preço está **caro ou barato** para esta rota e data?
2. Vale **comprar agora** ou esperar?
3. Qual cia / trecho carrega **pior histórico** de atraso e cancelamento?

Sem essas perguntas, você otimiza storage. Com elas, cada camada do lakehouse tem dono:

| Camada | Pergunta que ela responde |
|--------|---------------------------|
| SoR | O fato bruto existe e é rastreável? |
| SoT | O fato está limpo, joinável e featureizado? |
| Spec | O fato vira score, preço esperado e **ação**? |
| Produto | O usuário recebe o sinal a tempo, com degradação honesta? |

Regra explícita do MVP (calibrável, mas escrita):

- **COMPRAR** se variação prevista de preço ≥ **+5%**
- **AGUARDAR** se ≤ **−5%**
- **MONITORAR** no intervalo (−5%, +5%)

MAE e RMSE sem essa regra são vanity metric com diploma. Com ela, o modelo **ordena o sinal**.

## 2. Origem dos dados — duas fontes, dois regimes

### 2.1 ANAC / VRA — o chão operacional

Base pública de voos regulares (VRA) e tabelas SoR derivadas no monorepo:

| Pasta SoR | Papel |
|-----------|--------|
| `SoR_voos_operacoes` | Operações / situação do voo (atraso, cancelamento, realização) |
| `SoR_origens_destino` | Pares origem–destino |
| `SoR_municipios` | Dimensão de município (join com IATA) |
| `SoR_tarifas_aereas` | Tarifas históricas (quando presentes no recorte) |
| `SoR_microdados` | Microdados auxiliares / marcadores de ingestão |

Ordem de grandeza no ambiente de trabalho do grupo: **~9,2 GB** só em SoR. Isso não é “big data” de marketing — é **volume que obriga disciplina**: não sobe no Git, não entra na API, não vira slide. Sobe para Bronze/SoR, passa por notebook de ETL, e só a Spec enxuta vira contrato de produto.

Pontos de qualidade que a Silver precisa resolver (e o dicionário do projeto documenta):

- IATA em maiúsculas, 3 letras;
- mapear situação de voo ANAC → atraso / cancelamento / realizado conforme o ano vigente;
- município como chave de join (texto normalizado), não só código solto;
- amostragem suficiente antes de publicar `pct_atraso` / `pct_cancelamento` (rota com 1 voo e 100% de atraso é ruído, não KPI).

### 2.2 Cotações ao vivo — o preço que o mercado mostra agora

Segunda fonte: **Google Flights via SerpAPI** (cliente na API do produto / notebook simulador). Regime diferente da ANAC:

- **Atualidade** alta, **histórico** curto;
- custo por chamada (cota mensal) — ida ≈ 1 crédito; ida-volta até ~3; flex de datas multiplica;
- mesma busca repetida **gasta de novo** (não há cache de negócio no MVP);
- moeda/locale fixos no MVP: BRL, `gl=br`, `hl=pt-br`.

A engenharia aqui não é “chamar API”. É **cruzar** preço vivo com Spec histórica **sem mentir** quando não há match.

## 3. SoR → SoT → Spec — o lakehouse como fábrica

Nomes de produto no VooAI (equivalente Bronze / Silver / Gold):

```text
Fontes (ANAC + cotações)
    → SoR  (bruto, sem embelezar)     ~9 GB
    → SoT  (limpo + features)         ~344 MB no recorte local
    → Spec (contrato do produto)      ~1,27 M linhas de risco + métricas + joblib
         ↘ AI/BI (leitura gerencial)
         ↘ export parquet → API → UI
```

Compute de materialização: **Databricks Free** (Delta + notebooks + MLflow). Serving: **API + parquet Spec** — a API **não** treina no request. Separar factory de serving não é gambiarra; é o padrão que evita timeout de Free Edition e protege cota de cotação.

Notebooks canônicos do grupo:

1. **08** — ETL SoR → SoT / agregados Spec  
2. **09** — modelagem de risco + `spec_modelos_risco_*.parquet`  
3. **10** — simulador GFlights + join Spec (referência da API)

### 3.1 SoT — onde o dado vira joinável

Exemplos do que a Silver carrega no MVP:

| Artefato | Conteúdo | Por que importa |
|----------|----------|-----------------|
| `SoT_aeroportos` | ~**346** IATAs BR (`icao`, `iata`, município, nome, país, serviço regular) | Autocomplete e resolução origem/destino — **sem isso a busca nem chega na SerpAPI** |
| `SoT_historico_voos` | Histórico operacional tratado | Base de features de atraso/cancelamento |
| `SoT_tarifas` | Tarifas normalizadas | Features e baselines de preço |

Tratamentos típicos (Silver): nulos, chaves normalizadas de município/companhia, dedupe de cotação por rota + cia + timestamps, preço > 0, `lead_days` ≥ 0.

**Lição:** SoT é o lugar onde você **paga** a dívida de qualidade. Pular Silver e “jogar Bronze no modelo” só escala o erro.

### 3.2 Spec — o contrato (Gold de produto)

A Spec não é “mais uma pasta”. É o **SLA interno** entre ciência de dados e produto. No snapshot do MVP:

**`spec_modelos_risco`** — ~**1.265.997** linhas, **47** colunas, janela de `data_voo` materializada para o produto. Inclui, entre outras:

- chaves: `data_voo`, `municipio_origem`, `municipio_destino`, `nome_empresa`, calendário (`ano`, `n_mes`, `n_dia_semana`…);
- scores: `score_cancelamento`, `score_atraso`, `score_risco_operacional`;
- históricos em três grãos: **empresa**, **rota**, **empresa×rota**, **data** (`hist_*_pct_atraso`, `hist_*_pct_cancelamento`, volumes);
- preço: `preco_estimado_modelo`, `preco_historico_media/mediana/desvio`, `nivel_referencia_preco`.

Outras faces da Spec:

| Artefato | Uso |
|----------|-----|
| `spec_companhias` | Ranking / confiabilidade agregada por cia (ex.: Azul ~1,3 M voos, atraso ~33%; LATAM/TAM ~1,1 M, ~38%; Gol ~0,98 M, ~37%) |
| `spec_atrasos`, `spec_origens_destinos`, `spec_datas` | Séries e KPIs para dashboard / detalhe |
| `spec_metricas_modelos` | MAE, RMSE, AUC — o que a banca e o `/models/metrics` leem |
| `spec_modelos/*.joblib` | Artefatos de treino versionados |
| `spec_resultados/` | Dumps de busca (efêmero — **não** é contrato) |

Spec de produto versionada no Git (~40 MB úteis): clone novo sobe API **sem** arrastar 9 GB de SoR. SoR fica onde deve: lakehouse / disco de trabalho.

## 4. Modelagem — validação temporal e números reais

Snapshot de métricas Spec `2026-09-08`.

### 4.1 Preço — `preco_ridge_temporal`

| Split | MAE (R$) | RMSE (R$) | MAPE | R² |
|-------|----------|-----------|------|-----|
| Validação | **397** | **620** | 33% | 0,27 |
| Teste | **417** | **651** | 34% | 0,24 |

Leitura honesta: em tarifa doméstica volátil, MAE ~R$ 400 **não** “resolve o mercado”. Resolve **ordenar** tendência (sobe / cai / fica) para a regra ±5%. Quem vende R² 0,99 com split temporal sério ou errou o split, ou mediu o problema errado.

### 4.2 Risco — atraso e cancelamento (logística)

| Modelo | Split | ROC-AUC | PR-AUC | Prevalência |
|--------|-------|---------|--------|-------------|
| Cancelamento | teste | **0,68** | 0,06 | ~1,6% |
| Atraso | teste | **0,65** | 0,52 | ~37% |

Cancelamento é **evento raro** — PR-AUC baixo é esperado. Atraso é frequente (~37%). ROC sozinho mente; prevalência + PR-AUC contam a história. Transparência metodológica **é** valor: é o que gera confiança no sinal ([confiança nos dados](/artigos/antes-de-ser-data-driven-a-empresa-precisa-confiar-nos-dados)).

### 4.3 Join Spec × cotação viva

Na busca, a API:

1. resolve origem/destino via `SoT_aeroportos` (malha doméstica BR no MVP);
2. cota SerpAPI;
3. normaliza companhia / município;
4. faz match com Spec na `data_voo` (+ chaves);
5. aplica scores e a regra ±5%;
6. se não houver match: preço vivo permanece; scores ANAC degradam com `sem_match_exato` — **sem inventar confiabilidade**.

Internacional: o motor de cotação aceita IATA mundial; o gargalo atual é a dim BR + Spec ANAC. Produto honesto declara o limite.

## 5. A entrega: produto, não repositório

Se a intenção é **negócio**, a vitrine é a tela — não o monorepo.

![VooAI — busca: origem, destino, data e CTA Ver sinal](/images/vooai/home-busca.png)

A home promete **sinal claro para comprar ou esperar**, não “mais um dashboard”.

![VooAI — board com COMPRAR / AGUARDAR por companhia (São Paulo → Recife)](/images/vooai/board-sinal.png)

No board, Spec vira produto: score por cia, preço a partir de, etiqueta **COMPRAR** ou **AGUARDAR**.

![VooAI — KPIs do resultado: ofertas, menor preço, pontualidade, score](/images/vooai/resultado-kpis.png)

Código e lakehouse ficam no backstage: sustentam confiança e reprodutibilidade. O que se pitcha é o **sinal**.

## 6. De ponta a ponta: o que “dado → valor” significou neste TCC

1. **Origem rastreável** — ANAC (fato operacional) + cotação (fato de mercado), regimes distintos.  
2. **SoR sem maquiagem** — ~9 GB que **não** vazam para Git nem para a UI.  
3. **SoT como pedágio de qualidade** — IATA, município, features, 346 aeroportos BR.  
4. **Spec como contrato** — 1,27 M linhas, 47 colunas de risco, métricas e joblib versionados.  
5. **Validação temporal** — MAE/AUC em validação **e** teste.  
6. **Regra de negócio escrita** — ±5% → COMPRAR / AGUARDAR / MONITORAR.  
7. **Serving desacoplado** — Databricks Free materializa; API serve; SerpAPI sob cota.  
8. **Degradação honesta** — sem match Spec, não se fabrica score.  
9. **Vitrine de produto** — prints da entrega, não do repositório.

Valor = **menos arrependimento na compra** + **narrativa defensável** na banca + **ativo reutilizável** se o grupo quiser produto.

## 7. O que o Databricks Free habilitou (e o que não)

| Habilitou | Limitação consciente |
|-----------|----------------------|
| Delta + notebooks 08–10 | Sem cluster 24/7 na UI |
| MLflow / métricas versionadas | Export Spec para disco/API |
| AI/BI gerencial da malha | Doméstico BR no MVP |
| Mesmo Gold para dash e app | Internacional: cotação ok; Spec ANAC ainda não |

Isso é governança de camadas — não desculpa.

## Conclusão

Engenharia de dados completa não é “ter Bronze”. É fechar o fio:

**origem → qualidade → feature → modelo → métrica → regra → produto → degradação.**

O VooAI percorre esse fio com números reais e uma UI que devolve ação. Dashboard sem limiar continua teatro. Pipeline sem Spec continua custo. Dado com contrato de decisão começa a pagar o MBA — e, se for o caso, o negócio.

O próximo passo comercial não é “mostrar o Git”. É **fechar a narrativa** com prints da entrega, métricas honestas e um usuário que entende o sinal em segundos.

---

## Créditos — colaboração do MBA

Este trabalho foi feito **em colaboração** com os parceiros do MBA em Engenharia de Dados no projeto **VooAI**:

- [Agnes Ruescas](https://www.linkedin.com/in/agnesruescas/)
- [Gustavo de Paula](https://www.linkedin.com/in/gustavodepaulades/)
- [Santina Cortinove](https://www.linkedin.com/in/santina-cortinove-362bb9161/)
- [Raul Chavarria](https://www.linkedin.com/in/raulchavarria/)
- [Brunno Mambro](https://www.linkedin.com/in/brunno-mambro-232639b3/)

*Texto e publicação no DataDriks: [Adriano Santos](https://www.linkedin.com/in/drico2236) — com o grupo VooAI acima.*

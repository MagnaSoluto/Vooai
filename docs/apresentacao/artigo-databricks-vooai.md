# Do dado bruto à decisão: como o VooAI transforma ANAC + cotações em sinal de compra

**Artigo para publicação no Databricks (Community / Medium / blog técnico)**  
Projeto acadêmico — MBA em Engenharia de Dados · VooAI  
Stack: Databricks Free Edition · Delta Lake · MLflow · Spec (Gold) · FastAPI · React

---

## Resumo executivo

Comprar passagem aérea no Brasil é um problema de **assimétrica de informação**: o preço muda o tempo todo, o atraso é estrutural e o passageiro quase sempre decide no escuro. O **VooAI** fecha esse gap com um lakehouse enxuto no Databricks Free: dados abertos da ANAC (VRA) e cotações vivas viram uma Spec (Gold) com scores de risco, previsão de preço e a regra de negócio **COMPRAR / AGUARDAR / MONITORAR**.

A tese do artigo — e do TCC — é simples: **dado só vira valor quando chega à decisão no momento certo**, com métricas honestas e um produto que o usuário entende.

---

## 1. O problema de negócio (não o de tecnologia)

Três perguntas que o passageiro faz de verdade:

1. **Esse preço está caro ou barato** para esta rota e data?
2. **Vale comprar agora** ou esperar alguns dias?
3. **Qual companhia / trecho** tem histórico pior de atraso e cancelamento?

Planilhas e scrapes soltos respondem mal. O valor está em **juntar** histórico operacional (ANAC) com preço ao vivo (Google Flights via SerpAPI) e devolver **uma ação**, não um dashboard de 40 KPIs.

---

## 2. Arquitetura: lakehouse como fábrica de decisão

No Databricks Free Edition usamos o padrão clássico — com nomes de produto SoR / SoT / Spec:

| Camada | Nome | O que entra | O que sai |
|--------|------|-------------|-----------|
| Bronze | **SoR** | VRA/ANAC e fontes brutas | Fatos sem “embelezar” |
| Silver | **SoT** | Limpeza, IATA, features | Base confiável para modelo |
| Gold | **Spec** | Scores, previsões, KPIs | Contrato do produto |

Dois consumos da mesma Spec:

1. **AI/BI Dashboard** no Databricks — leitura gerencial da malha doméstica.
2. **Produto web** — FastAPI lê parquet Spec exportado; React mostra busca + recomendação. A API **não** treina modelo no request (evita timeout do Free e permite demo estável).

```text
ANAC + cotações
    → SoR → SoT → Spec (MLflow)
         ↘ AI/BI Dashboard
         ↘ export parquet → API → UI (COMPRAR / AGUARDAR / MONITORAR)
```

**Lição de valor:** separar *treino/materialização* (Databricks) de *serviço* (API) é o que torna o MVP acadêmico operável — e é o mesmo padrão de empresas que não querem acoplar cluster de ML ao click do usuário.

---

## 3. Métricas que importam (e o que elas ensinam)

Números abaixo vêm da Spec materializada em `2026-09-08` (validação temporal).

### 3.1 Preço — regressão com split temporal

Modelo `preco_ridge_temporal`:

| Split | MAE (R$) | RMSE (R$) | MAPE | R² |
|-------|----------|-----------|------|-----|
| Validação | **397** | **620** | 33% | 0,27 |
| Teste | **417** | **651** | 34% | 0,24 |

**Como ler isso sem autoengano:** em tarifas domésticas voláteis, MAE na casa de R$ 400 não “resolve” o mercado — mas **ordena** o sinal. O valor não é acertar o centavo; é dizer se a tendência aponta para **subir (≥ +5%)**, **cair (≤ −5%)** ou **ficar no meio** → regra COMPRAR / AGUARDAR / MONITORAR.

**Ensino:** métrica sem regra de negócio é vanity metric. MAE/RMSE só viram valor quando viram **política de decisão**.

### 3.2 Risco operacional — classificação (atraso e cancelamento)

| Modelo | Split | ROC-AUC | PR-AUC | Prevalência |
|--------|-------|---------|--------|-------------|
| Cancelamento (logística) | teste | **0,68** | 0,06 | ~1,6% |
| Atraso (logística) | teste | **0,65** | 0,52 | ~37% |

Cancelamento é **evento raro** (PR-AUC baixo é esperado). Atraso é frequente (~37% dos voos no histórico agregado das big 3). O produto combina scores históricos por empresa/rota com o preço vivo — o passageiro vê **confiabilidade relativa**, não uma falsa certeza.

**Ensino:** em classes desbalanceadas, ROC sozinho mente; prevalência + PR-AUC contam a história certa. Transparência metodológica **é** valor de negócio (confiança no sinal).

### 3.3 Escala da Spec de produto

- **~1,27 milhão** de linhas em `spec_modelos_risco` (janela de datas de voo materializada para o MVP).
- Histórico de cias (recorte): Azul ~1,3M voos (atraso ~33%), LATAM/TAM ~1,1M (~38%), Gol ~0,98M (~37%) — ordens de grandeza ANAC que o dashboard e o detalhe do voo usam.

**Ensino:** volume na Bronze não impressiona o CFO; ** Spec enxuta e versionada** (no Git, ~40 MB de Gold) impressiona o time que precisa clonar e demonstrar.

---

## 4. De métrica a valor: o fio condutor do TCC

Transformar dados em valor, neste projeto, significou cinco movimentos:

1. **Escolher a decisão** (comprar agora ou não) antes de escolher o algoritmo.
2. **Contratar a Spec** como produto — colunas estáveis, exportáveis, testáveis via `/health` e `/models/metrics`.
3. **Validação temporal** — não misturar futuro no treino; MAE/AUC reportados em validação **e** teste.
4. **Degradação honesta** — sem match Spec, a UI ainda mostra preço vivo; scores ANAC só onde há histórico doméstico.
5. **Custo de serving** — Databricks Free para factory; API + parquet para latência e cota SerpAPI sob controle.

Valor = **menos arrependimento na compra** + **narrativa auditável** para banca e para o próprio usuário.

---

## 5. O que o Databricks Free habilitou (e o que não)

| Habilitou | Limitação consciente |
|-----------|----------------------|
| Delta + notebooks 08–10 (ETL, risco, simulador) | Sem cluster 24/7 acoplado à UI |
| MLflow e métricas versionadas | Free Edition: export Spec para disco/API |
| AI/BI para leitura gerencial | Malha **doméstica BR** no MVP |
| Mesmo artefato Gold para dash e app | Internacional = SerpAPI ok; Spec ANAC ainda não |

Isso é feature, não bug: o TCC demonstra **governança de camadas** e **ponte Git ↔ workspace**, não um monólito na nuvem.

---

## 6. Conclusão

Engenharia de dados deixa de ser “pipeline bonito” quando:

- a **pergunta de negócio** está escrita;
- as **métricas** batem com a pergunta;
- a **Spec** é o contrato;
- o **usuário** recebe uma ação (COMPRAR / AGUARDAR / MONITORAR), não um dump.

O VooAI é a prova de conceito desse caminho no ecossistema Databricks Free — do VRA da ANAC ao clique de busca, com números que o grupo pode defender na banca.

---

### Referências internas do monorepo

- Arquitetura: `docs/arquitetura.md`
- Deploy / Spec no Git: `docs/deploy-academico.md`, `data/README.md`
- Métricas Spec: `data/Spec/spec_metricas_modelos/`
- App: `https://vooai.magnasoluto.com.br` (ambiente acadêmico / demo)

### Créditos — colaboração do MBA

Projeto **VooAI** feito em colaboração com:

- [Agnes Ruescas](https://www.linkedin.com/in/agnesruescas/)
- [Gustavo de Paula](https://www.linkedin.com/in/gustavodepaulades/)
- [Santina Cortinove](https://www.linkedin.com/in/santina-cortinove-362bb9161/)
- [Raul Chavarria](https://www.linkedin.com/in/raulchavarria/)
- [Brunno Mambro](https://www.linkedin.com/in/brunno-mambro-232639b3/)

*Texto: Adriano Santos — MBA Engenharia de Dados · grupo Magna Soluto / Mackenzie.*

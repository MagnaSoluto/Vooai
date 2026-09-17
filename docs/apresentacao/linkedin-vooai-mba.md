# LinkedIn — post VooAI + TCC (MBA Engenharia de Dados)

Copie, ajuste o tom se quiser e publique. Há uma versão **curta** e uma **completa**.

---

## Versão completa (recomendada)

Acabei de fechar um ciclo que resume bem o que o MBA em Engenharia de Dados me cobrou na prática: **parar de acumular tabela e começar a entregar decisão**.

O projeto é o **VooAI** — sinal claro de **COMPRAR, AGUARDAR ou MONITORAR** na compra de passagens, cruzando:

• dados abertos da **ANAC (VRA)** — atraso e cancelamento reais da malha doméstica  
• **cotações ao vivo** (Google Flights)  
• uma Spec (Gold) materializada no **Databricks Free** (Delta + MLflow) e consumida por API + produto web  

Não foi “mais um dashboard”. Foi lakehouse com contrato: SoR → SoT → Spec, validação **temporal**, e métricas que a gente defende na banca — por exemplo, no modelo de preço (teste): MAE ≈ **R$ 417**, RMSE ≈ **R$ 651**; em atraso, ROC-AUC ≈ **0,65** com prevalência ~**37%**. Número sem regra de negócio é vaidade: o valor está no limiar de **±5%** que vira ação para o passageiro.

Aprendizado que levo do TCC / MBA:

1. Dado vira valor quando responde uma pergunta cara (comprar agora ou não).  
2. Gold/Spec versionada (>1M linhas de risco no recorte do MVP, ~40 MB no Git) vale mais que Bronze gigante sem dono.  
3. Separar treino (Databricks) de serving (API) é maturidade, não gambiarra.  

Feito **em colaboração** com o grupo do MBA — projeto **VooAI**:

Agnes Ruescas · Gustavo de Paula · Santina Cortinove · Raul Chavarria · Brunno Mambro  
(LinkedIns no artigo: datadriks.com.br/artigos/vooai-do-dado-bruto-a-decisao)

Engenharia de dados, no fim, é **confiança + timing + decisão**.

#EngenhariaDeDados #MBA #Databricks #DeltaLake #MachineLearning #ANAC #VooAI #DataToValue #Mackenzie

---

## Versão curta (feed / mobile)

MBA em Engenharia de Dados → TCC na prática: o **VooAI**.

Lakehouse no **Databricks Free** (SoR/SoT/Spec) + preço ao vivo + histórico ANAC = sinal **COMPRAR / AGUARDAR / MONITORAR**.

Métricas com validação temporal (ex.: MAE preço ~R$ 417 no teste; atraso ROC-AUC ~0,65). O ponto não é o modelo “perfeito” — é **transformar dado em decisão** com regra de negócio (±5%) e Spec auditável.

Do pipeline à UI: isso, pra mim, é data engineering de verdade.

#EngenhariaDeDados #Databricks #MBA #VooAI #DataToValue

---

## Sugestão de mídia

1. Print do produto (Home ou Resultado com COMPRAR/AGUARDAR/MONITORAR).  
2. Print do dashboard / fluxo SoR→SoT→Spec (mermaid do `docs/arquitetura.md`).  
3. Tabela pequena de métricas (MAE/RMSE + AUC) — reforça credibilidade.

## CTA opcional (última linha)

“Se quiser o artigo técnico completo (Databricks + métricas), comento ‘artigo’ que mando o link.”  
*(Anexo ou link: `docs/apresentacao/artigo-databricks-vooai.md` no repo / Medium / Databricks Community.)*

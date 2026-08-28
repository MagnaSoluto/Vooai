---
name: vooai-ml
description: >-
  Modelagem VooAI: regressão, séries temporais, validação temporal, MLflow e
  regra COMPRAR/AGUARDAR/MONITORAR ±5%. Use when training models, MAE/RMSE,
  forecasting fares, or changing the decision threshold.
---

# Modelagem e decisão

Notebooks 05–07. Target: preço futuro **ou** variação % em janela definida na EDA.

- Validação **temporal** (proibido shuffle aleatório).
- Métricas: MAE, RMSE; R² só complementar na regressão.
- Regressão: Linear baseline, RF, boosting se viável.
- Séries: baseline + ARIMA/SARIMA e/ou Prophet.
- Registrar no MLflow do Free.

Regra inicial (calibrar):

- COMPRAR se `predicted_change_pct >= 0.05`
- AGUARDAR se `predicted_change_pct <= -0.05`
- MONITORAR no meio

A recomendação é camada **depois** do modelo. Incluir confiabilidade ANAC na UX, não no target de preço.

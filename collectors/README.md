# Collectors — cotações

Rotina Python de coleta periódica (rota, companhia, datas, horários, duração, escalas, antecedência).

## Regras

- MVP: rotas em [`docs/rotas-mvp.md`](../docs/rotas-mvp.md).
- Schema de persistência Bronze: ver [`docs/dicionario-de-dados.md`](../docs/dicionario-de-dados.md) (`gold.quotes` deriva daqui).
- Não versionar dumps grandes; gravar JSON/CSV em `data/raw/` (gitignore) e subir para Bronze no Databricks Free.
- Documentar a fonte escolhida pelo grupo e respeitar termos de uso. Sem scraping agressivo.

## Frequência sugerida (calibrar)

- 1–2 coletas/dia por rota do MVP durante o desenvolvimento.
- Registrar `collected_at` em UTC e `lead_days` derivado.

Próximo passo: implementar o script quando a fonte de cotação estiver fechada.

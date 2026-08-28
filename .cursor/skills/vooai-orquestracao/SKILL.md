---
name: vooai-orquestracao
description: >-
  Índice do monorepo VooAI: mapa skill↔agente, pastas, ordem de ativação.
  Use at the start of any VooAI task, when choosing which specialist to call,
  or when the user mentions Facu, VooAI, lakehouse, ou o projeto de passagens.
---

# Orquestração VooAI

Projeto acadêmico Mackenzie. Git = fonte de verdade. Databricks **Free Edition** = compute + Delta + AI/BI. **Proibido:** OCI, Carbon, skills/agentes Carbon.

## Pastas

| Path | Dono típico |
|------|-------------|
| `branding/` | vooai-brand |
| `collectors/` | vooai-ingestao |
| `notebooks/` | ingestão / lakehouse / ml |
| `data/gold/` | lakehouse + backend |
| `apps/api` | vooai-backend |
| `apps/web` | vooai-frontend |
| `docs/arquitetura.md` | vooai-docs |

## Matriz objetivo → ordem

| Objetivo | Ordem |
|----------|--------|
| Qualquer tarefa nova | **vooai-orquestrador** (esta skill) |
| Branding / HTML / tokens | vooai-brand |
| Nova tela | vooai-brand → vooai-frontend → vooai-qa |
| Coleta de preço | vooai-ingestao (coleta) → lakehouse → qa |
| Ingestão ANAC | vooai-ingestao (anac) → lakehouse → qa |
| Camadas Delta / dicionário | vooai-lakehouse |
| Modelo / regra ±5% | vooai-ml → lakehouse (Gold) → backend → qa |
| API | vooai-backend |
| Dashboard Databricks | skill vooai-dashboard |
| README / slides | vooai-docs |
| Aceite MVP | vooai-qa |

Ler a skill correspondente em `.cursor/skills/vooai-*/SKILL.md` antes de editar.

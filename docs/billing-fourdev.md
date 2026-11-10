# Recarga VooAI via Billing API FourDev

VooAI **não** chama Asaas. Fluxo igual ao SDR:

```text
VooAI POST /wallet/topup
  → Billing API POST /billing/v1/charges (platform_id=vooai)
    → Asaas PIX
Asaas webhook → Billing API /billing/v1/webhook
  → forward VOOAI_BASE_URL + /billing/webhooks/asaas
    → credita carteira VooAI
```

## Env VooAI

| Var | Uso |
|-----|-----|
| `VOOAI_BILLING_ENABLED` | `0` = API gratuita (sem Bearer/débito). `1` = cobra busca |
| `BILLING_API_URL` | **Mesmo nome do SDR** — origem do serviço `billing-api` |
| `BILLING_API_TOKEN` | mesmo token do `/opt/billing/app.env` |
| `VOOAI_WEBHOOK_TOKEN` | só o aviso de pagamento; diferente de `BILLING_API_TOKEN` |

Valores canônicos (iguais ao SDR / `docs/BILLING-CHECKOUT.md`):

| Ambiente | `BILLING_API_URL` |
|----------|-------------------|
| Local (barber compose) | `http://127.0.0.1:8380` |
| Box Docker | `http://billing-api:8080` |
| Prod (Caddy) | `https://api.fourdev.com.br` (path `/billing/v1/...`) |

Cobrança: `POST {BILLING_API_URL}/billing/v1/charges` com `Authorization: Bearer` + `X-Billing-Token`.

Sem `BILLING_API_*` ou com `stub=true`: topup usa crédito imediato (só dev).  
Com `VOOAI_BILLING_ENABLED=0`: `/search` livre (sem token) — modo testes / cota SerpAPI.

## Env Billing API (barber)

| Var | Uso |
|-----|-----|
| `VOOAI_BASE_URL` | ex. `http://vooai-api:8000` ou `https://vooai…/api` |
| `platform_id` | whitelist inclui **`vooai`** |

## External reference

`vooai:{user_id}:wallet:wallet_recharge:{yyyyMMddHHmm}`

## Docs relacionadas

- SDR: `../SDR/docs/BILLING-CHECKOUT.md`
- Barber: `FourDev.Billing.Api`

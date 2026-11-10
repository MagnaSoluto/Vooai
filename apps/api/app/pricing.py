"""Preço da busca VooAI — saldos + margem mínima 30% sobre custo SerpAPI.

1 saldo = 1 unidade de busca (preço de referência da ida = R$ 0,12).
Débito por busca = N saldos = créditos SerpAPI estimados (ida=1, RT=3, flex…).

Recarga PIX: bruto − taxa Asaas → floor(líquido / 0,12) saldos creditados.
Taxa Asaas PIX padrão: R$ 1,99/transação (override VOOAI_ASAAS_PIX_FEE_BRL).
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

# Margem mínima de produto (não negociar abaixo sem revisar custo).
MIN_MARGIN = 0.30

# Custo variável por crédito SerpAPI (BRL). Override por env.
DEFAULT_COST_PER_CREDIT_BRL = 0.08

# Recarga mínima da carteira (BRL).
MIN_TOPUP_BRL = 5.00

# 1 saldo ≈ busca ida (price_for_credits(1) com custo 0,08 e margem 30%).
SALDO_UNIT_BRL = 0.12

# Taxa Asaas PIX por cobrança recebida (padrão público; contrato pode diferir).
DEFAULT_ASAAS_PIX_FEE_BRL = 1.99


def cost_per_credit_brl() -> float:
    raw = os.getenv("VOOAI_SERPAPI_COST_BRL", str(DEFAULT_COST_PER_CREDIT_BRL))
    try:
        return max(0.01, float(raw))
    except ValueError:
        return DEFAULT_COST_PER_CREDIT_BRL


def asaas_pix_fee_brl() -> float:
    raw = os.getenv("VOOAI_ASAAS_PIX_FEE_BRL", str(DEFAULT_ASAAS_PIX_FEE_BRL))
    try:
        return max(0.0, float(raw))
    except ValueError:
        return DEFAULT_ASAAS_PIX_FEE_BRL


def ceil_brl(value: float) -> float:
    """Arredonda para cima em centavos (protege a margem)."""
    return math.ceil(value * 100) / 100


def price_for_credits(credits: int, *, margin: float = MIN_MARGIN) -> float:
    """Preço cobrado do usuário para N créditos SerpAPI, com margem mínima."""
    if credits < 1:
        credits = 1
    m = max(margin, MIN_MARGIN)
    unit = cost_per_credit_brl() / (1.0 - m)
    return ceil_brl(credits * unit)


def estimate_serpapi_credits(
    *,
    trip_type: str = "ida",
    flex_dates: str = "off",
) -> int:
    """Espelha o teto de chamadas em search.py (ida=1, RT=3, flex ida≤7, flex RT≤12)."""
    flex = (flex_dates or "off").strip().lower()
    if flex in ("", "false", "0", "none", "no"):
        flex = "off"
    if flex in ("true", "1", "yes", "dias", "days"):
        flex = "nearby"
    rt = (trip_type or "ida").strip().lower() in ("ida_volta", "roundtrip", "rt")
    if flex == "off":
        return 3 if rt else 1
    if rt:
        return 12  # até 4 âncoras × 3
    return 7  # até 7 datas


def net_after_asaas(amount_brl: float) -> float:
    """Valor líquido após taxa fixa Asaas PIX (não pode ficar negativo)."""
    bruto = max(0.0, float(amount_brl))
    fee = min(asaas_pix_fee_brl(), bruto)  # Asaas: taxa ≤ valor da cobrança
    return round(bruto - fee, 2)


def saldos_from_topup_brl(amount_brl: float) -> dict[str, float | int]:
    """Converte PIX bruto → saldos creditáveis (após Asaas)."""
    bruto = ceil_brl(float(amount_brl))
    fee = round(min(asaas_pix_fee_brl(), bruto), 2)
    net = round(bruto - fee, 2)
    unit = SALDO_UNIT_BRL
    saldos = int(math.floor(net / unit + 1e-9)) if net > 0 and unit > 0 else 0
    return {
        "pay_brl": bruto,
        "asaas_fee_brl": fee,
        "net_brl": net,
        "saldo_unit_brl": unit,
        "saldos": saldos,
    }


def brl_equiv_saldos(saldos: int | float) -> float:
    return round(float(saldos) * SALDO_UNIT_BRL, 2)


@dataclass(frozen=True)
class QuotePrice:
    credits: int
    saldos: int
    cost_brl: float
    price_brl: float
    margin: float
    trip_type: str
    flex_dates: str

    def as_dict(self) -> dict:
        return {
            "credits": self.credits,
            "saldos": self.saldos,
            "cost_brl": round(self.cost_brl, 4),
            "price_brl": self.price_brl,
            "margin": self.margin,
            "trip_type": self.trip_type,
            "flex_dates": self.flex_dates,
            "currency": "BRL",
            "saldo_unit_brl": SALDO_UNIT_BRL,
        }


def quote_price(
    *,
    trip_type: str = "ida",
    flex_dates: str = "off",
    return_date: str | None = None,
) -> QuotePrice:
    tt = trip_type or "ida"
    if return_date and tt == "ida":
        tt = "ida_volta"
    credits = estimate_serpapi_credits(trip_type=tt, flex_dates=flex_dates or "off")
    cost = round(credits * cost_per_credit_brl(), 4)
    price = price_for_credits(credits)
    return QuotePrice(
        credits=credits,
        saldos=credits,  # 1 crédito SerpAPI cobrado = 1 saldo
        cost_brl=cost,
        price_brl=price,
        margin=MIN_MARGIN,
        trip_type=tt,
        flex_dates=(flex_dates or "off"),
    )


# Tabela de referência (Developer SerpAPI, R$ 0,08/crédito, margem 30%).
PRICE_TABLE = {
    "ida": price_for_credits(1),  # R$ 0,12 → 1 saldo
    "ida_volta": price_for_credits(3),  # R$ 0,35 → 3 saldos
    "flex_ida": price_for_credits(7),  # R$ 0,80 → 7 saldos
    "flex_ida_volta": price_for_credits(12),  # R$ 1,38 → 12 saldos
}

PRICE_TABLE_SALDOS = {
    "ida": 1,
    "ida_volta": 3,
    "flex_ida": 7,
    "flex_ida_volta": 12,
}

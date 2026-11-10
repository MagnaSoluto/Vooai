"""Cliente da Billing API VooAI (Asaas fica atrás dela — nunca chamar Asaas daqui)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class ChargeResult:
    cobranca_id: str
    customer_id: str | None
    status: str
    metodo: str | None
    copia_e_cola: str | None
    qr_base64: str | None
    invoice_url: str | None
    valor: float
    external_reference: str | None
    raw: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "cobranca_id": self.cobranca_id,
            "customer_id": self.customer_id,
            "status": self.status,
            "metodo": self.metodo,
            "copia_e_cola": self.copia_e_cola,
            "qr_base64": self.qr_base64,
            "invoice_url": self.invoice_url,
            "valor": self.valor,
            "external_reference": self.external_reference,
            "provider": "billing_api",
        }


class BillingNotConfigured(Exception):
    pass


class BillingApiError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        super().__init__(message)


def billing_configured() -> bool:
    return bool((os.getenv("BILLING_API_URL") or "").strip() and (os.getenv("BILLING_API_TOKEN") or "").strip())


def _base() -> str:
    raw = (os.getenv("BILLING_API_URL") or "").strip().rstrip("/")
    # Igual ao SDR BillingApiHttpClientFactory: URL pode vir com sufixo /billing
    if raw.lower().endswith("/billing"):
        raw = raw[: -len("/billing")].rstrip("/")
    return raw


def _token() -> str:
    return (os.getenv("BILLING_API_TOKEN") or os.getenv("X_BILLING_TOKEN") or "").strip()


def create_pix_charge(
    *,
    user_id: int,
    email: str,
    amount_brl: float,
    customer_name: str | None = None,
    customer_document: str | None = None,
) -> ChargeResult:
    if not billing_configured():
        raise BillingNotConfigured(
            "BILLING_API_URL / BILLING_API_TOKEN não configurados. "
            "Use stub local ou aponte BILLING_API_URL / BILLING_API_TOKEN."
        )

    from datetime import datetime, timezone

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
    ext = f"vooai:{user_id}:wallet:wallet_recharge:{stamp}"
    body = {
        "platform_id": "vooai",
        "tenant_externo_id": str(user_id),
        "customer_name": (customer_name or email or f"VooAI user {user_id}").strip(),
        "customer_email": email,
        "customer_document": customer_document,
        "customer_phone": None,
        "amount_brl": float(amount_brl),
        "description": f"VooAI — recarga R$ {amount_brl:.2f}",
        "billing_type": "pix",
        "external_reference": ext,
        "kind": "wallet_recharge",
    }
    headers = {
        "Authorization": f"Bearer {_token()}",
        "X-Billing-Token": _token(),
        "Content-Type": "application/json",
    }
    url = f"{_base()}/billing/v1/charges"
    with httpx.Client(timeout=45.0) as client:
        res = client.post(url, json=body, headers=headers)
        try:
            data = res.json()
        except Exception:
            data = {}
        if res.status_code >= 400:
            erro = (data.get("erro") or {}) if isinstance(data, dict) else {}
            msg = erro.get("mensagem") or res.text[:300] or res.reason_phrase
            raise BillingApiError(res.status_code, f"Billing API ({res.status_code}): {msg}")

    return ChargeResult(
        cobranca_id=str(data.get("cobranca_id") or ""),
        customer_id=data.get("customer_id"),
        status=str(data.get("status") or "pendente"),
        metodo=data.get("metodo"),
        copia_e_cola=data.get("copia_e_cola"),
        qr_base64=data.get("qr_base64"),
        invoice_url=data.get("invoice_url"),
        valor=float(data.get("valor") or amount_brl),
        external_reference=data.get("external_reference") or ext,
        raw=data if isinstance(data, dict) else {},
    )


def get_charge(cobranca_id: str) -> ChargeResult:
    """Lê valor, status e referência gravados. O corpo do webhook não decide o crédito."""
    if not billing_configured():
        raise BillingNotConfigured("BILLING_API_URL / BILLING_API_TOKEN não configurados.")
    if not (cobranca_id or "").strip():
        raise BillingApiError(400, "cobranca_id vazio")

    headers = {
        "Authorization": f"Bearer {_token()}",
        "X-Billing-Token": _token(),
    }
    url = f"{_base()}/billing/v1/charges/{cobranca_id.strip()}"
    with httpx.Client(timeout=20.0) as client:
        res = client.get(url, headers=headers)
        try:
            data = res.json()
        except Exception:
            data = {}
        if res.status_code >= 400 or not isinstance(data, dict):
            erro = (data.get("erro") or {}) if isinstance(data, dict) else {}
            msg = erro.get("mensagem") or res.text[:300] or res.reason_phrase
            raise BillingApiError(res.status_code, f"Billing API ({res.status_code}): {msg}")

    valor = float(data.get("valor") or 0)
    referencia = str(data.get("external_reference") or "")
    if valor <= 0 or not referencia:
        raise BillingApiError(502, "Cobrança sem valor ou referência confirmados.")

    return ChargeResult(
        cobranca_id=str(data.get("cobranca_id") or cobranca_id),
        customer_id=data.get("customer_id"),
        status=str(data.get("status") or ""),
        metodo=data.get("metodo"),
        copia_e_cola=data.get("copia_e_cola"),
        qr_base64=data.get("qr_base64"),
        invoice_url=data.get("invoice_url"),
        valor=valor,
        external_reference=referencia,
        raw=data,
    )

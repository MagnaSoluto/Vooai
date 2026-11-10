from __future__ import annotations

import hmac
import os
from pathlib import Path
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import quote_cache
from .auth import require_user_if_billing
from .billing_client import (
    BillingApiError,
    BillingNotConfigured,
    billing_configured,
    create_pix_charge,
    get_charge,
)
from .cookies import REFRESH_COOKIE, attach_session_cookies, clear_refresh_cookie
from .dashboard import dashboard_summary
from .db import billing_enabled, db_label, init_db
from .detail import flight_detail
from .models import AirportHit, DashboardSummary, Health, SearchResponse
from .paths import spec_dir
from .pricing import (
    MIN_TOPUP_BRL,
    PRICE_TABLE,
    PRICE_TABLE_SALDOS,
    SALDO_UNIT_BRL,
    asaas_pix_fee_brl,
    brl_equiv_saldos,
    cost_per_credit_brl,
    quote_price,
    saldos_from_topup_brl,
)
from .rate_limit import check_rate_limit
from .search import airline_reliability, simular_viagem, try_cached_viagem
from .security import allow_topup_stub, cors_origins, is_prod, search_require_auth
from .sessions import (
    ensure_auth_schema,
    login_with_password,
    refresh_session,
    register_with_password,
    request_magic_link,
    revoke_refresh,
    smtp_configured,
    verify_magic_link,
)
from .spec_store import (
    clear_caches,
    dim_aeroportos,
    gold_date_range,
    gold_path,
    metrics_rows,
)
from .telemetry import (
    amount_bucket,
    record_batch,
    record_event,
    saldos_bucket,
    summary as telemetry_summary,
    telemetry_enabled,
)
from .wallet import (
    InsufficientFunds,
    User,
    credit_from_charge,
    debit,
    ledger_for,
    refund,
    save_pending_charge,
    topup,
    wallet_public,
)

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

app = FastAPI(
    title="VooAI API",
    version="0.5.0",
    description=(
        "Cotações Google Flights + Spec. Cache Redis, carteira e auth "
        "(senha / código por e-mail; access + refresh HttpOnly)."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-VooAI-Token", "X-VooAI-Admin-Token"],
)

UserDep = Annotated[User | None, Depends(require_user_if_billing)]


@app.on_event("startup")
def _startup() -> None:
    init_db()
    ensure_auth_schema()


class RegisterBody(BaseModel):
    email: str = Field(..., min_length=5, max_length=200)
    password: str = Field(..., min_length=8, max_length=200)


class LoginBody(BaseModel):
    email: str = Field(..., min_length=5, max_length=200)
    password: str = Field(..., min_length=8, max_length=200)


class MagicRequestBody(BaseModel):
    email: str = Field(..., min_length=5, max_length=200)


class MagicVerifyBody(BaseModel):
    email: str = Field(..., min_length=5, max_length=200)
    code: str = Field(..., min_length=4, max_length=12)


class RefreshBody(BaseModel):
    refresh_token: str | None = None


class TelemetryEventIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=40)
    props: dict[str, Any] = Field(default_factory=dict)
    authenticated: bool = False
    session_anon: str | None = Field(default=None, max_length=64)


class TelemetryBatchIn(BaseModel):
    events: list[TelemetryEventIn] = Field(default_factory=list, max_length=20)
    session_anon: str | None = Field(default=None, max_length=64)
    authenticated: bool = False


class LogoutBody(BaseModel):
    refresh_token: str | None = None


class TopupBody(BaseModel):
    amount_brl: float = Field(..., description=f"Mínimo R$ {MIN_TOPUP_BRL:.2f}")
    customer_name: str | None = None
    customer_document: str | None = None
    stub: bool = False


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "anon"


def _rl_auth(request: Request, bucket: str) -> None:
    try:
        check_rate_limit(f"auth:{bucket}:{_client_ip(request)}")
    except RuntimeError as exc:
        raise HTTPException(
            status_code=429,
            detail={"code": "rate_limited", "message": str(exc)},
        ) from exc


def _auth_response(payload: dict[str, Any], response: Response) -> dict[str, Any]:
    return attach_session_cookies(response, payload)


@app.get("/health", response_model=Health)
def health() -> Health:
    gold = None
    dmin = dmax = None
    try:
        gold = gold_path()
        a, b = gold_date_range()
        dmin, dmax = a.isoformat(), b.isoformat()
    except Exception:
        pass
    return Health(
        status="ok",
        spec_dir=str(spec_dir()) if not is_prod() else "/data/Spec",
        gold_file=gold if not is_prod() else (Path(gold).name if gold else None),
        gold_date_min=dmin,
        gold_date_max=dmax,
        serpapi_configured=bool(os.getenv("SERPAPI_API_KEY")),
        quote_cache_backend=quote_cache.backend_name(),
        quote_cache_ttl_sec=quote_cache.cache_ttl_sec(),
        redis_ok=quote_cache.redis_ok(),
    )


@app.post("/events")
def ingest_events(body: TelemetryBatchIn, request: Request) -> dict[str, Any]:
    """Ingest client-side product events (fail-open, sem PII)."""
    if not telemetry_enabled():
        return {"ok": True, "accepted": 0, "enabled": False}
    rl_key = f"tel:{request.client.host if request.client else 'anon'}"
    try:
        check_rate_limit(rl_key)
    except RuntimeError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    items = [e.model_dump() for e in body.events]
    accepted = record_batch(
        items,
        default_authenticated=body.authenticated,
        default_session_anon=body.session_anon,
    )
    return {"ok": True, "accepted": accepted, "enabled": True}


@app.get("/events/summary")
def events_summary(
    days: int = Query(7, ge=1, le=90),
    x_vooai_admin_token: str | None = Header(default=None, alias="X-VooAI-Admin-Token"),
) -> dict[str, Any]:
    expected = (os.getenv("VOOAI_ADMIN_TOKEN") or "").strip()
    if not expected or not _segredo_igual(expected, x_vooai_admin_token or ""):
        raise HTTPException(status_code=401, detail="Admin token inválido.")
    return telemetry_summary(days)


@app.get("/pricing")
def pricing_info(
    trip_type: str = Query("ida", description="ida | ida_volta"),
    flex_dates: str = Query("off", description="off | nearby | weekdays | weekends"),
    return_date: str | None = Query(None),
):
    q = quote_price(trip_type=trip_type, flex_dates=flex_dates, return_date=return_date)
    example = saldos_from_topup_brl(MIN_TOPUP_BRL)
    return {
        "min_margin": 0.30,
        "cost_per_credit_brl": cost_per_credit_brl(),
        "saldo_unit_brl": SALDO_UNIT_BRL,
        "asaas_pix_fee_brl": asaas_pix_fee_brl(),
        "min_topup_brl": MIN_TOPUP_BRL,
        "topup_example": example,
        "billing_enabled": billing_enabled(),
        "search_require_auth": search_require_auth(),
        "table": PRICE_TABLE,
        "table_saldos": PRICE_TABLE_SALDOS,
        "quote": q.as_dict(),
        "cache_ttl_sec": quote_cache.cache_ttl_sec(),
        "note": "Consulta entrega debita saldos (1 saldo ≈ busca ida). Recarga PIX: bruto − taxa Asaas → floor(líquido/0,12) saldos. Cache hit não gasta SerpAPI.",
        "db": "postgres" if db_label().startswith("postgres") else "sqlite",
        "billing_api_configured": billing_configured(),
        "magic_link_available": smtp_configured() or not is_prod(),
    }


@app.post("/auth/register")
def auth_register(request: Request, response: Response, body: RegisterBody) -> dict[str, Any]:
    _rl_auth(request, "register")
    try:
        return _auth_response(register_with_password(str(body.email), body.password), response)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "register_failed", "message": str(exc)}) from exc


@app.post("/auth/login")
def auth_login(request: Request, response: Response, body: LoginBody) -> dict[str, Any]:
    _rl_auth(request, "login")
    try:
        return _auth_response(login_with_password(str(body.email), body.password), response)
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail={"code": "auth_failed", "message": "Credenciais inválidas."},
        ) from None


@app.post("/auth/magic-link")
def auth_magic_link(request: Request, body: MagicRequestBody) -> dict[str, Any]:
    _rl_auth(request, "magic")
    try:
        return request_magic_link(str(body.email))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "magic_failed", "message": str(exc)}) from exc


@app.post("/auth/magic-link/verify")
def auth_magic_verify(request: Request, response: Response, body: MagicVerifyBody) -> dict[str, Any]:
    _rl_auth(request, "magic_verify")
    try:
        return _auth_response(verify_magic_link(str(body.email), body.code), response)
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail={"code": "magic_invalid", "message": "Código inválido ou expirado."},
        ) from None


@app.post("/auth/refresh")
def auth_refresh(request: Request, response: Response, body: RefreshBody | None = None) -> dict[str, Any]:
    _rl_auth(request, "refresh")
    raw = None
    if body and body.refresh_token:
        raw = body.refresh_token
    if not raw:
        raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise HTTPException(
            status_code=401,
            detail={"code": "refresh_invalid", "message": "Sessão expirada. Entre de novo."},
        )
    try:
        return _auth_response(refresh_session(raw), response)
    except ValueError:
        clear_refresh_cookie(response)
        raise HTTPException(
            status_code=401,
            detail={"code": "refresh_invalid", "message": "Sessão expirada. Entre de novo."},
        ) from None


@app.post("/auth/logout")
def auth_logout(
    request: Request,
    response: Response,
    user: UserDep,
    body: LogoutBody | None = None,
) -> dict[str, Any]:
    rt = (body.refresh_token if body else None) or request.cookies.get(REFRESH_COOKIE)
    revoke_refresh(rt, user_id=user.id if user else None)
    clear_refresh_cookie(response)
    return {"status": "ok"}


@app.get("/auth/me")
def auth_me(user: UserDep) -> dict[str, Any]:
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "auth_required", "message": "Entre na conta."},
        )
    return {
        **wallet_public(user),
        "billing_enabled": billing_enabled(),
        "search_require_auth": search_require_auth(),
        "currency": "BRL",
    }


@app.get("/wallet")
def wallet_balance(user: UserDep) -> dict[str, Any]:
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "auth_required", "message": "Token obrigatório para ver saldo."},
        )
    return {
        **wallet_public(user),
        "currency": "BRL",
        "billing_enabled": billing_enabled(),
    }


def _normalize_br_document(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    return digits or None


@app.post("/wallet/topup")
def wallet_topup(request: Request, body: TopupBody, user: UserDep) -> dict[str, Any]:
    """Recarga via Billing API (PIX). Stub só em não-prod."""
    _rl_auth(request, "topup")
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "auth_required", "message": "Token obrigatório."},
        )
    if body.amount_brl < MIN_TOPUP_BRL:
        raise HTTPException(
            status_code=400,
            detail={"code": "topup_min", "message": f"Recarga mínima: R$ {MIN_TOPUP_BRL:.2f}"},
        )

    preview = saldos_from_topup_brl(body.amount_brl)
    if int(preview["saldos"]) <= 0:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "topup_fee_exceeds",
                "message": (
                    f"Após taxa Asaas (R$ {preview['asaas_fee_brl']:.2f}) "
                    "não restam saldos. Aumente o valor da recarga."
                ),
                **preview,
            },
        )

    use_stub = allow_topup_stub() and (body.stub or not billing_configured())
    if use_stub:
        try:
            updated = topup(user.id, body.amount_brl, reason="topup_stub_local")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            **wallet_public(updated),
            "credited_brl": body.amount_brl,
            "credited_saldos": preview["saldos"],
            "topup_breakdown": preview,
            "provider": "stub_local",
            "status": "pago",
            "note": "Crédito imediato (dev). Em prod configure BILLING_API_URL.",
        }
    if body.stub and not allow_topup_stub():
        raise HTTPException(status_code=403, detail="Stub de recarga desligado em produção.")
    if not billing_configured():
        raise HTTPException(status_code=503, detail="Billing API não configurada.")

    document = _normalize_br_document(body.customer_document)
    if not document or len(document) not in (11, 14):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "document_required",
                "message": "Informe CPF (11 dígitos) ou CNPJ (14 dígitos) para gerar o PIX.",
            },
        )

    try:
        charge = create_pix_charge(
            user_id=user.id,
            email=user.email,
            amount_brl=body.amount_brl,
            customer_name=body.customer_name or user.email,
            customer_document=document,
        )
    except BillingNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BillingApiError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "billing_failed", "message": str(exc)},
        ) from exc

    if not charge.cobranca_id:
        raise HTTPException(status_code=502, detail="Billing API não retornou cobranca_id.")

    save_pending_charge(
        cobranca_id=charge.cobranca_id,
        user_id=user.id,
        amount_brl=charge.valor,
        external_reference=charge.external_reference,
    )
    return {
        **wallet_public(user),
        "provider": "billing_api",
        "status": charge.status,
        "amount_brl": charge.valor,
        "expected_saldos": preview["saldos"],
        "topup_breakdown": preview,
        "charge": charge.as_dict(),
        "note": (
            f"Após o PIX, creditamos ~{preview['saldos']} saldos "
            f"(R$ {preview['net_brl']:.2f} líquido − taxa Asaas R$ {preview['asaas_fee_brl']:.2f})."
        ),
    }


def _segredo_igual(esperado: str, recebido: str) -> bool:
    if not esperado or not recebido:
        return False
    a = esperado.encode()
    b = recebido.encode()
    if len(a) != len(b):
        return False
    return hmac.compare_digest(a, b)


def _is_paid_status(status: str | None, event_name: str | None = None) -> bool:
    """Espelha BillingPortalService.IsPaid do Leads (event + status Asaas/pt-BR)."""
    e = (event_name or "").strip().upper()
    s = (status or "").strip().upper()
    if e in {"PAYMENT_RECEIVED", "PAYMENT_CONFIRMED"}:
        return True
    return s in {
        "RECEIVED",
        "CONFIRMED",
        "RECEIVED_IN_CASH",
        "RECEBIDA",
        "CONFIRMADA",
        "PAGO",
    }


@app.post("/billing/webhooks/asaas")
async def billing_webhook_asaas(
    request: Request,
    asaas_access_token: str | None = Header(default=None, alias="asaas-access-token"),
    x_billing_token: str | None = Header(default=None, alias="X-Billing-Token"),
    authorization: str | None = Header(default=None),
):
    """Recebe forward da Billing API (não do Asaas direto)."""
    expected = (
        os.getenv("VOOAI_WEBHOOK_TOKEN") or os.getenv("BILLING_WEBHOOK_TOKEN") or ""
    ).strip()
    token = asaas_access_token or x_billing_token
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    # Fail-closed igual Leads: sem token configurado → 401
    if not expected or not _segredo_igual(expected, token or ""):
        raise HTTPException(status_code=401, detail="Webhook token inválido.")

    import json

    raw = await request.body()
    try:
        payload = json.loads(raw.decode() or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="JSON inválido") from None

    event = str(payload.get("event") or "")
    payment = payload.get("payment") if isinstance(payload.get("payment"), dict) else payload
    status = str(payment.get("status") or "")
    if not _is_paid_status(status, event):
        return {"ok": True, "ignored": True, "status": status or event}

    cobranca_id = str(payment.get("id") or payload.get("cobranca_id") or "")
    if not cobranca_id:
        return {"ok": True, "ignored": True, "reason": "sem cobranca_id"}

    try:
        confirmed = get_charge(cobranca_id)
    except (BillingApiError, BillingNotConfigured) as exc:
        raise HTTPException(status_code=503, detail="Cobrança não confirmada na Billing API.") from exc

    if not _is_paid_status(confirmed.status, None) or confirmed.valor <= 0:
        raise HTTPException(status_code=503, detail="Cobrança ainda não recebida.")

    ext = confirmed.external_reference or ""
    if not ext.startswith("vooai:"):
        return {"ok": True, "credited": False, "reason": "outra linha"}

    user = credit_from_charge(
        cobranca_id=cobranca_id,
        amount_brl=confirmed.valor,
        external_reference=ext,
    )
    if user is not None:
        record_event(
            "topup",
            {
                "status": "paid",
                "amount_bucket": amount_bucket(confirmed.valor),
                "saldos_bucket": saldos_bucket(getattr(user, "balance_saldos", None)),
                "source": "webhook",
            },
            authenticated=True,
            source="webhook",
        )
    return {
        "ok": True,
        "credited": user is not None,
        "cobranca_id": cobranca_id,
        "balance_saldos": user.balance_saldos if user else None,
        "balance_brl": user.balance_brl if user else None,
    }


@app.get("/wallet/ledger")
def wallet_ledger(user: UserDep, limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    if user is None:
        raise HTTPException(status_code=401, detail="Token obrigatório.")
    return {"email": user.email, "entries": ledger_for(user.id, limit=limit)}


def _do_search(
    *,
    origin: str,
    dest: str,
    date: str,
    return_date: str | None,
    trip_type: str | None,
    flex_dates: str | None,
    user: User | None,
    request: Request,
) -> SearchResponse:
    volta = return_date
    if trip_type == "ida":
        volta = None
    if trip_type == "ida_volta" and not volta:
        raise HTTPException(status_code=400, detail="Informe return_date para ida e volta.")

    rl_key = f"u:{user.id}" if user else f"ip:{request.client.host if request.client else 'anon'}"
    try:
        check_rate_limit(rl_key)
    except RuntimeError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    tt = "ida_volta" if volta else (trip_type or "ida")
    price = quote_price(trip_type=tt, flex_dates=flex_dates or "off", return_date=volta)

    # Débito antecipado: cliente paga toda consulta entregue (cache hit = margem nossa).
    # Estorno só se falharmos e NÃO entregarmos a busca (SerpAPI/Spec/validação/erro).
    ledger_id: int | None = None
    if billing_enabled():
        if user is None:
            raise HTTPException(status_code=401, detail="Billing ativo: envie Bearer token.")
        try:
            user, ledger_id = debit(
                user.id,
                price.saldos,
                reason=f"search:{price.trip_type}:{price.flex_dates}",
                search_ref=f"{origin}->{dest}:{date}",
            )
        except InsufficientFunds as exc:
            raise HTTPException(
                status_code=402,
                detail={
                    "message": "Saldos insuficientes",
                    "balance_saldos": exc.balance_saldos,
                    "required_saldos": exc.required_saldos,
                    "balance_brl": brl_equiv_saldos(exc.balance_saldos),
                    "required_brl": brl_equiv_saldos(exc.required_saldos),
                    "topup_min_brl": MIN_TOPUP_BRL,
                },
            ) from exc

    def _refund_undelivered(reason: str) -> None:
        """Estorna só quando a busca não foi entregue ao cliente."""
        if ledger_id:
            refund(ledger_id, reason=reason)

    try:
        cached = try_cached_viagem(origin, dest, date, volta, flex_dates=flex_dates)
    except ValueError as exc:
        _refund_undelivered("refund_undelivered_validation")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        _refund_undelivered("refund_undelivered_spec")
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if cached is not None:
        # Entregue via cache — mantém débito (não estorna).
        cached["pricing"] = cached.get("pricing") or price.as_dict()
        cached["pricing"]["charged"] = True
        cached["pricing"]["serpapi_spent"] = False
        if ledger_id:
            cached["pricing"]["ledger_id"] = ledger_id
        if user:
            cached["wallet_balance_brl"] = user.balance_brl
            cached["wallet_balance_saldos"] = user.balance_saldos
        return SearchResponse(**cached)

    try:
        payload = simular_viagem(origin, dest, date, volta, flex_dates=flex_dates)
        # Entregue (miss ou race de cache) — mantém débito.
        if user:
            payload["wallet_balance_brl"] = user.balance_brl
            payload["wallet_balance_saldos"] = user.balance_saldos
        if payload.get("pricing") is None:
            payload["pricing"] = price.as_dict()
        payload["pricing"]["charged"] = True
        payload["pricing"]["serpapi_spent"] = not bool(payload.get("cache_hit"))
        if ledger_id:
            payload["pricing"]["ledger_id"] = ledger_id
        return SearchResponse(**payload)
    except ValueError as exc:
        _refund_undelivered("refund_undelivered_validation")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        _refund_undelivered("refund_undelivered_serpapi")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        _refund_undelivered("refund_undelivered_spec")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception:
        _refund_undelivered("refund_undelivered_unexpected")
        raise


@app.get("/search", response_model=SearchResponse)
def search(
    request: Request,
    user: UserDep,
    origin: str = Query(..., min_length=2, description="Cidade ou IATA"),
    dest: str = Query(..., min_length=2, description="Cidade ou IATA"),
    date: str = Query(..., description="Data de ida YYYY-MM-DD"),
    return_date: str | None = Query(None, description="Data de volta YYYY-MM-DD (ida e volta)"),
    trip_type: str | None = Query(None, description="ida | ida_volta"),
    flex_dates: str | None = Query(
        "off",
        description="off | nearby | weekdays | weekends — estende a busca a datas próximas",
    ),
) -> SearchResponse:
    return _do_search(
        origin=origin,
        dest=dest,
        date=date,
        return_date=return_date,
        trip_type=trip_type,
        flex_dates=flex_dates,
        user=user,
        request=request,
    )


@app.get("/quotes/search", response_model=SearchResponse)
def quotes_search_compat(
    request: Request,
    user: UserDep,
    origin: str = Query(...),
    dest: str = Query(...),
    date: str = Query(...),
    return_date: str | None = Query(None),
    trip_type: str | None = Query(None),
    flex_dates: str | None = Query("off"),
) -> SearchResponse:
    return _do_search(
        origin=origin,
        dest=dest,
        date=date,
        return_date=return_date,
        trip_type=trip_type,
        flex_dates=flex_dates,
        user=user,
        request=request,
    )


@app.get("/airports", response_model=list[AirportHit])
def airports(q: str = Query(..., min_length=1)) -> list[AirportHit]:
    from .normalize import normalizar_texto

    dim = dim_aeroportos()
    raw = q.strip()
    chave = raw.lower()
    nq = normalizar_texto(raw) or chave
    iata_up = raw.upper()

    scored: list[tuple[int, dict]] = []
    for h in dim.to_dicts():
        iata = h["iata"]
        mun = h.get("municipio") or ""
        nome = h.get("nome_aeroporto") or ""
        mun_n = normalizar_texto(mun) or ""
        nome_n = normalizar_texto(nome) or ""
        score = 99
        if iata == iata_up:
            score = 0
        elif iata.startswith(iata_up) and len(iata_up) >= 1:
            score = 1
        elif mun_n == nq:
            score = 2
        elif mun_n.startswith(nq):
            score = 3
        elif nq in mun_n or nq in nome_n or chave in iata.lower():
            score = 4
        else:
            continue
        label = f"{iata} · {mun}"
        if nome:
            curto = nome.replace("International Airport", "Intl").replace("Airport", "").strip(" -")
            if curto and curto.lower() not in mun.lower():
                label = f"{iata} · {mun} — {curto}"
        scored.append(
            (
                score,
                {
                    "iata": iata,
                    "municipio": mun,
                    "nome_aeroporto": nome,
                    "label": label,
                    "value": iata,
                    "kind": "airport",
                },
            )
        )

    scored.sort(key=lambda x: (x[0], x[1]["municipio"], x[1]["iata"]))
    cities: dict[str, list[str]] = {}
    for _, h in scored:
        cities.setdefault(h["municipio"], []).append(h["iata"])
    out: list[AirportHit] = []
    seen_city: set[str] = set()
    for score, h in scored[:30]:
        mun = h["municipio"]
        iatas = cities.get(mun) or []
        if mun not in seen_city and len(iatas) > 1 and score <= 3:
            seen_city.add(mun)
            out.append(
                AirportHit(
                    iata=",".join(sorted(set(iatas))),
                    municipio=mun,
                    nome_aeroporto=None,
                    label=f"{mun} (todos · {', '.join(sorted(set(iatas)))})",
                    value=mun,
                    kind="city",
                )
            )
        out.append(AirportHit(**h))
        if len(out) >= 12:
            break
    return out


@app.get("/flights/detail")
def flights_detail(
    companhia: str | None = Query(None),
    companhia_chave: str | None = Query(None),
    iata_origin: str | None = Query(None),
    iata_destination: str | None = Query(None),
    date: str | None = Query(None, description="YYYY-MM-DD"),
    preco_brl: float | None = Query(None),
):
    try:
        flight = {"preco_brl": preco_brl} if preco_brl is not None else None
        return flight_detail(
            companhia=companhia,
            companhia_chave=companhia_chave,
            iata_origin=iata_origin,
            iata_destination=iata_destination,
            date_str=date,
            flight=flight,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/reliability")
def reliability():
    return airline_reliability()


@app.get("/dashboard", response_model=DashboardSummary)
@app.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard(
    limit: int = Query(10, ge=3, le=25, description="Tamanho dos rankings"),
    min_flights: int = Query(50, ge=1, description="Mínimo de voos no corredor"),
) -> DashboardSummary:
    try:
        return DashboardSummary(**dashboard_summary(limit=limit, min_flights_route=min_flights))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/models/metrics")
def model_metrics():
    return metrics_rows()


@app.post("/admin/reload-spec")
def admin_reload_spec(
    x_vooai_admin_token: str | None = Header(default=None, alias="X-VooAI-Admin-Token"),
):
    expected = os.getenv("VOOAI_ADMIN_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Admin desabilitado: VOOAI_ADMIN_TOKEN ausente.")
    if x_vooai_admin_token != expected:
        raise HTTPException(status_code=401, detail="Token admin inválido.")
    cleared = clear_caches()
    gold = None
    try:
        gold = gold_path()
    except Exception:
        pass
    return {"status": "ok", "cleared": cleared, "gold_file": gold, "db": db_label()}

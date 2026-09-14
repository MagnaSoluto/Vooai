from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .dashboard import dashboard_summary
from .detail import flight_detail
from .models import AirportHit, DashboardSummary, Health, SearchResponse
from .paths import spec_dir
from .search import airline_reliability, simular_viagem
from .spec_store import dim_aeroportos, gold_date_range, gold_path, metrics_rows

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

app = FastAPI(
    title="VooAI API",
    version="0.2.0",
    description="Cotações Google Flights (SerpAPI) cruzadas com Spec materializada (parquet).",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
        spec_dir=str(spec_dir()),
        gold_file=gold,
        gold_date_min=dmin,
        gold_date_max=dmax,
        serpapi_configured=bool(os.getenv("SERPAPI_API_KEY")),
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


@app.get("/search", response_model=SearchResponse)
def search(
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
    volta = return_date
    if trip_type == "ida":
        volta = None
    if trip_type == "ida_volta" and not volta:
        raise HTTPException(status_code=400, detail="Informe return_date para ida e volta.")
    try:
        payload = simular_viagem(origin, dest, date, volta, flex_dates=flex_dates)
        return SearchResponse(**payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/quotes/search", response_model=SearchResponse)
def quotes_search_compat(
    origin: str = Query(...),
    dest: str = Query(...),
    date: str = Query(...),
    return_date: str | None = Query(None),
    trip_type: str | None = Query(None),
    flex_dates: str | None = Query("off"),
) -> SearchResponse:
    return search(
        origin=origin,
        dest=dest,
        date=date,
        return_date=return_date,
        trip_type=trip_type,
        flex_dates=flex_dates,
    )


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

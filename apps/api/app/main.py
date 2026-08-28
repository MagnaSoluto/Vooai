from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .gold import load_all, resolve_gold_dir
from .models import (
    Health,
    ModelMetric,
    Quote,
    QuoteSearch,
    Recommendation,
    Reliability,
    Route,
)

app = FastAPI(
    title="VooAI API",
    version="0.1.0",
    description="Consome a camada Gold exportada. Não treina modelos.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=Health)
def health() -> Health:
    path, source = resolve_gold_dir()
    return Health(status="ok", gold_dir=str(path), source=source)


@app.get("/routes", response_model=list[Route])
def routes() -> list[Route]:
    return [Route(**row) for row in load_all()["routes"] if row["active_mvp"]]


@app.get("/quotes/search", response_model=QuoteSearch)
def quotes_search(
    origin: str = Query(..., min_length=3, max_length=3),
    dest: str = Query(..., min_length=3, max_length=3),
    date: str | None = Query(None, description="YYYY-MM-DD sobre departure_at"),
) -> QuoteSearch:
    origin_u = origin.upper()
    dest_u = dest.upper()
    route_id = f"{origin_u}_{dest_u}"
    data = load_all()
    matched = [
        q
        for q in data["quotes"]
        if q["route_id"] == route_id and (date is None or q["departure_at"].startswith(date))
    ]
    rec = next((r for r in data["recommendations"] if r["route_id"] == route_id), None)
    hist = rec["hist_avg_brl"] if rec else (
        sum(q["price_brl"] for q in matched) / len(matched) if matched else None
    )
    return QuoteSearch(
        origin=origin_u,
        dest=dest_u,
        date=date,
        hist_avg_brl=hist,
        quotes=[Quote(**q) for q in matched],
    )


@app.get("/recommendations/{route_id}", response_model=Recommendation)
def recommendation(route_id: str) -> Recommendation:
    key = route_id.upper()
    row = next((r for r in load_all()["recommendations"] if r["route_id"] == key), None)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Sem recomendação Gold para {key}")
    return Recommendation(**row)


@app.get("/reliability", response_model=list[Reliability])
def reliability(
    airline: str | None = None,
    route: str | None = None,
) -> list[Reliability]:
    rows = load_all()["reliability"]
    if airline:
        code = airline.upper()
        rows = [r for r in rows if r["airline_iata"] == code]
    if route:
        key = route.upper()
        rows = [r for r in rows if r["route_id"] == key]
    return [Reliability(**r) for r in rows]


@app.get("/models/metrics", response_model=list[ModelMetric])
def metrics() -> list[ModelMetric]:
    return [ModelMetric(**row) for row in load_all()["metrics"]]

from __future__ import annotations

from pydantic import BaseModel, Field


class Health(BaseModel):
    status: str
    gold_dir: str
    source: str


class Route(BaseModel):
    route_id: str
    origin: str
    destination: str
    origin_city: str
    destination_city: str
    active_mvp: bool


class Quote(BaseModel):
    quote_id: str
    route_id: str
    airline_iata: str
    collected_at: str
    departure_at: str
    lead_days: int
    price_brl: float
    duration_min: int
    stops: int


class QuoteSearch(BaseModel):
    origin: str
    dest: str
    date: str | None = None
    hist_avg_brl: float | None = None
    quotes: list[Quote]


class Recommendation(BaseModel):
    route_id: str
    current_price_brl: float
    hist_avg_brl: float
    predicted_change_pct: float
    action: str = Field(pattern="^(COMPRAR|AGUARDAR|MONITORAR)$")
    model_confidence: float
    as_of: str


class Reliability(BaseModel):
    airline_iata: str
    route_id: str | None
    delay_rate: float
    cancel_rate: float
    reliability_rank: int
    sample_flights: int


class ModelMetric(BaseModel):
    model_name: str
    family: str
    mae: float
    rmse: float
    r2: float | None
    trained_at: str

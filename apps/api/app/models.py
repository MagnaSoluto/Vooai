from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Health(BaseModel):
    status: str
    spec_dir: str
    gold_file: str | None = None
    gold_date_min: str | None = None
    gold_date_max: str | None = None
    serpapi_configured: bool


class FlightOffer(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = None
    leg: str | None = None
    leg_label: str | None = None
    companhia: str | None = None
    companhia_chave: str | None = None
    flight_numbers: str | None = None
    iata_origin: str | None = None
    iata_destination: str | None = None
    departure_at: str | None = None
    arrival_at: str | None = None
    duration_min: int | None = None
    conexoes: int | None = None
    preco_brl: float | None = None
    tipo_tarifa: str | None = None
    categoria_resultado: str | None = None
    status_match_gold: str | None = None
    score_cancelamento: float | None = None
    score_atraso: float | None = None
    score_risco_operacional: float | None = None
    score_preco_atual: float | None = None
    score_risco_geral: float | None = None
    classificacao_preco: str | None = None
    classificacao_risco_geral: str | None = None
    preco_estimado_modelo: float | None = None
    preco_historico_mediana: float | None = None
    preco_historico_media: float | None = None
    preco_historico_q1: float | None = None
    preco_historico_q3: float | None = None
    hist_empresa_pct_atraso: float | None = None
    hist_empresa_pct_cancelamento: float | None = None
    hist_rota_pct_atraso: float | None = None
    hist_rota_pct_cancelamento: float | None = None
    hist_empresa_rota_pct_atraso: float | None = None
    hist_empresa_rota_pct_cancelamento: float | None = None
    safety_score: float | None = None
    punctuality_pct: float | None = None
    cancel_pct: float | None = None
    action: str = Field(pattern="^(COMPRAR|AGUARDAR|MONITORAR)$")
    predicted_change_pct: float = 0.0
    versao_modelo: str | None = None
    booking_url: str | None = None
    data_voo: str | None = None


class SearchSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    flights_found: int
    outbound_count: int | None = None
    inbound_count: int | None = None
    combo_count: int | None = None
    mixed_count: int | None = None
    lowest_price_brl: float | None = None
    lowest_combo_brl: float | None = None
    lowest_mixed_brl: float | None = None
    avg_punctuality_pct: float | None = None
    avg_safety_score: float | None = None


class RouteScore(BaseModel):
    safety_score: float | None = None
    label: str
    punctuality_pct: float | None = None
    cancel_pct: float | None = None
    price_class: str | None = None
    risk_class: str | None = None


class AirlineScore(BaseModel):
    airline: str
    avg_safety_score: float
    n: int


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    origin: str
    destination: str
    date: str
    return_date: str | None = None
    trip_type: str = "ida"
    iatas_origin: list[str]
    iatas_destination: list[str]
    gold_file: str
    summary: SearchSummary
    route_score: RouteScore
    airline_scores: list[AirlineScore]
    route_performance: dict[str, Any]
    best_option: dict[str, Any] | FlightOffer | None = None
    flights: list[FlightOffer]
    outbound_flights: list[FlightOffer] = []
    inbound_flights: list[FlightOffer] = []
    combo_flights: list[FlightOffer] = []
    mixed_pairs: list[dict[str, Any]] = []


class AirportHit(BaseModel):
    iata: str
    municipio: str
    nome_aeroporto: str | None = None
    label: str
    value: str
    kind: str = "airport"


class DashboardKpis(BaseModel):
    flights_spec: int
    avg_delay_pct: float | None = None
    avg_cancel_pct: float | None = None
    airlines_n: int | None = None
    corridors_n: int | None = None
    gold_date_min: str | None = None
    gold_date_max: str | None = None
    data_referencia: str | None = None


class DashboardAirline(BaseModel):
    airline: str
    flights: int | None = None
    delay_pct: float | None = None
    cancel_pct: float | None = None


class DashboardCorridor(BaseModel):
    origin: str
    destination: str
    flights: int | None = None
    delay_pct: float | None = None
    no_show_pct: float | None = None


class DashboardSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    scope: str = "domestic_br"
    kpis: DashboardKpis
    top_airlines: list[DashboardAirline]
    top_corridors_delay: list[DashboardCorridor]
    top_corridors_no_show: list[DashboardCorridor] = []
    model_metrics: dict[str, Any]
    gold_file: str | None = None

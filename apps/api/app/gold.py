from __future__ import annotations

import csv
import os
from functools import lru_cache
from pathlib import Path


HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[3] if len(HERE.parents) >= 4 else HERE.parents[-1]


def resolve_gold_dir() -> tuple[Path, str]:
    env = os.environ.get("VOOAI_GOLD_DIR")
    sample_env = os.environ.get("VOOAI_GOLD_SAMPLE")
    candidates: list[tuple[Path, str]] = []
    if env:
        candidates.append((Path(env), "env"))
        candidates.append((Path(env) / "sample", "env/sample"))
    if sample_env:
        candidates.append((Path(sample_env), "sample_env"))
    candidates.append((REPO_ROOT / "data" / "gold", "data/gold"))
    candidates.append((REPO_ROOT / "data" / "gold" / "sample", "sample"))
    candidates.append((HERE.parent / "sample", "bundled"))
    for path, source in candidates:
        if (path / "routes.csv").exists():
            return path, source
    return REPO_ROOT / "data" / "gold" / "sample", "sample"


def _read_csv(name: str) -> list[dict[str, str]]:
    directory, _ = resolve_gold_dir()
    path = directory / name
    if not path.exists():
        sample = REPO_ROOT / "data" / "gold" / "sample" / name
        path = sample
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _to_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "sim"}


def _to_float(value: str) -> float | None:
    value = (value or "").strip()
    if value == "":
        return None
    return float(value)


def _to_int(value: str) -> int:
    return int(float(value))


@lru_cache(maxsize=1)
def load_all() -> dict:
    routes = []
    for row in _read_csv("routes.csv"):
        routes.append(
            {
                "route_id": row["route_id"],
                "origin": row["origin"],
                "destination": row["destination"],
                "origin_city": row["origin_city"],
                "destination_city": row["destination_city"],
                "active_mvp": _to_bool(row["active_mvp"]),
            }
        )
    quotes = []
    for row in _read_csv("quotes.csv"):
        quotes.append(
            {
                "quote_id": row["quote_id"],
                "route_id": row["route_id"],
                "airline_iata": row["airline_iata"],
                "collected_at": row["collected_at"],
                "departure_at": row["departure_at"],
                "lead_days": _to_int(row["lead_days"]),
                "price_brl": float(row["price_brl"]),
                "duration_min": _to_int(row["duration_min"]),
                "stops": _to_int(row["stops"]),
            }
        )
    recommendations = []
    for row in _read_csv("recommendations.csv"):
        recommendations.append(
            {
                "route_id": row["route_id"],
                "current_price_brl": float(row["current_price_brl"]),
                "hist_avg_brl": float(row["hist_avg_brl"]),
                "predicted_change_pct": float(row["predicted_change_pct"]),
                "action": row["action"],
                "model_confidence": float(row["model_confidence"]),
                "as_of": row["as_of"],
            }
        )
    reliability = []
    for row in _read_csv("reliability.csv"):
        route = (row.get("route_id") or "").strip()
        reliability.append(
            {
                "airline_iata": row["airline_iata"],
                "route_id": route or None,
                "delay_rate": float(row["delay_rate"]),
                "cancel_rate": float(row["cancel_rate"]),
                "reliability_rank": _to_int(row["reliability_rank"]),
                "sample_flights": _to_int(row["sample_flights"]),
            }
        )
    metrics = []
    for row in _read_csv("model_metrics.csv"):
        metrics.append(
            {
                "model_name": row["model_name"],
                "family": row["family"],
                "mae": float(row["mae"]),
                "rmse": float(row["rmse"]),
                "r2": _to_float(row.get("r2") or ""),
                "trained_at": row["trained_at"],
            }
        )
    return {
        "routes": routes,
        "quotes": quotes,
        "recommendations": recommendations,
        "reliability": reliability,
        "metrics": metrics,
    }

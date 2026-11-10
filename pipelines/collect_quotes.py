"""Collector de cotações → SoR_cotacoes (Bronze de preços).

Roda na box via cron (1–2×/dia). NÃO passa pela API de produto.
Usa o mesmo cliente SerpAPI da API (`apps/api/app/gflights.py`).

Uso:
  python -m pipelines.collect_quotes --lead-days 14
  python -m pipelines.collect_quotes --dry-run --max-routes 2
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import polars as pl

ROOT = Path(__file__).resolve().parents[1]
API_APP = ROOT / "apps" / "api"
if str(API_APP) not in sys.path:
    sys.path.insert(0, str(API_APP))

from app.gflights import cotar_google_flights  # noqa: E402

from .paths import cotacoes_sor_dir, rotas_mvp_md  # noqa: E402


def parse_rotas_mvp(path: Path | None = None) -> list[tuple[str, str, str]]:
    md = path or rotas_mvp_md()
    rows: list[tuple[str, str, str]] = []
    for line in md.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|") or line.startswith("|---") or "route_id" in line:
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 3:
            continue
        route_id, origin, dest = parts[0], parts[1], parts[2]
        if len(origin) != 3 or len(dest) != 3:
            continue
        rows.append((route_id.upper(), origin.upper(), dest.upper()))
    return rows


def _quote_id(route_id: str, airline: str, departure_at: str, price: float, collected: str) -> str:
    raw = f"{route_id}|{airline}|{departure_at}|{price}|{collected}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def collect_route(
    route_id: str,
    origin: str,
    dest: str,
    departure: date,
) -> pl.DataFrame:
    df = cotar_google_flights([origin], [dest], departure, None)
    if df.is_empty():
        return df
    collected = datetime.now(timezone.utc).replace(microsecond=0)
    lead = (departure - collected.date()).days
    rows = []
    for r in df.to_dicts():
        airline = (r.get("companhia_principal_api") or "").strip()
        dep_at = r.get("partida_horario") or ""
        price = float(r["preco_brl"]) if r.get("preco_brl") is not None else None
        if price is None or price <= 0:
            continue
        rows.append(
            {
                "quote_id": _quote_id(route_id, airline, str(dep_at), price, collected.isoformat()),
                "route_id": route_id,
                "origin": origin,
                "destination": dest,
                "airline": airline,
                "airline_iata": None,
                "collected_at": collected.isoformat().replace("+00:00", "Z"),
                "departure_at": str(dep_at) if dep_at else None,
                "departure_date": departure.isoformat(),
                "lead_days": max(lead, 0),
                "price_brl": price,
                "duration_min": r.get("duracao_minutos"),
                "stops": r.get("conexoes"),
                "source": "serpapi_google_flights",
                "flight_numbers": r.get("numeros_voos"),
            }
        )
    return pl.DataFrame(rows) if rows else pl.DataFrame()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collector VooAI → SoR_cotacoes")
    parser.add_argument("--lead-days", type=int, default=14, help="Antecedência da data de voo")
    parser.add_argument("--max-routes", type=int, default=0, help="0 = todas as rotas MVP")
    parser.add_argument("--dry-run", action="store_true", help="Não chama SerpAPI; só lista rotas")
    parser.add_argument("--departure", type=str, default="", help="YYYY-MM-DD (override lead-days)")
    args = parser.parse_args(argv)

    if not os.getenv("SERPAPI_API_KEY") and not args.dry_run:
        print("ERRO: SERPAPI_API_KEY não definida.", file=sys.stderr)
        return 2

    rotas = parse_rotas_mvp()
    if args.max_routes > 0:
        rotas = rotas[: args.max_routes]

    if args.departure:
        dep = date.fromisoformat(args.departure)
    else:
        dep = date.today() + timedelta(days=args.lead_days)

    print(f"rotas={len(rotas)} departure={dep.isoformat()} dry_run={args.dry_run}")
    if args.dry_run:
        for rid, o, d in rotas:
            print(f"  would collect {rid} {o}->{d}")
        return 0

    frames: list[pl.DataFrame] = []
    errors = 0
    for rid, o, d in rotas:
        try:
            df = collect_route(rid, o, d, dep)
            print(f"  {rid}: {df.height} ofertas")
            if df.height:
                frames.append(df)
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"  {rid}: FALHA {exc}", file=sys.stderr)

    if not frames:
        print("Nenhuma cotação gravada.")
        return 1 if errors else 0

    out = pl.concat(frames, how="diagonal_relaxed")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    day = date.today().isoformat()
    dest_dir = cotacoes_sor_dir() / f"dt={day}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"quotes_{stamp}.parquet"
    out.write_parquet(path, compression="zstd")
    print(f"OK → {path} ({out.height} linhas)")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""ETL leve: SoR_cotacoes → SoT_cotacoes → Spec spec_cotacoes.

Agrega preços por rota/cia/dia de coleta para alimentar tendência barata.
NÃO substitui o notebook 09 (risco ANAC) — complementa com série de mercado.

  python -m pipelines.etl_quotes
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from .paths import cotacoes_sor_dir, cotacoes_sot_dir, cotacoes_spec_dir


def _read_all_sor() -> pl.DataFrame:
    root = cotacoes_sor_dir()
    files = sorted(root.rglob("quotes_*.parquet"))
    if not files:
        raise FileNotFoundError(f"Nenhum parquet em {root}. Rode collect_quotes primeiro.")
    return pl.concat([pl.read_parquet(f) for f in files], how="diagonal_relaxed")


def run() -> dict[str, Path]:
    raw = _read_all_sor()
    # Silver: tipagem + dedupe
    silver = (
        raw.with_columns(
            pl.col("route_id").cast(pl.String).str.to_uppercase(),
            pl.col("origin").cast(pl.String).str.to_uppercase(),
            pl.col("destination").cast(pl.String).str.to_uppercase(),
            pl.col("price_brl").cast(pl.Float64),
            pl.col("lead_days").cast(pl.Int32, strict=False),
            pl.col("duration_min").cast(pl.Int32, strict=False),
            pl.col("stops").cast(pl.Int32, strict=False),
        )
        .filter(pl.col("price_brl") > 0)
        .unique(subset=["route_id", "airline", "collected_at", "departure_at", "price_brl"], keep="last")
        .sort(["route_id", "collected_at"])
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    sot = cotacoes_sot_dir()
    sot.mkdir(parents=True, exist_ok=True)
    sot_path = sot / f"cotacoes_{stamp}.parquet"
    silver.write_parquet(sot_path, compression="zstd")

    # Gold leve: stats por rota + lead_days bucket
    gold = (
        silver.with_columns(
            pl.when(pl.col("lead_days") <= 7)
            .then(pl.lit("0_7"))
            .when(pl.col("lead_days") <= 14)
            .then(pl.lit("8_14"))
            .when(pl.col("lead_days") <= 30)
            .then(pl.lit("15_30"))
            .otherwise(pl.lit("31_plus"))
            .alias("lead_bucket")
        )
        .group_by(["route_id", "origin", "destination", "lead_bucket"])
        .agg(
            pl.len().alias("n_quotes"),
            pl.col("price_brl").mean().alias("price_mean_brl"),
            pl.col("price_brl").median().alias("price_median_brl"),
            pl.col("price_brl").min().alias("price_min_brl"),
            pl.col("price_brl").max().alias("price_max_brl"),
            pl.col("price_brl").std().alias("price_std_brl"),
            pl.col("collected_at").max().alias("as_of"),
        )
        .sort(["route_id", "lead_bucket"])
    )

    spec = cotacoes_spec_dir()
    spec.mkdir(parents=True, exist_ok=True)
    gold_path = spec / f"spec_cotacoes_{stamp}.parquet"
    gold.write_parquet(gold_path, compression="zstd")

    print(f"SoT → {sot_path} ({silver.height} linhas)")
    print(f"Spec → {gold_path} ({gold.height} linhas)")
    return {"sot": sot_path, "spec": gold_path}


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(description="ETL cotações SoR→SoT→Spec").parse_args(argv)
    try:
        run()
    except FileNotFoundError as exc:
        print(f"ERRO: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Agregados Spec para o dashboard gerencial (malha doméstica BR)."""

from __future__ import annotations

import glob
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import polars as pl

from .paths import latest_glob, spec_dir
from .spec_store import companhias_hist, gold_date_range, gold_lazy, gold_path

_MES_PT = (
    "",
    "Jan",
    "Fev",
    "Mar",
    "Abr",
    "Mai",
    "Jun",
    "Jul",
    "Ago",
    "Set",
    "Out",
    "Nov",
    "Dez",
)


def _atrasos_hist() -> pl.DataFrame:
    path = latest_glob(str(spec_dir() / "spec_atrasos" / "historico_atrasos_*.parquet"))
    return pl.read_parquet(path)


def _od_hist() -> pl.DataFrame:
    path = latest_glob(
        str(spec_dir() / "spec_origens_destinos" / "historico_origens_destinos_*.parquet")
    )
    return pl.read_parquet(path)


def _datas_hist() -> pl.DataFrame:
    path = latest_glob(str(spec_dir() / "spec_datas" / "historico_datas_*.parquet"))
    return pl.read_parquet(path)


def _all_metrics() -> dict[str, list[dict]]:
    pattern = str(spec_dir() / "spec_metricas_modelos" / "metricas_*.parquet")
    files = glob.glob(pattern)
    classification: list[dict] = []
    price: list[dict] = []
    for f in sorted(files, key=lambda p: Path(p).stat().st_mtime, reverse=True):
        name = Path(f).name.lower()
        rows = pl.read_parquet(f).to_dicts()
        if "classificacao" in name or "risco" in name:
            if not classification:
                classification = rows
        elif "preco" in name or "tarifa" in name:
            if not price:
                price = rows
        else:
            cols = set(rows[0].keys()) if rows else set()
            if {"mae", "rmse"} & cols and not price:
                price = rows
            elif {"roc_auc", "pr_auc"} & cols and not classification:
                classification = rows
    return {"classification": classification, "price": price}


def _latest_ref(df: pl.DataFrame) -> tuple[pl.DataFrame, object | None]:
    if "data_referencia" not in df.columns or df.is_empty():
        return df, None
    ref = df.select(pl.col("data_referencia").max()).item()
    return df.filter(pl.col("data_referencia") == ref), ref


@lru_cache(maxsize=1)
def _seasonality_months() -> list[dict]:
    df, _ = _latest_ref(_datas_hist())
    by = (
        df.group_by("n_mes")
        .agg(
            [
                pl.col("voos_realizados").sum().alias("flights"),
                pl.col("voos_cancelados").sum().alias("canceled"),
                pl.col("pct_no_show").mean().alias("no_show"),
            ]
        )
        .sort("n_mes")
    )
    out = []
    for row in by.to_dicts():
        m = int(row["n_mes"])
        flights = int(row["flights"] or 0)
        canceled = int(row["canceled"] or 0)
        cancel_pct = round((canceled / flights) * 100, 2) if flights else None
        out.append(
            {
                "month": m,
                "label": _MES_PT[m],
                "flights": flights,
                "cancel_pct": cancel_pct,
                "no_show_pct": round(float(row["no_show"] or 0) * 100, 2),
            }
        )
    return out


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, 1)


def _month_end(d: date) -> date:
    nxt = _add_months(date(d.year, d.month, 1), 1)
    return nxt - timedelta(days=1)


@lru_cache(maxsize=1)
def ops_combo_timeline(past_months: int = 6, forecast_months: int = 3) -> dict:
    """Histórico sazonal (meses anteriores) + previsão dia a dia nos próximos meses.

    Reutilizado pelo dashboard e pelo detalhe do voo (mesmo contrato visual).
    """
    datas, _ = _latest_ref(_datas_hist())
    daily_saz = datas.select(
        [
            pl.col("n_mes").cast(pl.Int8),
            pl.col("n_dia").cast(pl.Int8),
            pl.col("voos_realizados").alias("flights"),
            pl.col("voos_cancelados"),
            (pl.col("pct_no_show") * 100).alias("no_show_pct"),
        ]
    ).with_columns(
        (pl.col("voos_cancelados") / pl.col("flights") * 100).alias("cancel_pct")
    )

    season_month = {int(r["month"]): r for r in _seasonality_months()}

    try:
        dmin, _ = gold_date_range()
    except Exception:
        dmin = date.today()
    anchor = date(dmin.year, dmin.month, 1)

    observed: list[dict] = []
    for i in range(past_months, 0, -1):
        mes = _add_months(anchor, -i)
        s = season_month.get(mes.month)
        if not s:
            continue
        observed.append(
            {
                "month": mes.isoformat(),
                "label": f"{_MES_PT[mes.month]}/{str(mes.year)[2:]}",
                "flights": s["flights"],
                "cancel_pct": s["cancel_pct"],
                "no_show_pct": s["no_show_pct"],
                "kind": "observed",
                "source": "spec_datas",
            }
        )

    forecast_end = _add_months(anchor, forecast_months)
    cols = set(gold_lazy().collect_schema().names())
    gold_aggs = []
    if "hist_data_voos_realizados" in cols:
        gold_aggs.append(pl.col("hist_data_voos_realizados").first().alias("flights_gold"))
    else:
        gold_aggs.append(pl.lit(None).alias("flights_gold"))
    if "hist_data_pct_cancelamento" in cols:
        gold_aggs.append(pl.col("hist_data_pct_cancelamento").first().alias("cancel_rate_gold"))
    else:
        gold_aggs.append(pl.lit(None).alias("cancel_rate_gold"))

    gold_day = (
        gold_lazy()
        .filter((pl.col("data_voo") >= dmin) & (pl.col("data_voo") < forecast_end))
        .group_by("data_voo")
        .agg(gold_aggs)
        .collect()
        .with_columns(
            [
                pl.col("data_voo").dt.month().cast(pl.Int8).alias("n_mes"),
                pl.col("data_voo").dt.day().cast(pl.Int8).alias("n_dia"),
            ]
        )
    )

    cal_rows = []
    cur = anchor
    while cur < forecast_end:
        end_m = _month_end(cur)
        d = cur
        while d <= end_m:
            cal_rows.append({"data_voo": d, "n_mes": d.month, "n_dia": d.day})
            d += timedelta(days=1)
        cur = _add_months(cur, 1)

    cal = pl.DataFrame(cal_rows).with_columns(
        [
            pl.col("n_mes").cast(pl.Int8),
            pl.col("n_dia").cast(pl.Int8),
        ]
    )
    joined = (
        cal.join(daily_saz, on=["n_mes", "n_dia"], how="left")
        .join(gold_day, on=["data_voo", "n_mes", "n_dia"], how="left")
        .with_columns(
            [
                pl.coalesce(["flights_gold", "flights"]).alias("flights_day"),
                pl.coalesce([pl.col("cancel_rate_gold") * 100, pl.col("cancel_pct")]).alias(
                    "cancel_day"
                ),
                pl.col("no_show_pct").alias("noshow_day"),
            ]
        )
    )

    day_points = []
    for row in joined.sort("data_voo").to_dicts():
        f = row.get("flights_day")
        if f is None:
            continue
        day_points.append(
            {
                "date": row["data_voo"].isoformat()
                if hasattr(row["data_voo"], "isoformat")
                else str(row["data_voo"]),
                "flights": int(round(float(f))),
                "cancel_pct": round(float(row["cancel_day"] or 0), 2),
                "no_show_pct": round(float(row["noshow_day"] or 0), 2),
            }
        )

    forecast: list[dict] = []
    if day_points:
        df_days = pl.DataFrame(day_points).with_columns(
            pl.col("date").str.to_date().dt.truncate("1mo").alias("mes")
        )
        monthly = (
            df_days.group_by("mes")
            .agg(
                [
                    pl.col("flights").sum().alias("flights"),
                    (
                        (pl.col("cancel_pct") * pl.col("flights")).sum()
                        / pl.col("flights").sum()
                    ).alias("cancel_pct"),
                    (
                        (pl.col("no_show_pct") * pl.col("flights")).sum()
                        / pl.col("flights").sum()
                    ).alias("no_show_pct"),
                    pl.len().alias("days"),
                ]
            )
            .sort("mes")
        )
        for row in monthly.to_dicts():
            mes = row["mes"]
            forecast.append(
                {
                    "month": mes.isoformat(),
                    "label": f"{_MES_PT[mes.month]}/{str(mes.year)[2:]}",
                    "flights": int(row["flights"]),
                    "cancel_pct": round(float(row["cancel_pct"]), 2),
                    "no_show_pct": round(float(row["no_show_pct"]), 2),
                    "kind": "forecast",
                    "source": "day_model_spec+seasonality",
                    "days": int(row["days"]),
                }
            )

    return {
        "anchor": dmin.isoformat(),
        "past_months": past_months,
        "forecast_months": forecast_months,
        "method": (
            "Volume operacional e taxas de cancelamento e no-show. "
            "Barras = voos; linhas = percentuais. "
            "Histórico recente e horizonte de três meses à frente."
        ),
        "series": observed + forecast,
        "forecast_days_sample": (day_points[:10] + day_points[-5:]) if day_points else [],
    }


@lru_cache(maxsize=1)
def _outlook_months() -> list[dict]:
    cols = set(gold_lazy().collect_schema().names())
    select = [pl.col("data_voo")]
    for c in (
        "preco_estimado_modelo",
        "preco_historico_mediana",
        "hist_data_pct_atraso",
        "hist_data_pct_cancelamento",
        "score_risco_operacional",
        "score_risco_base",
    ):
        if c in cols:
            select.append(pl.col(c))

    agg_exprs = [pl.len().alias("n")]
    if "preco_estimado_modelo" in cols:
        agg_exprs.append(pl.col("preco_estimado_modelo").mean().alias("price_forecast"))
    if "preco_historico_mediana" in cols:
        agg_exprs.append(pl.col("preco_historico_mediana").mean().alias("price_median"))
    if "hist_data_pct_atraso" in cols:
        agg_exprs.append((pl.col("hist_data_pct_atraso").mean() * 100).alias("delay_pct"))
    if "hist_data_pct_cancelamento" in cols:
        agg_exprs.append((pl.col("hist_data_pct_cancelamento").mean() * 100).alias("cancel_pct"))
    if "score_risco_operacional" in cols:
        agg_exprs.append(pl.col("score_risco_operacional").mean().alias("risk_score"))
    elif "score_risco_base" in cols:
        agg_exprs.append(pl.col("score_risco_base").mean().alias("risk_score"))

    agg = (
        gold_lazy()
        .select(select)
        .with_columns(pl.col("data_voo").dt.truncate("1mo").alias("mes"))
        .group_by("mes")
        .agg(agg_exprs)
        .sort("mes")
        .collect()
    )

    rows = []
    prev_price = None
    for row in agg.to_dicts():
        mes = row["mes"]
        label = f"{_MES_PT[mes.month]}/{str(mes.year)[2:]}"
        price = row.get("price_forecast")
        mom = None
        if price is not None and prev_price:
            mom = round(((float(price) - float(prev_price)) / float(prev_price)) * 100, 2)
        if price is not None:
            prev_price = float(price)
        rows.append(
            {
                "month": mes.isoformat(),
                "label": label,
                "n": int(row.get("n") or 0),
                "price_forecast": round(float(price), 2) if price is not None else None,
                "price_median": round(float(row["price_median"]), 2)
                if row.get("price_median") is not None
                else None,
                "delay_pct": round(float(row["delay_pct"]), 2)
                if row.get("delay_pct") is not None
                else None,
                "cancel_pct": round(float(row["cancel_pct"]), 2)
                if row.get("cancel_pct") is not None
                else None,
                "risk_score": round(float(row["risk_score"]), 3)
                if row.get("risk_score") is not None
                else None,
                "price_mom_pct": mom,
            }
        )
    return rows


def _br_int(n: int) -> str:
    return f"{int(n):,}".replace(",", ".")


def _br_money(n: float) -> str:
    return f"{float(n):,.0f}".replace(",", ".")


def _story(
    season: list[dict],
    outlook: list[dict],
    delay_avg: float | None,
    ops: dict | None = None,
) -> dict:
    peak_cancel = max(season, key=lambda x: x.get("cancel_pct") or 0) if season else None
    trough_flights = min(season, key=lambda x: x.get("flights") or 0) if season else None
    peak_flights = max(season, key=lambda x: x.get("flights") or 0) if season else None

    cheapest = None
    dearest = None
    riskiest = None
    for row in outlook:
        if row.get("price_forecast") is not None:
            if cheapest is None or row["price_forecast"] < cheapest["price_forecast"]:
                cheapest = row
            if dearest is None or row["price_forecast"] > dearest["price_forecast"]:
                dearest = row
        if row.get("delay_pct") is not None:
            if riskiest is None or row["delay_pct"] > riskiest["delay_pct"]:
                riskiest = row

    bullets = []
    series = (ops or {}).get("series") or []
    forecast_pts = [p for p in series if p.get("kind") == "forecast"]
    if forecast_pts:
        hot = max(forecast_pts, key=lambda x: x.get("cancel_pct") or 0)
        bullets.append(
            f"Nos próximos {len(forecast_pts)} meses (modelo dia a dia), cancelamento previsto "
            f"pico em {hot['label']} ({hot['cancel_pct']}%)."
        )
        vol = max(forecast_pts, key=lambda x: x.get("flights") or 0)
        bullets.append(
            f"Maior volume previsto em {vol['label']} ({_br_int(vol['flights'])} voos no período)."
        )
    if peak_flights and trough_flights:
        bullets.append(
            f"Na sazonalidade da malha, o volume pico é {_MES_PT[peak_flights['month']]} "
            f"({_br_int(peak_flights['flights'])} voos) e o vale é {_MES_PT[trough_flights['month']]}."
        )
    if peak_cancel:
        bullets.append(
            f"Cancelamento histórico sobe em {_MES_PT[peak_cancel['month']]} "
            f"({peak_cancel['cancel_pct']}% dos voos do mês)."
        )
    if cheapest and dearest:
        bullets.append(
            f"No horizonte de preço, tarifa prevista mais baixa em {cheapest['label']} "
            f"(R$ {_br_money(cheapest['price_forecast'])}) e mais alta em {dearest['label']} "
            f"(R$ {_br_money(dearest['price_forecast'])})."
        )
    if delay_avg is not None:
        bullets.append(
            f"Atraso médio ponderado nas companhias da malha: {delay_avg:.1f}%."
        )

    return {
        "headline": "Da sazonalidade ao horizonte de preço e risco.",
        "lede": (
            "Leitura gerencial da malha doméstica: histórico mensal, previsão operacional "
            "e qualidade do sinal de compra."
        ),
        "bullets": bullets[:5],
        "cheapest_month": cheapest["label"] if cheapest else None,
        "riskiest_month": riskiest["label"] if riskiest else None,
    }


def dashboard_summary(limit: int = 10, min_flights_route: int = 50) -> dict:
    limit = max(3, min(limit, 25))
    cias, ref = _latest_ref(companhias_hist())

    voos_totais = int(cias.select(pl.col("voos_totais").sum()).item() or 0)
    w = cias.filter(pl.col("voos_totais") > 0)
    if w.height:
        delay_avg = float(
            (
                w.select((pl.col("pct_atraso") * pl.col("voos_totais")).sum()).item()
                / w.select(pl.col("voos_totais").sum()).item()
            )
            * 100
        )
        cancel_avg = float(
            (
                w.select((pl.col("pct_cancelamento") * pl.col("voos_totais")).sum()).item()
                / w.select(pl.col("voos_totais").sum()).item()
            )
            * 100
        )
    else:
        delay_avg = cancel_avg = None

    dmin = dmax = None
    gold = None
    try:
        gold = gold_path()
        a, b = gold_date_range()
        dmin, dmax = a.isoformat(), b.isoformat()
    except Exception:
        pass

    airlines = (
        cias.sort("voos_totais", descending=True)
        .head(limit)
        .select(
            [
                pl.col("nome_empresa").alias("airline"),
                pl.col("voos_totais").alias("flights"),
                (pl.col("pct_atraso") * 100).round(2).alias("delay_pct"),
                (pl.col("pct_cancelamento") * 100).round(2).alias("cancel_pct"),
            ]
        )
        .to_dicts()
    )

    atrasos, _ = _latest_ref(_atrasos_hist())
    corridors = (
        atrasos.filter(pl.col("voos_totais") >= min_flights_route)
        .sort("pct_atraso", descending=True)
        .head(limit)
        .select(
            [
                pl.col("municipio_origem").alias("origin"),
                pl.col("municipio_destino").alias("destination"),
                pl.col("voos_totais").alias("flights"),
                (pl.col("pct_atraso") * 100).round(2).alias("delay_pct"),
            ]
        )
        .to_dicts()
    )

    od, _ = _latest_ref(_od_hist())
    no_show_hot = (
        od.filter(pl.col("voos_realizados") >= min_flights_route)
        .sort("pct_no_show", descending=True)
        .head(min(5, limit))
        .select(
            [
                pl.col("municipio_origem").alias("origin"),
                pl.col("municipio_destino").alias("destination"),
                pl.col("voos_realizados").alias("flights"),
                (pl.col("pct_no_show") * 100).round(2).alias("no_show_pct"),
            ]
        )
        .to_dicts()
    )

    season = _seasonality_months()
    outlook = _outlook_months()
    ops = ops_combo_timeline(6, 3)
    story = _story(season, outlook, delay_avg, ops)

    return {
        "scope": "domestic_br",
        "kpis": {
            "flights_spec": voos_totais,
            "avg_delay_pct": round(delay_avg, 2) if delay_avg is not None else None,
            "avg_cancel_pct": round(cancel_avg, 2) if cancel_avg is not None else None,
            "airlines_n": cias.height,
            "corridors_n": atrasos.height,
            "gold_date_min": dmin,
            "gold_date_max": dmax,
            "data_referencia": str(ref) if ref is not None else None,
        },
        "story": story,
        "ops_combo": ops,
        "seasonality": season,
        "outlook": outlook,
        "top_airlines": airlines,
        "top_corridors_delay": corridors,
        "top_corridors_no_show": no_show_hot,
        "model_metrics": _all_metrics(),
        "gold_file": gold,
    }

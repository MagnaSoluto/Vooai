"""Histórico Spec para detalhe do voo."""

from __future__ import annotations

from datetime import date
from functools import lru_cache

import polars as pl

from .normalize import expr_companhia_normalizada, expr_texto_normalizado, normalizar_companhia, normalizar_texto
from .paths import latest_glob, spec_dir
from .spec_store import carregar_gold_consulta, dim_aeroportos, gold_date_range, gold_lazy


@lru_cache(maxsize=1)
def _atrasos() -> pl.DataFrame:
    path = latest_glob(str(spec_dir() / "spec_atrasos" / "historico_atrasos_*.parquet"))
    return pl.read_parquet(path).with_columns(
        expr_texto_normalizado("municipio_origem").alias("municipio_origem_chave"),
        expr_texto_normalizado("municipio_destino").alias("municipio_destino_chave"),
    )


@lru_cache(maxsize=1)
def _od() -> pl.DataFrame:
    path = latest_glob(str(spec_dir() / "spec_origens_destinos" / "historico_origens_destinos_*.parquet"))
    return pl.read_parquet(path).with_columns(
        expr_texto_normalizado("municipio_origem").alias("municipio_origem_chave"),
        expr_texto_normalizado("municipio_destino").alias("municipio_destino_chave"),
    )


@lru_cache(maxsize=1)
def _companhias() -> pl.DataFrame:
    path = latest_glob(str(spec_dir() / "spec_companhias" / "historico_companhias_*.parquet"))
    return pl.read_parquet(path).with_columns(
        expr_companhia_normalizada("nome_empresa").alias("companhia_chave")
    )


@lru_cache(maxsize=1)
def _datas() -> pl.DataFrame:
    path = latest_glob(str(spec_dir() / "spec_datas" / "historico_datas_*.parquet"))
    return pl.read_parquet(path)


def _municipio_de_iata(iata: str | None) -> str | None:
    if not iata:
        return None
    dim = dim_aeroportos()
    hit = dim.filter(pl.col("iata") == iata.upper()).select("municipio").head(1)
    if hit.is_empty():
        return None
    return hit["municipio"][0]


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


def _add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    return date(y, m, 1)


def _seasonality_by_month() -> dict[int, dict]:
    by = (
        _datas()
        .group_by("n_mes")
        .agg(
            [
                pl.col("voos_realizados").sum().alias("flights"),
                pl.col("voos_cancelados").sum().alias("canceled"),
                pl.col("pct_no_show").mean().alias("no_show"),
            ]
        )
        .sort("n_mes")
    )
    out: dict[int, dict] = {}
    for row in by.to_dicts():
        m = int(row["n_mes"])
        flights = int(row["flights"] or 0)
        canceled = int(row["canceled"] or 0)
        out[m] = {
            "flights": flights,
            "cancel_pct": round((canceled / flights) * 100, 2) if flights else None,
            "delay_proxy_pct": round(float(row["no_show"] or 0) * 100, 2),
        }
    return out


def _route_airline_baseline(chave: str, chave_o: str, chave_d: str) -> dict:
    """Volume e taxas históricas da companhia nesta rota."""
    cols = set(gold_lazy().collect_schema().names())
    selects = []
    for c in (
        "hist_empresa_rota_voos_realizados",
        "hist_empresa_rota_pct_cancelamento",
        "hist_empresa_rota_pct_atraso",
        "hist_rota_voos_realizados",
    ):
        if c in cols:
            selects.append(pl.col(c).first().alias(c))
    if not selects:
        return {}
    hit = (
        gold_lazy()
        .with_columns(
            [
                expr_texto_normalizado("municipio_origem").alias("ok"),
                expr_texto_normalizado("municipio_destino").alias("dk"),
                expr_companhia_normalizada("nome_empresa").alias("ck"),
            ]
        )
        .filter((pl.col("ck") == chave) & (pl.col("ok") == chave_o) & (pl.col("dk") == chave_d))
        .select(selects)
        .head(1)
        .collect()
    )
    if hit.is_empty():
        return {}
    r = hit.row(0, named=True)
    return {k: r.get(k) for k in r}


def _route_airline_outlook(
    chave: str | None,
    chave_o: str | None,
    chave_d: str | None,
    *,
    past_months: int = 9,
    forecast_months: int = 3,
) -> dict | None:
    """Últimos 9 meses observados + 3 de previsão, filtrado por companhia e rota."""
    if not chave or not chave_o or not chave_d:
        return None

    try:
        dmin, dmax = gold_date_range()
    except Exception:
        dmin, dmax = date.today(), date.today()

    anchor = date.today().replace(day=1)
    season = _seasonality_by_month()
    year_flights = sum(s["flights"] for s in season.values()) or 1
    base = _route_airline_baseline(chave, chave_o, chave_d)
    base_vol = float(base.get("hist_empresa_rota_voos_realizados") or 0)
    base_cancel = base.get("hist_empresa_rota_pct_cancelamento")
    base_delay = base.get("hist_empresa_rota_pct_atraso")

    # Previsão: meses futuros na Spec para esta cia×rota
    cols = set(gold_lazy().collect_schema().names())
    aggs = [pl.len().alias("n_spec")]
    if "preco_estimado_modelo" in cols:
        aggs.append(pl.col("preco_estimado_modelo").median().alias("price_forecast"))
    if "preco_historico_mediana" in cols:
        aggs.append(pl.col("preco_historico_mediana").median().alias("price_median"))
    if "hist_data_pct_atraso" in cols:
        aggs.append((pl.col("hist_data_pct_atraso").mean() * 100).alias("delay_pct"))
    if "hist_data_pct_cancelamento" in cols:
        aggs.append((pl.col("hist_data_pct_cancelamento").mean() * 100).alias("cancel_pct"))

    gold_by_month: dict[str, dict] = {}
    try:
        end_f = _add_months(anchor, forecast_months + 1)
        start_f = max(date(dmin.year, dmin.month, 1), anchor)
        gdf = (
            gold_lazy()
            .with_columns(
                [
                    expr_texto_normalizado("municipio_origem").alias("ok"),
                    expr_texto_normalizado("municipio_destino").alias("dk"),
                    expr_companhia_normalizada("nome_empresa").alias("ck"),
                ]
            )
            .filter(
                (pl.col("ck") == chave)
                & (pl.col("ok") == chave_o)
                & (pl.col("dk") == chave_d)
                & (pl.col("data_voo") >= start_f)
                & (pl.col("data_voo") < end_f)
            )
            .group_by(pl.col("data_voo").dt.truncate("1mo").alias("mes"))
            .agg(aggs)
            .collect()
        )
        for row in gdf.to_dicts():
            mes = row["mes"]
            if hasattr(mes, "isoformat"):
                gold_by_month[mes.isoformat()] = row
    except Exception:
        pass

    series: list[dict] = []

    def _observed_point(mes: date) -> dict:
        saz = season.get(mes.month) or {}
        weight = (saz.get("flights") or 0) / year_flights
        flights = int(round(base_vol * weight)) if base_vol else int(saz.get("flights") or 0)
        # Taxas: sazonalidade do calendário, calibrada pela média histórica cia×rota
        cancel = saz.get("cancel_pct")
        if base_cancel is not None and cancel is not None:
            # mistura leve: 60% calendário + 40% cia×rota
            cancel = round(0.6 * cancel + 0.4 * float(base_cancel) * 100, 2)
        elif base_cancel is not None:
            cancel = round(float(base_cancel) * 100, 2)
        delay = saz.get("delay_proxy_pct")
        if base_delay is not None:
            # atraso cia×rota é o sinal principal; calendário modula ±
            cal = saz.get("delay_proxy_pct") or 0
            avg_cal = sum((season[m]["delay_proxy_pct"] or 0) for m in season) / max(len(season), 1)
            factor = (cal / avg_cal) if avg_cal else 1.0
            delay = round(float(base_delay) * 100 * factor, 2)
        return {
            "month": mes.isoformat(),
            "label": f"{_MES_PT[mes.month]}/{str(mes.year)[2:]}",
            "flights": max(flights, 0),
            "cancel_pct": cancel,
            "delay_pct": delay,
            "kind": "observed",
        }

    def _forecast_point(mes: date) -> dict:
        key = mes.isoformat()
        g = gold_by_month.get(key)
        saz = season.get(mes.month) or {}
        weight = (saz.get("flights") or 0) / year_flights
        flights = int(round(base_vol * weight)) if base_vol else int(saz.get("flights") or 0)
        if g:
            n_spec = int(g.get("n_spec") or 0)
            if base_vol and n_spec:
                flights = int(round(base_vol * (n_spec / 30.0) * weight * 12 / max(len(season), 1)))
            cancel = g.get("cancel_pct")
            delay = g.get("delay_pct")
            if cancel is None and base_cancel is not None:
                cancel = round(float(base_cancel) * 100, 2)
            if delay is None and base_delay is not None:
                delay = round(float(base_delay) * 100, 2)
            return {
                "month": key,
                "label": f"{_MES_PT[mes.month]}/{str(mes.year)[2:]}",
                "flights": max(flights, 0),
                "cancel_pct": round(float(cancel), 2) if cancel is not None else None,
                "delay_pct": round(float(delay), 2) if delay is not None else None,
                "price_forecast": round(float(g["price_forecast"]), 2)
                if g.get("price_forecast") is not None
                else None,
                "price_median": round(float(g["price_median"]), 2)
                if g.get("price_median") is not None
                else None,
                "kind": "forecast",
            }
        # fallback sazonal
        pt = _observed_point(mes)
        pt["kind"] = "forecast"
        return pt

    # 9 meses até o mês atual (inclusive)
    for i in range(past_months - 1, -1, -1):
        series.append(_observed_point(_add_months(anchor, -i)))
    # 3 meses à frente
    for i in range(1, forecast_months + 1):
        series.append(_forecast_point(_add_months(anchor, i)))

    return {
        "scope": "airline_route",
        "companhia_chave": chave,
        "municipio_origem_chave": chave_o,
        "municipio_destino_chave": chave_d,
        "anchor": anchor.isoformat(),
        "past_months": past_months,
        "forecast_months": forecast_months,
        "method": (
            "Volume e taxas de cancelamento e atraso da companhia nesta rota. "
            "Barras indicam volume operacional; linhas, os percentuais. "
            "Janela: 9 meses observados e horizonte de 3 meses."
        ),
        "series": series,
        "line_labels": {
            "cancel_pct": "% cancelamento",
            "delay_pct": "% atraso",
        },
    }


def flight_detail(
    *,
    companhia: str | None,
    companhia_chave: str | None,
    iata_origin: str | None,
    iata_destination: str | None,
    date_str: str | None,
    flight: dict | None = None,
) -> dict:
    chave = companhia_chave or normalizar_companhia(companhia)
    mun_o = _municipio_de_iata(iata_origin)
    mun_d = _municipio_de_iata(iata_destination)
    chave_o = normalizar_texto(mun_o) if mun_o else None
    chave_d = normalizar_texto(mun_d) if mun_d else None

    airline = None
    if chave:
        crows = _companhias().filter(pl.col("companhia_chave") == chave)
        if not crows.is_empty():
            r = crows.row(0, named=True)
            airline = {
                "nome": r.get("nome_empresa"),
                "voos_totais": r.get("voos_totais"),
                "voos_cancelados": r.get("voos_cancelados"),
                "voos_atrasados": r.get("voos_atrasados"),
                "pct_cancelamento": round(float(r.get("pct_cancelamento") or 0) * 100, 2),
                "pct_atraso": round(float(r.get("pct_atraso") or 0) * 100, 2),
                "pct_pontualidade": round((1 - float(r.get("pct_atraso") or 0)) * 100, 2),
            }

    route_delay = None
    route_od = None
    if chave_o and chave_d:
        ar = _atrasos().filter(
            (pl.col("municipio_origem_chave") == chave_o)
            & (pl.col("municipio_destino_chave") == chave_d)
        )
        if not ar.is_empty():
            r = ar.row(0, named=True)
            route_delay = {
                "voos_totais": r.get("voos_totais"),
                "voos_atrasados": r.get("voos_atrasados"),
                "pct_atraso": round(float(r.get("pct_atraso") or 0) * 100, 2),
            }
        od = _od().filter(
            (pl.col("municipio_origem_chave") == chave_o)
            & (pl.col("municipio_destino_chave") == chave_d)
        )
        if not od.is_empty():
            r = od.row(0, named=True)
            route_od = {
                "voos_realizados": r.get("voos_realizados"),
                "voos_cancelados": r.get("voos_cancelados"),
                "pct_no_show": round(float(r.get("pct_no_show") or 0) * 100, 2),
                "pct_cancelamento": round(
                    (float(r.get("voos_cancelados") or 0) / max(float(r.get("voos_realizados") or 1), 1))
                    * 100,
                    2,
                ),
            }

    seasonal = None
    day_hist = None
    if date_str:
        try:
            d = date.fromisoformat(date_str)
            day_hist = _datas().filter((pl.col("n_mes") == d.month) & (pl.col("n_dia") == d.day))
            if not day_hist.is_empty():
                r = day_hist.row(0, named=True)
                seasonal = {
                    "mes": d.month,
                    "dia": d.day,
                    "voos_realizados": r.get("voos_realizados"),
                    "voos_cancelados": r.get("voos_cancelados"),
                    "pct_no_show": round(float(r.get("pct_no_show") or 0) * 100, 2),
                }
        except ValueError:
            pass

    # série operacional desta cia nesta rota (não a malha nacional do dashboard)
    ops_combo = _route_airline_outlook(chave, chave_o, chave_d)

    gold_slice = None
    if date_str and chave and chave_o and chave_d:
        try:
            g = carregar_gold_consulta(date.fromisoformat(date_str))
            hit = g.filter(
                (pl.col("municipio_origem_chave") == chave_o)
                & (pl.col("municipio_destino_chave") == chave_d)
                & (pl.col("companhia_chave") == chave)
            )
            if not hit.is_empty():
                r = hit.row(0, named=True)
                gold_slice = {
                    "score_cancelamento": r.get("score_cancelamento"),
                    "score_atraso": r.get("score_atraso"),
                    "score_risco_operacional": r.get("score_risco_operacional"),
                    "preco_estimado_modelo": r.get("preco_estimado_modelo"),
                    "preco_historico_mediana": r.get("preco_historico_mediana"),
                    "preco_historico_q1": r.get("preco_historico_q1"),
                    "preco_historico_q3": r.get("preco_historico_q3"),
                    "hist_empresa_rota_pct_atraso": r.get("hist_empresa_rota_pct_atraso"),
                    "hist_empresa_rota_pct_cancelamento": r.get("hist_empresa_rota_pct_cancelamento"),
                    "hist_rota_pct_atraso": r.get("hist_rota_pct_atraso"),
                    "hist_rota_pct_cancelamento": r.get("hist_rota_pct_cancelamento"),
                }
        except Exception:
            gold_slice = None

    bars = []
    if airline:
        bars.append({"label": "Pontualidade cia", "value": airline["pct_pontualidade"], "kind": "good"})
        bars.append({"label": "Atraso cia", "value": airline["pct_atraso"], "kind": "warn"})
        bars.append({"label": "Cancel. cia", "value": airline["pct_cancelamento"], "kind": "warn"})
    if route_delay:
        bars.append({"label": "Atraso rota", "value": route_delay["pct_atraso"], "kind": "warn"})
    if route_od:
        bars.append({"label": "No-show rota", "value": route_od["pct_no_show"], "kind": "warn"})
        bars.append({"label": "Cancel. rota", "value": route_od["pct_cancelamento"], "kind": "warn"})

    return {
        "municipio_origem": mun_o,
        "municipio_destino": mun_d,
        "airline": airline,
        "route_delay": route_delay,
        "route_operations": route_od,
        "seasonal": seasonal,
        "gold": gold_slice or (flight and {
            "score_cancelamento": flight.get("score_cancelamento"),
            "score_atraso": flight.get("score_atraso"),
            "preco_estimado_modelo": flight.get("preco_estimado_modelo"),
            "preco_historico_mediana": flight.get("preco_historico_mediana"),
            "preco_historico_q1": flight.get("preco_historico_q1"),
            "preco_historico_q3": flight.get("preco_historico_q3"),
        }),
        "bars": bars,
        "ops_combo": ops_combo,
        "insights": _insights(airline, route_delay, route_od, seasonal, gold_slice, flight),
    }


def _insights(airline, route_delay, route_od, seasonal, gold, flight) -> list[str]:
    tips = []
    if airline:
        tips.append(
            f"{airline['nome']}: pontualidade histórica {airline['pct_pontualidade']}% "
            f"({airline['voos_totais']:,} voos na base).".replace(",", ".")
        )
        if airline["pct_cancelamento"] < 2:
            tips.append("Cancelamento da companhia abaixo de 2% no histórico operacional.")
        elif airline["pct_cancelamento"] > 4:
            tips.append("Cancelamento da companhia acima de 4% — vale considerar alternativas.")
    if route_delay and route_delay["pct_atraso"] is not None:
        if route_delay["pct_atraso"] > 40:
            tips.append(f"Rota com atraso elevado ({route_delay['pct_atraso']}%).")
        elif route_delay["pct_atraso"] < 25:
            tips.append(f"Rota relativamente pontual ({route_delay['pct_atraso']}% atraso).")
    if route_od and route_od["pct_no_show"] is not None:
        tips.append(f"No-show / não realização na rota: {route_od['pct_no_show']}%.")
    if seasonal:
        tips.append(
            f"No dia {seasonal['dia']:02d}/{seasonal['mes']:02d} o histórico mostra "
            f"no-show de {seasonal['pct_no_show']}%."
        )
    if gold and gold.get("preco_historico_q1") and flight and flight.get("preco_brl"):
        if flight["preco_brl"] <= gold["preco_historico_q1"]:
            tips.append("Tarifa na faixa favorável em relação ao histórico da rota.")
        elif gold.get("preco_historico_q3") and flight["preco_brl"] > gold["preco_historico_q3"]:
            tips.append("Tarifa acima do patamar histórico usual desta rota.")
    if not tips:
        tips.append("Histórico limitado para este cruzamento; use o sinal de preço e risco como referência.")
    return tips

"""Orquestra Gflights + Spec (fluxo do notebook 10 + ida/volta em 3 chamadas)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

import polars as pl

from .airlines import booking_urls
from .gflights import cotar_google_flights
from .normalize import expr_companhia_normalizada, expr_texto_normalizado, normalizar_texto
from .paths import spec_dir
from .scoring import (
    adicionar_score_preco,
    adicionar_score_risco_geral,
    decide_action,
    safety_score_10,
)
from .spec_store import (
    carregar_gold_consulta,
    companhias_hist,
    dim_aeroportos,
    gold_date_range,
    gold_lazy,
    gold_path,
    resolver_local_para_iatas,
)

FLEX_MODES = ("off", "nearby", "weekdays", "weekends")
FLEX_RADIUS = 3
FLEX_HINT_THRESHOLD = 0.12  # 12% mais barato na Spec → alerta


def _parse_date(valor: str | date) -> date:
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
    raise ValueError("Data inválida. Use DD/MM/AAAA ou AAAA-MM-DD.")


def _normalize_flex(mode: str | None) -> str:
    m = (mode or "off").strip().lower()
    if m in ("", "false", "0", "none", "no"):
        return "off"
    if m in ("true", "1", "yes", "dias", "days"):
        return "nearby"
    if m not in FLEX_MODES:
        raise ValueError("flex_dates inválido. Use off | nearby | weekdays | weekends.")
    return m


def _expand_dates(
    anchor: date,
    mode: str,
    *,
    radius: int = FLEX_RADIUS,
    dmin: date,
    dmax: date,
    include_anchor: bool = True,
) -> list[date]:
    """Gera datas ao redor do âncora conforme o modo de flexibilidade."""
    out: list[date] = []
    if include_anchor:
        out.append(anchor)
    if mode == "off":
        return out
    for delta in range(-radius, radius + 1):
        if delta == 0:
            continue
        day = anchor + timedelta(days=delta)
        if day < dmin or day > dmax:
            continue
        wd = day.weekday()  # 0=seg … 6=dom
        if mode == "nearby":
            out.append(day)
        elif mode == "weekdays" and wd < 5:
            out.append(day)
        elif mode == "weekends" and wd >= 5:
            out.append(day)
    # âncora primeiro, depois cronológico
    rest = sorted(d for d in out if d != anchor)
    return ([anchor] if include_anchor and anchor >= dmin and anchor <= dmax else []) + rest


def _municipios_from_iatas(iatas: list[str]) -> list[str]:
    dim = dim_aeroportos()
    rows = dim.filter(pl.col("iata").is_in(iatas)).select("municipio").unique().to_series().to_list()
    return [m for m in rows if m]


def _spec_nearby_hint(
    iatas_origem: list[str],
    iatas_destino: list[str],
    data_voo: date,
    best_live_brl: float | None,
    *,
    radius: int = FLEX_RADIUS,
) -> dict | None:
    """Sem gastar SerpAPI: compara mediana Spec da rota em datas ±radius."""
    if best_live_brl is None or best_live_brl <= 0:
        return None
    try:
        dmin, dmax = gold_date_range()
    except Exception:
        return None
    nearby = _expand_dates(
        data_voo, "nearby", radius=radius, dmin=dmin, dmax=dmax, include_anchor=False
    )
    if not nearby:
        return None

    muns_o = [normalizar_texto(m) for m in _municipios_from_iatas(iatas_origem)]
    muns_d = [normalizar_texto(m) for m in _municipios_from_iatas(iatas_destino)]
    if not muns_o or not muns_d:
        return None

    cols = set(gold_lazy().collect_schema().names())
    has_est = "preco_estimado_modelo" in cols
    has_med = "preco_historico_mediana" in cols
    if not has_est and not has_med:
        return None

    aggs = []
    if has_est:
        aggs.append(pl.col("preco_estimado_modelo").median().alias("est"))
    if has_med:
        aggs.append(pl.col("preco_historico_mediana").median().alias("med"))

    def _by_dates(days: list[date]) -> pl.DataFrame:
        return (
            gold_lazy()
            .filter(pl.col("data_voo").is_in(days))
            .with_columns(
                [
                    expr_texto_normalizado("municipio_origem").alias("ok"),
                    expr_texto_normalizado("municipio_destino").alias("dk"),
                ]
            )
            .filter(pl.col("ok").is_in(muns_o) & pl.col("dk").is_in(muns_d))
            .group_by("data_voo")
            .agg(aggs)
            .collect()
        )

    def _ref_row(row: dict) -> float:
        vals = [float(v) for v in (row.get("est"), row.get("med")) if v is not None and float(v) > 0]
        return min(vals) if vals else 0.0

    df = _by_dates(nearby)
    if df.is_empty():
        return None
    rows = [r for r in df.to_dicts() if _ref_row(r) > 0]
    if not rows:
        return None
    rows.sort(key=_ref_row)
    best = rows[0]
    ref = _ref_row(best)
    # Compara com o melhor vivo e, se houver, com a mediana Spec do dia âncora
    baselines = [float(best_live_brl)]
    anchor_df = _by_dates([data_voo])
    if not anchor_df.is_empty():
        anchor_ref = _ref_row(anchor_df.to_dicts()[0])
        if anchor_ref > 0:
            baselines.append(anchor_ref)
    baseline = max(baselines)
    saving = (baseline - ref) / baseline
    if saving < FLEX_HINT_THRESHOLD:
        return None
    day = best["data_voo"]
    return {
        "active": True,
        "message": "Encontramos voos melhores em datas próximas",
        "best_date": day.isoformat() if hasattr(day, "isoformat") else str(day),
        "best_date_label": day.strftime("%d/%m") if hasattr(day, "strftime") else str(day),
        "suggested_flex": "nearby",
        "saving_pct": round(saving * 100, 1),
        "anchor_best_brl": round(float(best_live_brl), 2),
        "nearby_ref_brl": round(ref, 2),
    }


def preparar_api_para_join(df_api: pl.DataFrame) -> pl.DataFrame:
    if df_api.is_empty():
        return df_api
    dim_iata = dim_aeroportos().select(["iata", "municipio"]).unique(subset=["iata"])
    origem = dim_iata.rename({"iata": "iata_origem_voo", "municipio": "municipio_origem_gold"})
    destino = dim_iata.rename({"iata": "iata_destino_voo", "municipio": "municipio_destino_gold"})
    return (
        df_api.join(origem, on="iata_origem_voo", how="left")
        .join(destino, on="iata_destino_voo", how="left")
        .with_columns(
            expr_texto_normalizado("municipio_origem_gold").alias("municipio_origem_chave"),
            expr_texto_normalizado("municipio_destino_gold").alias("municipio_destino_chave"),
            expr_companhia_normalizada("companhia_principal_api").alias("companhia_chave"),
        )
    )


def _enrich_leg(df: pl.DataFrame, data_voo: date, leg: str) -> list[dict]:
    if df.is_empty():
        return []
    df = preparar_api_para_join(df)
    gold = carregar_gold_consulta(data_voo)
    if gold.is_empty():
        resultado = df.with_columns(pl.lit("sem_match_exato").alias("status_match_gold"))
    else:
        resultado = (
            df.join(
                gold,
                on=[
                    "data_voo",
                    "municipio_origem_chave",
                    "municipio_destino_chave",
                    "companhia_chave",
                ],
                how="left",
                suffix="_gold",
            )
            .with_columns(
                pl.when(pl.col("score_cancelamento").is_not_null())
                .then(pl.lit("match_exato"))
                .otherwise(pl.lit("sem_match_exato"))
                .alias("status_match_gold")
            )
        )
        resultado = adicionar_score_preco(resultado)
        resultado = adicionar_score_risco_geral(resultado)
    resultado = resultado.sort(["preco_brl", "score_risco_geral"])
    flights = [_row_to_flight(row, leg=leg) for row in resultado.to_dicts()]
    return flights


def simular_viagem(
    origem: str,
    destino: str,
    data_viagem: str | date,
    data_volta: str | date | None = None,
    flex_dates: str | None = "off",
) -> dict:
    data_voo = _parse_date(data_viagem)
    volta = _parse_date(data_volta) if data_volta else None
    flex = _normalize_flex(flex_dates)
    data_min, data_max = gold_date_range()
    if data_voo < data_min or data_voo > data_max:
        raise ValueError(
            f"A data de ida {data_voo} está fora do período materializado na Spec "
            f"({data_min} a {data_max})."
        )
    if volta is not None:
        if volta < data_voo:
            raise ValueError("A data de volta deve ser igual ou posterior à data de ida.")
        if volta > data_max:
            raise ValueError(
                f"A data de volta {volta} está fora do período materializado na Spec "
                f"(até {data_max})."
            )

    iatas_origem = resolver_local_para_iatas(origem)
    iatas_destino = resolver_local_para_iatas(destino)

    if flex != "off":
        return _simular_flex(
            origem=origem,
            destino=destino,
            data_voo=data_voo,
            data_volta=volta,
            iatas_origem=iatas_origem,
            iatas_destino=iatas_destino,
            flex=flex,
            dmin=data_min,
            dmax=data_max,
        )

    if volta is None:
        df_ida = cotar_google_flights(iatas_origem, iatas_destino, data_voo, None)
        flights_ida = _enrich_leg(df_ida, data_voo, "ida")
        _persist_consulta_rows(flights_ida)
        payload = _build_payload(
            origem=origem,
            destino=destino,
            data_voo=data_voo,
            iatas_origem=iatas_origem,
            iatas_destino=iatas_destino,
            flights_ida=flights_ida,
            flights_volta=[],
            flights_combo=[],
            data_volta=None,
        )
    else:
        with ThreadPoolExecutor(max_workers=3) as pool:
            fut_ida = pool.submit(cotar_google_flights, iatas_origem, iatas_destino, data_voo, None)
            fut_volta = pool.submit(cotar_google_flights, iatas_destino, iatas_origem, volta, None)
            fut_combo = pool.submit(cotar_google_flights, iatas_origem, iatas_destino, data_voo, volta)
            df_ida = fut_ida.result()
            df_volta = fut_volta.result()
            df_combo = fut_combo.result()

        flights_ida = _enrich_leg(df_ida, data_voo, "ida")
        flights_volta = _enrich_leg(df_volta, volta, "volta")
        flights_combo = _enrich_leg(df_combo, data_voo, "combo")
        _persist_consulta_rows(flights_ida + flights_volta + flights_combo)
        payload = _build_payload(
            origem=origem,
            destino=destino,
            data_voo=data_voo,
            iatas_origem=iatas_origem,
            iatas_destino=iatas_destino,
            flights_ida=flights_ida,
            flights_volta=flights_volta,
            flights_combo=flights_combo,
            data_volta=volta,
        )

    best_price = payload.get("summary", {}).get("lowest_price_brl")
    if best_price is None and payload.get("best_option"):
        best_price = payload["best_option"].get("price")
    payload["flex_dates"] = "off"
    payload["dates_searched"] = [data_voo.isoformat()]
    payload["nearby_hint"] = _spec_nearby_hint(
        iatas_origem, iatas_destino, data_voo, best_price
    )
    return payload


def _simular_flex(
    *,
    origem: str,
    destino: str,
    data_voo: date,
    data_volta: date | None,
    iatas_origem: list[str],
    iatas_destino: list[str],
    flex: str,
    dmin: date,
    dmax: date,
) -> dict:
    duration = (data_volta - data_voo).days if data_volta else None
    dates = _expand_dates(data_voo, flex, dmin=dmin, dmax=dmax, include_anchor=True)
    # Limita chamadas SerpAPI (ida: até 7; RT: até 4 âncoras × 3)
    if duration is not None:
        dates = dates[:4]
    else:
        dates = dates[:7]

    flights_ida: list[dict] = []
    flights_volta: list[dict] = []
    flights_combo: list[dict] = []

    def _one_way(day: date) -> list[dict]:
        df = cotar_google_flights(iatas_origem, iatas_destino, day, None)
        return _enrich_leg(df, day, "ida")

    def _rt_bundle(day: date) -> tuple[list[dict], list[dict], list[dict]]:
        ret = day + timedelta(days=duration)
        if ret > dmax:
            return [], [], []
        with ThreadPoolExecutor(max_workers=3) as pool:
            f_ida = pool.submit(cotar_google_flights, iatas_origem, iatas_destino, day, None)
            f_vol = pool.submit(cotar_google_flights, iatas_destino, iatas_origem, ret, None)
            f_cmb = pool.submit(cotar_google_flights, iatas_origem, iatas_destino, day, ret)
            ida = _enrich_leg(f_ida.result(), day, "ida")
            vol = _enrich_leg(f_vol.result(), ret, "volta")
            cmb = _enrich_leg(f_cmb.result(), day, "combo")
        return ida, vol, cmb

    if duration is None:
        with ThreadPoolExecutor(max_workers=min(7, len(dates))) as pool:
            parts = list(pool.map(_one_way, dates))
        for part in parts:
            flights_ida.extend(part)
        volta_payload = None
    else:
        with ThreadPoolExecutor(max_workers=min(4, len(dates))) as pool:
            bundles = list(pool.map(_rt_bundle, dates))
        for ida, vol, cmb in bundles:
            flights_ida.extend(ida)
            flights_volta.extend(vol)
            flights_combo.extend(cmb)
        volta_payload = data_volta

    _persist_consulta_rows(flights_ida + flights_volta + flights_combo)
    payload = _build_payload(
        origem=origem,
        destino=destino,
        data_voo=data_voo,
        iatas_origem=iatas_origem,
        iatas_destino=iatas_destino,
        flights_ida=flights_ida,
        flights_volta=flights_volta,
        flights_combo=flights_combo,
        data_volta=volta_payload,
    )
    payload["flex_dates"] = flex
    payload["dates_searched"] = [d.isoformat() for d in dates]
    payload["nearby_hint"] = None
    # Melhor data dentro do flex (menor preço ida/combo)
    by_date: dict[str, float] = {}
    for f in flights_ida + flights_combo:
        d = f.get("data_voo")
        p = f.get("preco_brl")
        if not d or p is None:
            continue
        key = str(d)[:10]
        by_date[key] = min(by_date.get(key, 1e12), float(p))
    if by_date:
        best_d = min(by_date, key=by_date.get)
        payload["flex_best_date"] = best_d
        payload["flex_best_price_brl"] = by_date[best_d]
    return payload


def _build_mixed_pairs(flights_ida: list[dict], flights_volta: list[dict], limit: int = 25) -> list[dict]:
    if not flights_ida or not flights_volta:
        return []
    top_ida = sorted(flights_ida, key=lambda f: (f.get("preco_brl") or 1e12, -(f.get("safety_score") or 0)))[:12]
    top_volta = sorted(flights_volta, key=lambda f: (f.get("preco_brl") or 1e12, -(f.get("safety_score") or 0)))[:12]
    pairs = []
    for a in top_ida:
        for b in top_volta:
            pa, pb = a.get("preco_brl"), b.get("preco_brl")
            if pa is None or pb is None:
                continue
            same = (a.get("companhia_chave") or "") == (b.get("companhia_chave") or "") and a.get("companhia_chave")
            sa, sb = a.get("safety_score"), b.get("safety_score")
            safety = None
            if sa is not None and sb is not None:
                safety = round((sa + sb) / 2, 1)
            pairs.append(
                {
                    "kind": "same_airline" if same else "mixed",
                    "total_price_brl": round(pa + pb, 2),
                    "safety_score": safety,
                    "outbound": a,
                    "inbound": b,
                    "booking_url_out": a.get("booking_url"),
                    "booking_url_in": b.get("booking_url"),
                }
            )
    pairs.sort(key=lambda p: (p["total_price_brl"], -(p["safety_score"] or 0)))
    # diversificar: priorizar mistos e mesmos, sem flood
    seen = set()
    out = []
    for p in pairs:
        key = (
            p["outbound"].get("flight_numbers"),
            p["outbound"].get("departure_at"),
            p["inbound"].get("flight_numbers"),
            p["inbound"].get("departure_at"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
        if len(out) >= limit:
            break
    return out


def _build_payload(
    origem,
    destino,
    data_voo,
    iatas_origem,
    iatas_destino,
    flights_ida: list[dict],
    flights_volta: list[dict],
    flights_combo: list[dict],
    data_volta=None,
) -> dict:
    all_flights = flights_ida + flights_volta + flights_combo
    matched = [f for f in all_flights if f.get("status_match_gold") == "match_exato"]
    scores = [f["safety_score"] for f in matched if f.get("safety_score") is not None]
    punct = [(1 - f["score_atraso"]) * 100 for f in matched if f.get("score_atraso") is not None]
    cancels = [f["score_cancelamento"] for f in matched if f.get("score_cancelamento") is not None]
    prices = [f["preco_brl"] for f in all_flights if f.get("preco_brl") is not None]
    mixed = _build_mixed_pairs(flights_ida, flights_volta) if data_volta else []
    combo_sorted = sorted(flights_combo, key=lambda f: (f.get("preco_brl") or 1e12, -(f.get("safety_score") or 0)))
    best = _pick_best_overall(flights_ida, flights_volta, combo_sorted, mixed)
    by_airline = _airline_bars(flights_ida + flights_combo)

    return {
        "origin": origem,
        "destination": destino,
        "date": data_voo.isoformat(),
        "return_date": data_volta.isoformat() if data_volta else None,
        "trip_type": "ida_volta" if data_volta else "ida",
        "iatas_origin": iatas_origem,
        "iatas_destination": iatas_destino,
        "gold_file": gold_path(),
        "summary": {
            "flights_found": len(all_flights),
            "outbound_count": len(flights_ida),
            "inbound_count": len(flights_volta),
            "combo_count": len(flights_combo),
            "mixed_count": len(mixed),
            "lowest_price_brl": min(prices) if prices else None,
            "lowest_combo_brl": min((f["preco_brl"] for f in combo_sorted if f.get("preco_brl") is not None), default=None),
            "lowest_mixed_brl": min((p["total_price_brl"] for p in mixed), default=None),
            "avg_punctuality_pct": round(sum(punct) / len(punct), 1) if punct else None,
            "avg_safety_score": round(sum(scores) / len(scores), 1) if scores else None,
        },
        "route_score": {
            "safety_score": best.get("safety_score") if best else (round(sum(scores) / len(scores), 1) if scores else None),
            "label": _safety_label(best.get("safety_score") if best else (sum(scores) / len(scores) if scores else None)),
            "punctuality_pct": round(sum(punct) / len(punct), 1) if punct else None,
            "cancel_pct": round(sum(cancels) / len(cancels) * 100, 1) if cancels else None,
            "price_class": (best.get("flight") or {}).get("classificacao_preco") if best else None,
            "risk_class": (best.get("flight") or {}).get("classificacao_risco_geral") if best else None,
        },
        "airline_scores": by_airline,
        "route_performance": _route_performance(matched),
        "best_option": best,
        "flights": all_flights,
        "outbound_flights": flights_ida,
        "inbound_flights": flights_volta,
        "combo_flights": combo_sorted,
        "mixed_pairs": mixed,
    }


def _pick_best_overall(ida, volta, combo, mixed):
    candidates = []
    if combo:
        c = combo[0]
        candidates.append({"source": "combo", "label": "Combo mesma cia", "price": c.get("preco_brl"), "safety_score": c.get("safety_score"), "flight": c, "pair": None})
    if mixed:
        m = mixed[0]
        candidates.append({"source": "mixed", "label": "Ida + volta montados", "price": m.get("total_price_brl"), "safety_score": m.get("safety_score"), "flight": None, "pair": m})
    if ida and not volta:
        f = _pick_best(ida)
        if f:
            candidates.append({"source": "ida", "label": "Melhor ida", "price": f.get("preco_brl"), "safety_score": f.get("safety_score"), "flight": f, "pair": None})
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: (x["price"] or 1e12, -(x["safety_score"] or 0)))[0]


def _pick_best(flights: list[dict]) -> dict | None:
    if not flights:
        return None
    ranked = sorted(
        flights,
        key=lambda f: (
            0 if f.get("action") == "COMPRAR" else 1 if f.get("action") == "MONITORAR" else 2,
            -(f.get("safety_score") or 0),
            f.get("preco_brl") or 1e12,
            f.get("conexoes") or 0,
        ),
    )
    return ranked[0]


def _airline_bars(flights: list[dict]) -> list[dict]:
    buckets: dict[str, list[float]] = {}
    for f in flights:
        name = f.get("companhia") or "—"
        if f.get("safety_score") is None:
            continue
        buckets.setdefault(name, []).append(float(f["safety_score"]))
    out = [
        {"airline": k, "avg_safety_score": round(sum(v) / len(v), 1), "n": len(v)}
        for k, v in buckets.items()
    ]
    return sorted(out, key=lambda x: -x["avg_safety_score"])


def _route_performance(matched: list[dict]) -> dict:
    if not matched:
        return {"sample_flights": 0}
    atrasos = [f["score_atraso"] for f in matched if f.get("score_atraso") is not None]
    cancels = [f["score_cancelamento"] for f in matched if f.get("score_cancelamento") is not None]
    return {
        "sample_flights": len(matched),
        "avg_delay_pct": round(sum(atrasos) / len(atrasos) * 100, 1) if atrasos else None,
        "avg_cancel_pct": round(sum(cancels) / len(cancels) * 100, 1) if cancels else None,
    }


def _safety_label(score: float | None) -> str:
    if score is None:
        return "Sem score"
    if score >= 8.5:
        return "Alta confiabilidade"
    if score >= 7.0:
        return "Boa confiabilidade"
    if score >= 5.0:
        return "Confiabilidade moderada"
    return "Atenção operacional"


def _row_to_flight(row: dict, leg: str = "ida") -> dict:
    preco = row.get("preco_brl")
    action, change = decide_action(
        preco,
        row.get("preco_estimado_modelo"),
        row.get("preco_historico_mediana"),
        row.get("classificacao_preco"),
    )
    safety = safety_score_10(row.get("score_risco_geral"))
    if safety is None and row.get("score_risco_operacional") is not None:
        safety = safety_score_10(row.get("score_risco_operacional"))
    chave = row.get("companhia_chave")
    out = {
        "id": f"{leg}-{row.get('companhia_principal_api')}-{row.get('partida_horario')}-{row.get('preco_brl')}-{row.get('numeros_voos')}",
        "leg": leg,
        "leg_label": {"ida": "Ida", "volta": "Volta", "combo": "Ida e volta (combo)"}.get(leg, leg),
        "companhia": row.get("companhia_principal_api"),
        "companhia_chave": chave,
        "flight_numbers": row.get("numeros_voos"),
        "iata_origin": row.get("iata_origem_voo"),
        "iata_destination": row.get("iata_destino_voo"),
        "departure_at": row.get("partida_horario"),
        "arrival_at": row.get("chegada_horario"),
        "duration_min": row.get("duracao_minutos"),
        "conexoes": row.get("conexoes"),
        "preco_brl": preco,
        "tipo_tarifa": row.get("tipo_tarifa"),
        "categoria_resultado": row.get("categoria_resultado"),
        "status_match_gold": row.get("status_match_gold"),
        "score_cancelamento": row.get("score_cancelamento"),
        "score_atraso": row.get("score_atraso"),
        "score_risco_operacional": row.get("score_risco_operacional"),
        "score_preco_atual": row.get("score_preco_atual"),
        "score_risco_geral": row.get("score_risco_geral"),
        "classificacao_preco": row.get("classificacao_preco"),
        "classificacao_risco_geral": row.get("classificacao_risco_geral"),
        "preco_estimado_modelo": row.get("preco_estimado_modelo"),
        "preco_historico_mediana": row.get("preco_historico_mediana"),
        "preco_historico_media": row.get("preco_historico_media"),
        "preco_historico_q1": row.get("preco_historico_q1"),
        "preco_historico_q3": row.get("preco_historico_q3"),
        "hist_empresa_pct_atraso": row.get("hist_empresa_pct_atraso"),
        "hist_empresa_pct_cancelamento": row.get("hist_empresa_pct_cancelamento"),
        "hist_rota_pct_atraso": row.get("hist_rota_pct_atraso"),
        "hist_rota_pct_cancelamento": row.get("hist_rota_pct_cancelamento"),
        "hist_empresa_rota_pct_atraso": row.get("hist_empresa_rota_pct_atraso"),
        "hist_empresa_rota_pct_cancelamento": row.get("hist_empresa_rota_pct_cancelamento"),
        "safety_score": safety,
        "punctuality_pct": round((1 - row["score_atraso"]) * 100, 1)
        if row.get("score_atraso") is not None
        else None,
        "cancel_pct": round(row["score_cancelamento"] * 100, 1)
        if row.get("score_cancelamento") is not None
        else None,
        "action": action,
        "predicted_change_pct": change,
        "versao_modelo": row.get("versao_modelo"),
        "data_voo": str(row.get("data_voo") or "")[:10],
        "data_volta": str(row.get("data_volta") or "")[:10] or None,
    }
    urls = booking_urls(
        chave,
        row.get("companhia_principal_api"),
        iata_origin=row.get("iata_origem_voo"),
        iata_destination=row.get("iata_destino_voo"),
        data_voo=row.get("data_voo"),
        data_volta=row.get("data_volta"),
        flight_numbers=row.get("numeros_voos"),
        leg=leg,
    )
    out["booking_url"] = urls.get("google") or urls.get("airline")
    out["booking_url_google"] = urls.get("google")
    out["booking_url_airline"] = urls.get("airline")
    return out


def _persist_consulta_rows(flights: list[dict]) -> None:
    if not flights:
        return
    pasta = Path(spec_dir()) / "spec_resultados" / "consultas_google_flights"
    pasta.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = pasta / f"consulta_voos_{stamp}.parquet"
    try:
        pl.DataFrame(flights).write_parquet(dest, compression="zstd")
    except Exception:
        pass


def airline_reliability() -> list[dict]:
    df = companhias_hist()
    rows = []
    for row in df.sort("pct_atraso").to_dicts():
        rows.append(
            {
                "airline": row.get("nome_empresa"),
                "flights": row.get("voos_totais"),
                "cancel_pct": round(float(row.get("pct_cancelamento") or 0) * 100, 2),
                "delay_pct": round(float(row.get("pct_atraso") or 0) * 100, 2),
            }
        )
    return rows

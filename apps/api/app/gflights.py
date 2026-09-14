"""Cliente SerpAPI Google Flights (notebook 10)."""

from __future__ import annotations

import os
from datetime import date, datetime

import httpx
import polars as pl

URL_SERPAPI = "https://serpapi.com/search.json"


def serpapi_key() -> str:
    chave = os.getenv("SERPAPI_API_KEY", "").strip()
    if not chave:
        raise RuntimeError(
            "SERPAPI_API_KEY não configurada. Defina a variável de ambiente para cotar voos."
        )
    return chave


def cotar_google_flights(
    iatas_origem: list[str],
    iatas_destino: list[str],
    data_voo: date,
    data_volta: date | None = None,
) -> pl.DataFrame:
    origem_param = ",".join(sorted(set(iatas_origem)))
    destino_param = ",".join(sorted(set(iatas_destino)))
    round_trip = data_volta is not None
    params = {
        "engine": "google_flights",
        "departure_id": origem_param,
        "arrival_id": destino_param,
        "outbound_date": data_voo.isoformat(),
        "currency": "BRL",
        "hl": "pt-br",
        "gl": "br",
        "type": "1" if round_trip else "2",
        "show_hidden": "true",
        "api_key": serpapi_key(),
    }
    if round_trip:
        params["return_date"] = data_volta.isoformat()

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.get(URL_SERPAPI, params=params)
            response.raise_for_status()
            results = response.json()
    except httpx.HTTPStatusError as erro:
        raise RuntimeError(
            f"Erro HTTP {erro.response.status_code}: {erro.response.text}"
        ) from erro
    except Exception as erro:
        raise RuntimeError(f"Erro ao consultar SerpApi: {erro}") from erro

    if "error" in results:
        raise RuntimeError(f"Erro retornado pela SerpApi: {results['error']}")

    ofertas: list[tuple[str, dict]] = []
    for categoria in ("best_flights", "other_flights"):
        for oferta in results.get(categoria, []) or []:
            ofertas.append((categoria, oferta))
    if not ofertas:
        return pl.DataFrame()

    linhas = []
    momento = datetime.now()
    for categoria, oferta in ofertas:
        pernas = oferta.get("flights") or []
        if not pernas:
            continue
        primeiro, ultimo = pernas[0], pernas[-1]
        partida = primeiro.get("departure_airport") or {}
        chegada = ultimo.get("arrival_airport") or {}
        companhias: list[str] = []
        numeros: list[str] = []
        for perna in pernas:
            cia = perna.get("airline")
            if cia and cia not in companhias:
                companhias.append(cia)
            num = perna.get("flight_number")
            if num:
                numeros.append(str(num))
        linhas.append(
            {
                "fonte": "GoogleFlights_SerpApi",
                "categoria_resultado": categoria,
                "data_extracao": momento,
                "data_voo": data_voo,
                "data_volta": data_volta,
                "tipo_viagem": "ida_volta" if round_trip else "ida",
                "iata_origem_consulta": origem_param,
                "iata_destino_consulta": destino_param,
                "iata_origem_voo": partida.get("id"),
                "aeroporto_origem_nome": partida.get("name"),
                "iata_destino_voo": chegada.get("id"),
                "aeroporto_destino_nome": chegada.get("name"),
                "companhia_principal_api": primeiro.get("airline"),
                "companhias_itinerario": " + ".join(companhias),
                "numeros_voos": " | ".join(numeros),
                "partida_horario": partida.get("time"),
                "chegada_horario": chegada.get("time"),
                "duracao_minutos": oferta.get("total_duration"),
                "conexoes": max(len(pernas) - 1, 0),
                "preco_brl": oferta.get("price"),
                "tipo_tarifa": oferta.get("type"),
            }
        )
    if not linhas:
        return pl.DataFrame()
    return (
        pl.DataFrame(linhas)
        .with_columns(
            pl.col("data_voo").cast(pl.Date),
            pl.col("preco_brl").cast(pl.Float64, strict=False),
            pl.col("duracao_minutos").cast(pl.Int32, strict=False),
            pl.col("conexoes").cast(pl.Int32, strict=False),
        )
        .filter(pl.col("preco_brl").is_not_null())
        .unique(
            subset=[
                "data_voo",
                "iata_origem_voo",
                "iata_destino_voo",
                "companhia_principal_api",
                "partida_horario",
                "chegada_horario",
                "preco_brl",
            ],
            keep="first",
        )
        .sort(["preco_brl", "duracao_minutos"])
    )

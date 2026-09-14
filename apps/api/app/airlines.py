"""Deep links de compra: rota + data (+ volta), não a home da companhia."""

from __future__ import annotations

import base64
from datetime import date, datetime
from urllib.parse import quote_plus, urlencode


def _as_date(valor: object) -> date | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()[:10]
    try:
        return date.fromisoformat(texto)
    except ValueError:
        return None


def _fmt(d: date, estilo: str) -> str:
    if estilo == "iso":
        return d.isoformat()
    if estilo == "br":
        return d.strftime("%d/%m/%Y")
    if estilo == "br-dash":
        return d.strftime("%d-%m-%Y")
    if estilo == "us":
        return d.strftime("%m/%d/%Y")
    return d.isoformat()


def _pb_varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | 0x80 if n else b)
        if not n:
            break
    return bytes(out)


def _pb_key(field: int, wire: int) -> bytes:
    return _pb_varint((field << 3) | wire)


def _pb_bytes(field: int, data: bytes) -> bytes:
    return _pb_key(field, 2) + _pb_varint(len(data)) + data


def _pb_str(field: int, s: str) -> bytes:
    return _pb_bytes(field, s.encode("utf-8"))


def _pb_var(field: int, n: int) -> bytes:
    return _pb_key(field, 0) + _pb_varint(n)


def _gf_place(iata: str) -> bytes:
    # entity_type=1 (aeroporto) + IATA
    return _pb_var(1, 1) + _pb_str(2, iata.upper())


def _gf_leg(data_iso: str, origem: str, destino: str) -> bytes:
    return (
        _pb_str(2, data_iso)
        + _pb_bytes(13, _gf_place(origem))
        + _pb_bytes(14, _gf_place(destino))
    )


def _google_flights_tfs(
    origem: str,
    destino: str,
    data_ida: date,
    data_volta: date | None = None,
) -> str:
    """Token `tfs` no mesmo formato que o Google Flights / SerpAPI usam."""
    body = b""
    body += _pb_var(1, 28)  # query_mode
    body += _pb_var(2, 2)  # query_context
    body += _pb_bytes(3, _gf_leg(data_ida.isoformat(), origem, destino))
    if data_volta:
        body += _pb_bytes(3, _gf_leg(data_volta.isoformat(), destino, origem))
    body += _pb_var(8, 1)  # 1 adulto
    body += _pb_var(9, 1)  # economy
    body += _pb_var(14, 1)  # display_flag
    body += _pb_var(19, 1 if data_volta else 2)  # 1=RT, 2=OW
    return base64.urlsafe_b64encode(body).decode("ascii").rstrip("=")


def _google_flights_url(
    origem: str,
    destino: str,
    data_ida: date,
    data_volta: date | None = None,
    flight_numbers: str | None = None,
) -> str:
    """Deep link estável: preenche origem, destino e data (token tfs)."""
    tfs = _google_flights_tfs(origem, destino, data_ida, data_volta)
    # tfu=EgIIAQ = estado de busca padrão observado no Google/SerpAPI
    return (
        "https://www.google.com/travel/flights"
        f"?hl=pt-BR&gl=BR&curr=BRL&tfs={tfs}&tfu=EgIIAQ"
    )


def _azul(origem, destino, data_ida, data_volta=None, flight_numbers=None) -> str:
    # Documentado em buscas canônicas Azul (c[0].ds / as / std)
    params = {
        "c[0].ds": origem,
        "c[0].as": destino,
        "c[0].std": _fmt(data_ida, "us"),
        "p[0].t": "ADT",
        "p[0].c": "1",
        "p[0].cp": "false",
        "f.dl": "7",
        "f.dr": "7",
        "cc": "BRL",
    }
    if data_volta:
        params["c[1].ds"] = destino
        params["c[1].as"] = origem
        params["c[1].std"] = _fmt(data_volta, "us")
    # Azul não deep-linka número de voo; mantém busca na data/rota.
    return "https://www.voeazul.com.br/br/pt/home/selecao-voo?" + urlencode(params)


def _gol(origem, destino, data_ida, data_volta=None, flight_numbers=None) -> str | None:
    # Deep link B2C da GOL fora do ar (mesmo na mão). Sem link de busca por ora.
    return None


def _latam(origem, destino, data_ida, data_volta=None, flight_numbers=None) -> str:
    params = {
        "origin": origem,
        "destination": destino,
        "outbound": _fmt(data_ida, "iso"),
        "adt": "1",
        "chd": "0",
        "inf": "0",
        "trip": "RT" if data_volta else "OW",
        "cabin": "Economy",
        "redemption": "false",
        "sort": "RECOMMENDED",
    }
    if data_volta:
        params["inbound"] = _fmt(data_volta, "iso")
    return "https://www.latamairlines.com/br/pt/oferta-voos?" + urlencode(params)


def _tap(origem, destino, data_ida, data_volta=None) -> str:
    params = {
        "tripType": "R" if data_volta else "O",
        "origin": origem,
        "destination": destino,
        "outboundDate": _fmt(data_ida, "iso"),
        "adults": "1",
        "cabinClass": "E",
        "market": "BR",
        "language": "pt",
    }
    if data_volta:
        params["inboundDate"] = _fmt(data_volta, "iso")
    return "https://booking.flytap.com/booking/flights?" + urlencode(params)


def _copa(origem, destino, data_ida, data_volta=None) -> str:
    params = {
        "roundtrip": "true" if data_volta else "false",
        "from": origem,
        "to": destino,
        "departureDate": _fmt(data_ida, "iso"),
        "adults": "1",
        "lang": "pt",
    }
    if data_volta:
        params["returnDate"] = _fmt(data_volta, "iso")
    return "https://www.copaair.com/pt-br/web/guest/home?" + urlencode(params)


def _american(origem, destino, data_ida, data_volta=None) -> str:
    params = {
        "locale": "pt_BR",
        "from": origem,
        "to": destino,
        "departDate": _fmt(data_ida, "iso"),
        "pax": "1",
        "tripType": "roundTrip" if data_volta else "oneWay",
    }
    if data_volta:
        params["returnDate"] = _fmt(data_volta, "iso")
    return "https://www.aa.com/booking/find-flights?" + urlencode(params)


def _delta(origem, destino, data_ida, data_volta=None) -> str:
    params = {
        "originCity": origem,
        "destinationCity": destino,
        "departureDate": _fmt(data_ida, "iso"),
        "adultPassengersCount": "1",
        "tripType": "ROUND_TRIP" if data_volta else "ONE_WAY",
    }
    if data_volta:
        params["returnDate"] = _fmt(data_volta, "iso")
    return "https://www.delta.com/flight-search/book-a-flight?" + urlencode(params)


def _united(origem, destino, data_ida, data_volta=None) -> str:
    params = {
        "f": origem,
        "t": destino,
        "d": _fmt(data_ida, "iso"),
        "tt": "2" if data_volta else "1",
        "sc": "7",
        "px": "1",
    }
    if data_volta:
        params["r"] = _fmt(data_volta, "iso")
    return "https://www.united.com/en/us/fsr/choose-flights?" + urlencode(params)


def _emirates(origem, destino, data_ida, data_volta=None) -> str:
    params = {
        "journeys[0][origin]": origem,
        "journeys[0][destination]": destino,
        "journeys[0][travelDate]": _fmt(data_ida, "iso"),
        "adults": "1",
        "cabinClass": "Y",
    }
    if data_volta:
        params["journeys[1][origin]"] = destino
        params["journeys[1][destination]"] = origem
        params["journeys[1][travelDate]"] = _fmt(data_volta, "iso")
    return "https://www.emirates.com/br/portuguese/book/?" + urlencode(params)


def _air_france(origem, destino, data_ida, data_volta=None) -> str:
    params = {
        "cabinClass": "ECONOMY",
        "pax": "1:0:0:0:0:0:0:0",
        "activeConnection": "0",
        "connections": (
            f"{origem}>{destino}:{_fmt(data_ida, 'iso')}"
            + (f",{destino}>{origem}:{_fmt(data_volta, 'iso')}" if data_volta else "")
        ),
    }
    return "https://wwws.airfrance.com.br/search/offers?" + urlencode(params)


def _klm(origem, destino, data_ida, data_volta=None) -> str:
    params = {
        "cabinClass": "ECONOMY",
        "adults": "1",
        "origin": origem,
        "destination": destino,
        "outboundDate": _fmt(data_ida, "iso"),
    }
    if data_volta:
        params["inboundDate"] = _fmt(data_volta, "iso")
        params["tripType"] = "R"
    else:
        params["tripType"] = "O"
    return "https://www.klm.com.br/search/offers?" + urlencode(params)


def _lufthansa(origem, destino, data_ida, data_volta=None) -> str:
    params = {
        "tripType": "R" if data_volta else "O",
        "origin": origem,
        "destination": destino,
        "outboundDate": _fmt(data_ida, "iso"),
        "adults": "1",
    }
    if data_volta:
        params["inboundDate"] = _fmt(data_volta, "iso")
    return "https://www.lufthansa.com/br/pt/booking/flight-search?" + urlencode(params)


def _iberia(origem, destino, data_ida, data_volta=None) -> str:
    params = {
        "market": "BR",
        "language": "pt",
        "origin": origem,
        "destination": destino,
        "outboundDate": _fmt(data_ida, "iso"),
        "adults": "1",
        "cabin": "Economy",
    }
    if data_volta:
        params["inboundDate"] = _fmt(data_volta, "iso")
        params["tripType"] = "ROUNDTRIP"
    else:
        params["tripType"] = "ONEWAY"
    return "https://www.iberia.com/br/voos/?" + urlencode(params)


def _british(origem, destino, data_ida, data_volta=None) -> str:
    params = {
        "eId": "106087",
        "page": "DEPARTURE",
        "tab_selected": "flight",
        "from": origem,
        "to": destino,
        "depDate": _fmt(data_ida, "iso"),
        "adults": "1",
    }
    if data_volta:
        params["retDate"] = _fmt(data_volta, "iso")
        params["tripType"] = "return"
    else:
        params["tripType"] = "oneWay"
    return "https://www.britishairways.com/travel/book/public/pt_br?" + urlencode(params)


def _qatar(origem, destino, data_ida, data_volta=None) -> str:
    params = {
        "fromStation": origem,
        "toStation": destino,
        "fromDate": _fmt(data_ida, "iso"),
        "adults": "1",
        "tripType": "R" if data_volta else "O",
    }
    if data_volta:
        params["toDate"] = _fmt(data_volta, "iso")
    return "https://www.qatarairways.com/en-br/homepage.html?" + urlencode(params)


def _turkish(origem, destino, data_ida, data_volta=None) -> str:
    params = {
        "portTo": destino,
        "portFrom": origem,
        "dateDeparture": _fmt(data_ida, "iso"),
        "adultCount": "1",
        "tripType": "2" if data_volta else "1",
    }
    if data_volta:
        params["dateReturn"] = _fmt(data_volta, "iso")
    return "https://www.turkishairlines.com/pt-int/flights/booking/?" + urlencode(params)


def _air_europa(origem, destino, data_ida, data_volta=None) -> str:
    params = {
        "origen": origem,
        "destino": destino,
        "fechaIda": _fmt(data_ida, "iso"),
        "adultos": "1",
        "tipoViaje": "R" if data_volta else "O",
    }
    if data_volta:
        params["fechaVuelta"] = _fmt(data_volta, "iso")
    return "https://www.aireuropa.com/br/pt/peg/" + "?" + urlencode(params)


def _aerolineas(origem, destino, data_ida, data_volta=None) -> str:
    params = {
        "triptype": "R" if data_volta else "O",
        "origin": origem,
        "destination": destino,
        "from_date": _fmt(data_ida, "iso"),
        "adults": "1",
    }
    if data_volta:
        params["to_date"] = _fmt(data_volta, "iso")
    return "https://www.aerolineas.com.ar/es-ar/vuelos?" + urlencode(params)


def _sky(origem, destino, data_ida, data_volta=None) -> str:
    params = {
        "origen": origem,
        "destino": destino,
        "fechaIda": _fmt(data_ida, "iso"),
        "adultos": "1",
    }
    if data_volta:
        params["fechaVuelta"] = _fmt(data_volta, "iso")
    return "https://www.skyairline.com/brasil?" + urlencode(params)


def _jetsmart(origem, destino, data_ida, data_volta=None) -> str:
    params = {
        "origin": origem,
        "destination": destino,
        "departureDate": _fmt(data_ida, "iso"),
        "adult": "1",
        "currency": "BRL",
    }
    if data_volta:
        params["returnDate"] = _fmt(data_volta, "iso")
    return "https://jetsmart.com/br/pt/flight-search?" + urlencode(params)


def _air_canada(origem, destino, data_ida, data_volta=None) -> str:
    params = {
        "org0": origem,
        "dest0": destino,
        "departureDate0": _fmt(data_ida, "iso"),
        "ADT": "1",
        "tripType": "R" if data_volta else "O",
    }
    if data_volta:
        params["org1"] = destino
        params["dest1"] = origem
        params["departureDate1"] = _fmt(data_volta, "iso")
    return "https://www.aircanada.com/aeroplan/redeem/availability/calendar?" + urlencode(params)


def _ethiopian(origem, destino, data_ida, data_volta=None) -> str:
    params = {
        "triptype": "roundtrip" if data_volta else "oneway",
        "origin": origem,
        "destination": destino,
        "departureDate": _fmt(data_ida, "iso"),
        "adult": "1",
    }
    if data_volta:
        params["returnDate"] = _fmt(data_volta, "iso")
    return "https://www.ethiopianairlines.com/aa/book?" + urlencode(params)


def _swiss(origem, destino, data_ida, data_volta=None) -> str:
    params = {
        "tripType": "R" if data_volta else "O",
        "origin": origem,
        "destination": destino,
        "outboundDate": _fmt(data_ida, "iso"),
        "adults": "1",
    }
    if data_volta:
        params["inboundDate"] = _fmt(data_volta, "iso")
    return "https://www.swiss.com/br/pt/book?" + urlencode(params)


def _aeromexico(origem, destino, data_ida, data_volta=None) -> str:
    params = {
        "itinerary": "roundtrip" if data_volta else "oneway",
        "origin": origem,
        "destination": destino,
        "departureDate": _fmt(data_ida, "iso"),
        "adults": "1",
    }
    if data_volta:
        params["returnDate"] = _fmt(data_volta, "iso")
    return "https://aeromexico.com/es-mx/reserva?" + urlencode(params)


def _avianca(origem, destino, data_ida, data_volta=None) -> str:
    params = {
        "origen1": origem,
        "destino1": destino,
        "fecha1": _fmt(data_ida, "iso"),
        "adt": "1",
        "tipoViaje": "R" if data_volta else "O",
    }
    if data_volta:
        params["fecha2"] = _fmt(data_volta, "iso")
    return "https://www.avianca.com/br/pt/reserva/?" + urlencode(params)


def _voepass(origem, destino, data_ida, data_volta=None) -> str:
    params = {
        "origem": origem,
        "destino": destino,
        "data_ida": _fmt(data_ida, "iso"),
        "adultos": "1",
    }
    if data_volta:
        params["data_volta"] = _fmt(data_volta, "iso")
    return "https://www.voepass.com.br/?" + urlencode(params)


def _total(origem, destino, data_ida, data_volta=None) -> str:
    params = {
        "origem": origem,
        "destino": destino,
        "ida": _fmt(data_ida, "iso"),
    }
    if data_volta:
        params["volta"] = _fmt(data_volta, "iso")
    return "https://www.total.aero/?" + urlencode(params)


_BUILDERS = {
    "azul": _azul,
    "gol": _gol,
    "latam": _latam,
    "tap portugal": _tap,
    "copa": _copa,
    "american": _american,
    "delta": _delta,
    "united": _united,
    "emirates": _emirates,
    "air france": _air_france,
    "klm": _klm,
    "lufthansa": _lufthansa,
    "iberia": _iberia,
    "british": _british,
    "qatar": _qatar,
    "turkish": _turkish,
    "air europa": _air_europa,
    "aerolineas argentinas": _aerolineas,
    "sky": _sky,
    "jetsmart": _jetsmart,
    "air canada": _air_canada,
    "ethiopian": _ethiopian,
    "swiss": _swiss,
    "aeromexico": _aeromexico,
    "avianca": _avianca,
    "voepass": _voepass,
    "total": _total,
}


def booking_url(
    companhia_chave: str | None = None,
    companhia: str | None = None,
    *,
    iata_origin: str | None = None,
    iata_destination: str | None = None,
    data_voo: object = None,
    data_volta: object = None,
    flight_numbers: str | None = None,
    leg: str | None = None,
) -> str | None:
    """Link principal de compra (Google Flights com rota, data e número do voo)."""
    urls = booking_urls(
        companhia_chave,
        companhia,
        iata_origin=iata_origin,
        iata_destination=iata_destination,
        data_voo=data_voo,
        data_volta=data_volta,
        flight_numbers=flight_numbers,
        leg=leg,
    )
    return urls.get("google") or urls.get("airline")


def booking_urls(
    companhia_chave: str | None = None,
    companhia: str | None = None,
    *,
    iata_origin: str | None = None,
    iata_destination: str | None = None,
    data_voo: object = None,
    data_volta: object = None,
    flight_numbers: str | None = None,
    leg: str | None = None,
) -> dict[str, str | None]:
    """
    google = oferta estável (rota + data no Google Flights).
    airline = busca na companhia (rota + data), quando o deep link público existir.
    """
    chave = (companhia_chave or "").strip().lower()
    origem = (iata_origin or "").strip().upper()
    destino = (iata_destination or "").strip().upper()
    ida = _as_date(data_voo)
    volta = _as_date(data_volta) if (leg == "combo" or data_volta) else None
    if leg in ("ida", "volta"):
        volta = None

    google = None
    airline = None
    if origem and destino and ida:
        google = _google_flights_url(origem, destino, ida, volta, flight_numbers)
        builder = _BUILDERS.get(chave)
        if builder:
            try:
                airline = builder(origem, destino, ida, volta)
            except Exception:
                airline = None
        return {"airline": airline, "google": google, "flight_numbers": flight_numbers}

    alvo = (companhia or chave or "").strip()
    if not alvo:
        g = "https://www.google.com/travel/flights?hl=pt-BR&curr=BRL"
        return {"airline": None, "google": g, "flight_numbers": flight_numbers}
    g = f"https://www.google.com/travel/flights?hl=pt-BR&curr=BRL&q={quote_plus(alvo)}"
    return {"airline": None, "google": g, "flight_numbers": flight_numbers}

"""Normalização de texto e companhias — alinhada ao catálogo Spec (todas as cias)."""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

import polars as pl

# Tokens removidos só como palavra inteira (nunca substring — evita "lufthanSA" → "lufthan").
_TOKENS_RUIDO = (
    "linhas",
    "aereas",
    "aerea",
    "transportes",
    "aereos",
    "companhia",
    "airlines",
    "airline",
    "airways",
    "air",
    "lines",
    "line",
    "royal",
    "dutch",
    "international",
    "intl",
    "service",
    "services",
    "brasil",
    "brazil",
    "brazilian",
    "s",
    "sa",
    "a",
)

# Variantes comuns (Google Flights / ANAC) → chave canônica estável.
# Inclui as big 3 e demais presentes na Spec / malha internacional frequente no BR.
_ALIASES: dict[str, str] = {
    "azul": "azul",
    "latam": "latam",
    "tam": "latam",
    "tam brazilian": "latam",
    "tam brazilian airlines": "latam",
    "lan": "latam",
    "lan airlines": "latam",
    "lan cargo": "latam",
    "lan peru": "latam",
    "tam mercosur": "latam",
    "gol": "gol",
    "gol transportes": "gol",
    "voepass": "voepass",
    "passaredo": "voepass",
    "passaredo transportes": "voepass",
    "avianca": "avianca",
    "avianca aerovias nacionales de colombia": "avianca",
    "tap": "tap portugal",
    "tap portugal": "tap portugal",
    "tap air portugal": "tap portugal",
    "total": "total",
    "total linhas": "total",
    "central american": "central american",
    "central american airlines": "central american",
    "american": "american",
    "american airlines": "american",
    "united": "united",
    "united airlines": "united",
    "delta": "delta",
    "delta air": "delta",
    "delta air lines": "delta",
    "copa": "copa",
    "copa airlines": "copa",
    "emirates": "emirates",
    "air france": "air france",
    "lufthansa": "lufthansa",
    "lufthansa cargo": "lufthansa",
    "qatar": "qatar",
    "qatar airways": "qatar",
    "turkish": "turkish",
    "turkish airlines": "turkish",
    "aerolineas argentinas": "aerolineas argentinas",
    "aerolinea rgentinas": "aerolineas argentinas",  # se "a" token sumir
    "klm": "klm",
    "klm royal dutch": "klm",
    "british": "british",
    "british airways": "british",
    "iberia": "iberia",
    "iberia airlines": "iberia",
    "air europa": "air europa",
    "ethiopian": "ethiopian",
    "ethiopian airlines": "ethiopian",
    "swiss": "swiss",
    "swiss international": "swiss",
    "swissair": "swiss",
    "sky airline": "sky",
    "sky": "sky",
    "jetsmart": "jetsmart",
    "air canada": "air canada",
    "air china": "air china",
    "korean": "korean",
    "korean air": "korean",
    "aeromexico": "aeromexico",
    "aero mexico": "aeromexico",
    "amaszonas": "amaszonas",
    "boliviana": "boliviana",
    "boliviana de aviacion": "boliviana",
    "boliviana de aviacion ob": "boliviana",
    "taag": "taag",
    "taag angola": "taag",
    "hi fly": "hi fly",
    "icelandair": "icelandair",
    "atlas": "atlas air",
    "atlas air": "atlas air",
    "cargolux": "cargolux",
    "tampa": "tampa",
    "phoenix": "phoenix",
    "phoenix air": "phoenix",
    "phoenix air service": "phoenix",
    "abaet": "abaet",
    "totavia": "totavia",
    "ita": "ita",
    "ita airways": "ita",
}


def normalizar_texto(valor: object) -> str | None:
    if valor is None:
        return None
    texto = str(valor).strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^a-z0-9]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto or None


def _tokens_uteis(texto: str) -> list[str]:
    return [t for t in texto.split() if t and t not in _TOKENS_RUIDO]


def _chave_base(valor: object) -> str | None:
    """Texto limpo + aliases explícitos (sem lookup Spec)."""
    texto = normalizar_texto(valor)
    if not texto:
        return None
    if texto in _ALIASES:
        return _ALIASES[texto]
    for tamanho in range(len(texto.split()), 0, -1):
        prefixo = " ".join(texto.split()[:tamanho])
        if prefixo in _ALIASES:
            return _ALIASES[prefixo]
    # Aliases parciais conhecidos
    if "azul" in texto:
        return "azul"
    if "latam" in texto or texto.startswith("tam ") or texto == "tam" or "lan airlines" in texto:
        return "latam"
    if re.search(r"(^| )gol($| )", texto) or "gol linhas" in texto or "gol transportes" in texto:
        return "gol"
    if "voepass" in texto or "passaredo" in texto:
        return "voepass"
    if "avianca" in texto:
        return "avianca"
    if texto.startswith("tap ") or texto == "tap":
        return "tap portugal"
    tokens = _tokens_uteis(texto)
    if not tokens:
        return texto
    reduzido = " ".join(tokens)
    if reduzido in _ALIASES:
        return _ALIASES[reduzido]
    return reduzido


@lru_cache(maxsize=1)
def _catalogo_spec() -> tuple[dict[str, str], dict[str, str]]:
    """
    Retorna (mapa_variante→chave_canonica, mapa_chave→nome_display).
    Carrega todas as companhias da Spec — sem limitar às big 3.
    """
    from .paths import latest_glob, spec_dir

    path = latest_glob(str(spec_dir() / "spec_companhias" / "historico_companhias_*.parquet"))
    df = pl.read_parquet(path).sort("voos_totais", descending=True)
    variante_para_chave: dict[str, str] = {}
    chave_para_nome: dict[str, str] = {}

    for row in df.to_dicts():
        nome = row.get("nome_empresa") or ""
        chave = _chave_base(nome)
        if not chave:
            continue
        chave_para_nome.setdefault(chave, nome)
        bruto = normalizar_texto(nome)
        if bruto:
            variante_para_chave.setdefault(bruto, chave)
        variante_para_chave.setdefault(chave, chave)
        tokens = _tokens_uteis(bruto or "")
        if tokens:
            variante_para_chave.setdefault(" ".join(tokens), chave)
            # primeira palavra significativa (ex.: emirates, copa) se única o suficiente
            if len(tokens[0]) >= 4:
                variante_para_chave.setdefault(tokens[0], chave)

    # aliases manuais sempre vencem / complementam
    for alias, chave in _ALIASES.items():
        variante_para_chave[alias] = chave
        chave_para_nome.setdefault(chave, chave.title())

    return variante_para_chave, chave_para_nome


def normalizar_companhia(valor: object) -> str | None:
    """Resolve nome da API/ANAC para chave canônica do catálogo Spec completo."""
    base = _chave_base(valor)
    if not base:
        return None
    try:
        variantes, _ = _catalogo_spec()
    except Exception:
        return base

    if base in variantes:
        return variantes[base]
    bruto = normalizar_texto(valor)
    if bruto and bruto in variantes:
        return variantes[bruto]

    # Match por contenção: "tap air portugal" ↔ "tap portugal"
    candidatos = []
    for variante, chave in variantes.items():
        if not variante or len(variante) < 3:
            continue
        if base == variante or base in variante or variante in base:
            candidatos.append((len(variante), chave))
    if candidatos:
        candidatos.sort()  # menor variante (mais específica curta) primeiro… na prática preferimos mais voos
        # Preferir chave já canônica do alias se houver
        chaves = {c for _, c in candidatos}
        if len(chaves) == 1:
            return next(iter(chaves))
        # desempate: chave igual à base, senão a de menor comprimento de variante
        for _, chave in candidatos:
            if chave == base:
                return chave
        return candidatos[0][1]
    return base


def nome_display_companhia(chave: str | None) -> str | None:
    if not chave:
        return None
    try:
        _, nomes = _catalogo_spec()
        return nomes.get(chave)
    except Exception:
        return None


def expr_texto_normalizado(coluna: str) -> pl.Expr:
    expr = pl.col(coluna).cast(pl.String).str.to_lowercase().str.strip_chars()
    for padrao, substituto in (
        (r"[áàãâä]", "a"),
        (r"[éèêë]", "e"),
        (r"[íìîï]", "i"),
        (r"[óòõôö]", "o"),
        (r"[úùûü]", "u"),
        (r"ç", "c"),
    ):
        expr = expr.str.replace_all(padrao, substituto)
    return (
        expr.str.replace_all(r"[^a-z0-9]+", " ")
        .str.replace_all(r"\s+", " ")
        .str.strip_chars()
    )


def expr_companhia_normalizada(coluna: str) -> pl.Expr:
    """
    Expressão Polars alinhada ao catálogo: usa map_elements com normalizar_companhia
    para que join Spec↔API cubra todas as cias da base histórica.
    """
    return (
        pl.col(coluna)
        .cast(pl.String)
        .map_elements(normalizar_companhia, return_dtype=pl.Utf8)
    )

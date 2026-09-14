"""Carga Spec (Gold) e dimensão de aeroportos SoT."""

from __future__ import annotations

from datetime import date
from functools import lru_cache

import polars as pl

from .normalize import expr_companhia_normalizada, expr_texto_normalizado, normalizar_texto
from .paths import latest_glob, sot_dir, spec_dir

COLUNAS_GOLD = [
    "data_voo",
    "municipio_origem",
    "municipio_destino",
    "nome_empresa",
    "score_cancelamento",
    "score_atraso",
    "score_risco_operacional",
    "hist_empresa_pct_cancelamento",
    "hist_empresa_pct_atraso",
    "hist_rota_pct_cancelamento",
    "hist_rota_pct_atraso",
    "hist_empresa_rota_pct_cancelamento",
    "hist_empresa_rota_pct_atraso",
    "hist_data_pct_cancelamento",
    "hist_data_pct_atraso",
    "nivel_referencia_preco",
    "preco_estimado_modelo",
    "preco_historico_media",
    "preco_historico_mediana",
    "preco_historico_desvio",
    "preco_historico_q1",
    "preco_historico_q3",
    "preco_historico_iqr",
    "score_volatilidade_preco",
    "score_risco_base",
    "data_processamento",
    "versao_modelo",
]


@lru_cache(maxsize=1)
def gold_path() -> str:
    return str(latest_glob(str(spec_dir() / "spec_modelos_risco" / "spec_modelos_risco_*.parquet")))


@lru_cache(maxsize=1)
def gold_lazy() -> pl.LazyFrame:
    return pl.scan_parquet(gold_path())


@lru_cache(maxsize=1)
def gold_date_range() -> tuple[date, date]:
    row = (
        gold_lazy()
        .select(
            pl.col("data_voo").min().alias("data_min"),
            pl.col("data_voo").max().alias("data_max"),
        )
        .collect()
    )
    return row["data_min"][0], row["data_max"][0]


@lru_cache(maxsize=1)
def dim_aeroportos() -> pl.DataFrame:
    path = latest_glob(str(sot_dir() / "SoT_aeroportos" / "aeroportos_*.parquet"))
    df = pl.read_parquet(path)
    if "servico_regular" in df.columns:
        regular = df.filter(pl.col("servico_regular").cast(pl.String).str.to_lowercase() == "yes")
        if regular.height > 0:
            df = regular
    return (
        df.filter(pl.col("codigo_iata").is_not_null())
        .with_columns(
            pl.col("codigo_iata").cast(pl.String).str.strip_chars().str.to_uppercase().alias("iata"),
            pl.col("municipio").cast(pl.String).str.strip_chars(),
            pl.col("nome_aeroporto").cast(pl.String),
        )
        .with_columns(expr_texto_normalizado("municipio").alias("municipio_chave"))
        .select(["municipio", "municipio_chave", "iata", "nome_aeroporto"])
        .unique()
        .sort(["municipio", "iata"])
    )


@lru_cache(maxsize=1)
def companhias_hist() -> pl.DataFrame:
    path = latest_glob(str(spec_dir() / "spec_companhias" / "historico_companhias_*.parquet"))
    return pl.read_parquet(path)


def resolver_local_para_iatas(local: str) -> list[str]:
    local = str(local).strip()
    if not local:
        raise ValueError("Local não informado.")
    dim = dim_aeroportos()
    if len(local) == 3 and local.isalpha():
        codigo = local.upper()
        encontrados = dim.filter(pl.col("iata") == codigo).select("iata").unique().to_series().to_list()
        if encontrados:
            return encontrados
        raise ValueError(
            f"Aeroporto '{codigo}' fora da malha doméstica BR. Use cidade ou IATA brasileiro."
        )
    chave = normalizar_texto(local)
    if not chave:
        raise ValueError(f"Nenhum aeroporto encontrado para '{local}'.")
    for filtro in (
        pl.col("municipio_chave") == chave,
        pl.col("municipio_chave").str.contains(chave),
        expr_texto_normalizado("nome_aeroporto").str.contains(chave),
    ):
        encontrados = (
            dim.filter(filtro).select("iata").unique().sort("iata").to_series().to_list()
        )
        if encontrados:
            return encontrados
    raise ValueError(f"Nenhum aeroporto encontrado para '{local}'.")


def carregar_gold_consulta(data_voo: date) -> pl.DataFrame:
    schema = set(gold_lazy().collect_schema().names())
    colunas = [c for c in COLUNAS_GOLD if c in schema]
    df = gold_lazy().filter(pl.col("data_voo") == data_voo).select(colunas).collect()
    if df.is_empty():
        return df
    return df.with_columns(
        expr_texto_normalizado("municipio_origem").alias("municipio_origem_chave"),
        expr_texto_normalizado("municipio_destino").alias("municipio_destino_chave"),
        expr_companhia_normalizada("nome_empresa").alias("companhia_chave"),
    )


def metrics_rows() -> list[dict]:
    try:
        path = latest_glob(str(spec_dir() / "spec_metricas_modelos" / "metricas_*.parquet"))
    except FileNotFoundError:
        return []
    df = pl.read_parquet(path)
    return df.to_dicts()

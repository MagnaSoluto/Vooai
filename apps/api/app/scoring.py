"""Scores de preço e risco + ação COMPRAR/AGUARDAR/MONITORAR."""

from __future__ import annotations

import math

import polars as pl

THRESHOLD = 0.05


def adicionar_score_preco(df: pl.DataFrame) -> pl.DataFrame:
    if df.is_empty():
        return df
    for coluna in (
        "preco_historico_iqr",
        "preco_historico_q3",
        "preco_historico_desvio",
        "preco_historico_media",
        "preco_estimado_modelo",
        "preco_historico_q1",
    ):
        if coluna not in df.columns:
            df = df.with_columns(pl.lit(None, dtype=pl.Float64).alias(coluna))

    df = df.with_columns(
        pl.when((pl.col("preco_historico_iqr") > 0) & pl.col("preco_historico_q3").is_not_null())
        .then(((pl.col("preco_brl") - pl.col("preco_historico_q3")) / pl.col("preco_historico_iqr")).clip(lower_bound=0))
        .otherwise(None)
        .alias("_excesso_iqr"),
        pl.when((pl.col("preco_historico_desvio") > 0) & pl.col("preco_historico_media").is_not_null())
        .then(((pl.col("preco_brl") - pl.col("preco_historico_media")) / pl.col("preco_historico_desvio")).clip(lower_bound=0))
        .otherwise(None)
        .alias("_z_preco"),
        pl.when(pl.col("preco_estimado_modelo") > 0)
        .then(((pl.col("preco_brl") / pl.col("preco_estimado_modelo")) - 1).clip(lower_bound=0))
        .otherwise(None)
        .alias("_excesso_modelo"),
    ).with_columns(
        (1 - (-pl.col("_excesso_iqr")).exp()).clip(0, 1).alias("score_preco_iqr"),
        (1 - (-pl.col("_z_preco")).exp()).clip(0, 1).alias("score_preco_desvio"),
        (1 - (-2 * pl.col("_excesso_modelo")).exp()).clip(0, 1).alias("score_preco_modelo"),
    )

    componentes = ["score_preco_iqr", "score_preco_desvio", "score_preco_modelo"]
    soma = pl.sum_horizontal([pl.col(c).fill_null(0) for c in componentes])
    qtd = pl.sum_horizontal([pl.col(c).is_not_null().cast(pl.Int8) for c in componentes])

    return (
        df.with_columns(
            pl.when(qtd > 0).then(soma / qtd).otherwise(None).alias("score_preco_atual")
        )
        .with_columns(
            pl.when(
                pl.col("preco_historico_q1").is_not_null()
                & (pl.col("preco_brl") <= pl.col("preco_historico_q1"))
            )
            .then(pl.lit("favoravel"))
            .when(
                pl.col("preco_historico_q3").is_not_null()
                & (pl.col("preco_brl") <= pl.col("preco_historico_q3"))
            )
            .then(pl.lit("dentro_do_historico"))
            .when(
                pl.col("preco_historico_iqr").is_not_null()
                & pl.col("preco_historico_q3").is_not_null()
                & (
                    pl.col("preco_brl")
                    <= (pl.col("preco_historico_q3") + 1.5 * pl.col("preco_historico_iqr"))
                )
            )
            .then(pl.lit("acima_do_historico"))
            .when(pl.col("preco_historico_q3").is_not_null())
            .then(pl.lit("muito_acima_do_historico"))
            .otherwise(pl.lit("sem_referencia"))
            .alias("classificacao_preco")
        )
    )


def adicionar_score_risco_geral(df: pl.DataFrame) -> pl.DataFrame:
    if df.is_empty():
        return df
    for coluna in ("score_cancelamento", "score_atraso", "score_preco_atual"):
        if coluna not in df.columns:
            df = df.with_columns(pl.lit(None, dtype=pl.Float64).alias(coluna))
    componentes = ["score_cancelamento", "score_atraso", "score_preco_atual"]
    soma = pl.sum_horizontal([pl.col(c).fill_null(0) for c in componentes])
    qtd = pl.sum_horizontal([pl.col(c).is_not_null().cast(pl.Int8) for c in componentes])
    return df.with_columns(
        pl.when(qtd > 0).then(soma / qtd).otherwise(None).alias("score_risco_geral")
    ).with_columns(
        pl.when(pl.col("score_risco_geral") < 0.25)
        .then(pl.lit("baixo"))
        .when(pl.col("score_risco_geral") < 0.50)
        .then(pl.lit("moderado"))
        .when(pl.col("score_risco_geral") < 0.75)
        .then(pl.lit("alto"))
        .when(pl.col("score_risco_geral").is_not_null())
        .then(pl.lit("muito_alto"))
        .otherwise(pl.lit("sem_score"))
        .alias("classificacao_risco_geral")
    )


def safety_score_10(score_risco_geral: float | None) -> float | None:
    if score_risco_geral is None or (isinstance(score_risco_geral, float) and math.isnan(score_risco_geral)):
        return None
    return round(max(0.0, min(10.0, (1.0 - float(score_risco_geral)) * 10.0)), 1)


def decide_action(
    preco_brl: float | None,
    preco_estimado: float | None,
    preco_mediana: float | None,
    classificacao_preco: str | None,
) -> tuple[str, float]:
    """Regra de marca ±5% vs referência do modelo/histórico."""
    ref = preco_estimado if preco_estimado and preco_estimado > 0 else preco_mediana
    change = 0.0
    if ref and preco_brl and preco_brl > 0:
        # ref > preço atual ⇒ expectativa de alta ⇒ COMPRAR agora
        change = (float(ref) - float(preco_brl)) / float(preco_brl)
        if change >= THRESHOLD:
            return "COMPRAR", change
        if change <= -THRESHOLD:
            return "AGUARDAR", change
    if classificacao_preco == "favoravel":
        return "COMPRAR", change
    if classificacao_preco in {"acima_do_historico", "muito_acima_do_historico"}:
        return "AGUARDAR", change
    return "MONITORAR", change

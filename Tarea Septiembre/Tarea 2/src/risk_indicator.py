"""Fase 5 — Indicador de riesgo: adjudicaciones con un solo postor.

Uso:
    python src/risk_indicator.py

Entre los procesos ADJUDICADOS (``n_adjudicaciones > 0``), calcula qué proporción tuvo exactamente UN postor
único (``n_postores_unicos == 1``, columna que ya viene agregada por proceso desde la Fase 1c: cuenta ids
distintos en com_ten_tenderers.csv). Lo reporta por departamento y por comprador, con los `top_n` compradores
de mayor proporción entre los que tienen al menos `min_procesos_adjudicados` (``risk.*`` en config.yaml): con
menos procesos, un comprador con 1 adjudicación y 1 postor ya "es" 100% y domina el ranking sin decir nada
útil — el mínimo evita ese ruido de muestra pequeña.

Este indicador viene de la literatura de integridad en contrataciones (OCP "Red Flags in Public Procurement",
Ojo Público "Funes"). Es una SEÑAL PARA MIRAR MÁS DE CERCA, no evidencia de irregularidad: un solo postor
puede deberse a un mercado con pocos proveedores capaces, a un monto pequeño que no atrae interés, o a una
adjudicación totalmente correcta. No se publican nombres de personas (los "compradores" aquí son SIEMPRE
entidades públicas — municipalidades, gobiernos regionales, ministerios— nunca personas naturales).
"""
from __future__ import annotations

import json
import sys

import pandas as pd

from common import ROOT, get_logger, load_config, now_iso, path

log = get_logger("risk_indicator")

AVISO = ("Una proporción alta de adjudicaciones con un solo postor es una SEÑAL PARA REVISAR, no una prueba de "
         "irregularidad: puede deberse a un mercado con pocos proveedores, a montos pequeños poco atractivos, o a "
         "procesos perfectamente correctos. No se publican nombres de personas naturales.")


def _con_postor_unico(df: pd.DataFrame) -> pd.DataFrame:
    adjudicados = df[df["n_adjudicaciones"] > 0].copy()
    adjudicados["postor_unico"] = adjudicados["n_postores_unicos"].eq(1)
    return adjudicados


def por_grupo(adjudicados: pd.DataFrame, columna: str, minimo: int = 0) -> pd.DataFrame:
    g = adjudicados.groupby(columna).agg(procesos_adjudicados=("ocid", "size"), postor_unico=("postor_unico", "sum"),
                                         monto_adjudicado_total=("monto_adjudicado", "sum"))
    g["share_postor_unico"] = (g["postor_unico"] / g["procesos_adjudicados"]).round(4)
    g = g[g["procesos_adjudicados"] >= minimo].sort_values("share_postor_unico", ascending=False)
    return g.reset_index()


def main() -> int:
    cfg = load_config()
    rcfg = cfg["risk"]
    df = pd.read_parquet(ROOT / cfg["validation"]["output_file"])
    adjudicados = _con_postor_unico(df)
    n_adj = len(adjudicados)
    n_postor_unico = int(adjudicados["postor_unico"].sum())

    por_depto = por_grupo(adjudicados, "departamento")
    por_comprador_todos = por_grupo(adjudicados, "comprador_nombre")
    top_compradores = por_grupo(adjudicados, "comprador_nombre", minimo=rcfg["min_procesos_adjudicados"]).head(rcfg["top_n"])

    con_muestra_suficiente = int((por_comprador_todos["procesos_adjudicados"] >= rcfg["min_procesos_adjudicados"]).sum())
    log.info("Adjudicados: %d | con un solo postor: %d (%.1f%%)", n_adj, n_postor_unico, 100 * n_postor_unico / n_adj if n_adj else 0)
    log.info("Compradores con >= %d procesos adjudicados: %d de %d", rcfg["min_procesos_adjudicados"], con_muestra_suficiente, len(por_comprador_todos))

    resumen = {
        "generado": now_iso(), "aviso": AVISO,
        "procesos_adjudicados": n_adj, "con_un_solo_postor": n_postor_unico,
        "share_global": round(n_postor_unico / n_adj, 4) if n_adj else None,
        "min_procesos_adjudicados_para_ranking": rcfg["min_procesos_adjudicados"], "top_n": rcfg["top_n"],
        "por_departamento": por_depto.to_dict("records"),
        "top_compradores": top_compradores.to_dict("records"),
        "compradores_con_muestra_suficiente": con_muestra_suficiente,
        "compradores_totales": len(por_comprador_todos),
    }
    path(cfg["paths"]["riesgo_json"]).write_text(json.dumps(resumen, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    path(cfg["paths"]["riesgo_md"]).write_text(render_markdown(resumen), encoding="utf-8")
    log.info("Guardado: %s, %s", cfg["paths"]["riesgo_json"], cfg["paths"]["riesgo_md"])
    return 0


def render_markdown(s: dict) -> str:
    L = [
        "# Reporte de riesgo — adjudicaciones con un solo postor",
        "",
        f"Generado: {s['generado']}",
        "",
        f"> {s['aviso']}",
        "",
        f"Procesos adjudicados: **{s['procesos_adjudicados']:,}** · con un solo postor: **{s['con_un_solo_postor']:,}** "
        f"(**{100 * (s['share_global'] or 0):.1f}%**)",
        "",
        "## Por departamento",
        "",
        "| Departamento | Procesos adjudicados | Con un solo postor | % |",
        "|---|---:|---:|---:|",
    ]
    for r in s["por_departamento"]:
        L.append(f"| {r['departamento']} | {r['procesos_adjudicados']:,} | {r['postor_unico']:,} | {100*r['share_postor_unico']:.1f} |")
    L += ["", f"## Top {s['top_n']} compradores (mínimo {s['min_procesos_adjudicados_para_ranking']} procesos adjudicados)",
          "", f"De {s['compradores_totales']:,} compradores, {s['compradores_con_muestra_suficiente']:,} tienen muestra suficiente.", "",
          "| Comprador | Procesos adjudicados | Con un solo postor | % | Monto adjudicado total (S/) |", "|---|---:|---:|---:|---:|"]
    for r in s["top_compradores"]:
        L.append(f"| {r['comprador_nombre']} | {r['procesos_adjudicados']:,} | {r['postor_unico']:,} | "
                 f"{100*r['share_postor_unico']:.1f} | {r['monto_adjudicado_total']:,.0f} |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())

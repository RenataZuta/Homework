"""Fase 1c — De OCDS (releases + records) a una tabla con EXACTAMENTE una fila por ocid.

Uso:
    python src/normalize_records.py

El modelo OCDS en 30 segundos:
- Un proceso de contratación se identifica por su `ocid`.
- Cada vez que el proceso cambia (convocatoria, adjudicación, contrato, corrección...) se publica un
  RELEASE: una "foto" parcial en ese momento. Un mismo ocid tiene muchos releases (aquí ~14 en promedio).
- Un RECORD junta todos los releases de un ocid y trae el `compiledRelease`: el estado ACTUAL del proceso,
  ya fusionado. Es la vista correcta para análisis ("¿cómo está hoy este proceso?").

En los CSV de OECE eso se ve así:
- releases.csv       → una fila por release (historial). NO sirve como tabla base: repetiría cada proceso ~14 veces.
- records.csv        → una fila por ocid con los campos simples del compiledRelease. ES la tabla base.
- com_*.csv          → listas del compiledRelease "aplanadas" (parties, awards, contracts, tenderers, documents...):
                       varias filas por ocid. Se AGREGAN (contar, sumar, concatenar) antes de unirlas.

Resultado: data/processed/procesos.parquet (+ una muestra en CSV) y data/outputs/reporte_normalizacion.json
con cuántas filas había en cada tabla antes y cuántas quedaron después.
"""
from __future__ import annotations

import json
import sys

import pandas as pd

from common import get_logger, load_config, now_iso, path

log = get_logger("normalize_records")

def read_month_table(cfg: dict, table: str) -> pd.DataFrame:
    """Lee la tabla `table` (clave de source.tables en config.yaml) de todos los meses, la concatena,
    anota el mes de origen y acorta los nombres de columna quitando el prefijo de la lista OCDS."""
    spec = cfg["source"]["tables"][table]
    frames = []
    for ym in cfg["bulk"]["months"]:
        f = path(f"{cfg['paths']['raw_extracted']}/{ym}/{spec['file']}")
        if not f.exists():
            raise FileNotFoundError(f"Falta {f}. Ejecuta primero: python src/acquisition_bulk.py")
        df = pd.read_csv(f, dtype=str, encoding="utf-8", keep_default_na=False, na_values=[""])
        df["archivo_mes"] = ym
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    prefix = spec["prefix"]
    if prefix:  # 'compiledRelease/awards/0/value/amount' → 'value_amount'
        df = df.rename(columns=lambda c: c.split(prefix, 1)[1].replace("/", "_") if prefix in c else c)
    return df


def count(counts: dict, cfg: dict, table: str, df: pd.DataFrame, **extra) -> None:
    counts[cfg["source"]["tables"][table]["file"]] = {"filas": len(df), "ocid_unicos": int(df["ocid"].nunique()),
                                                      **extra}


def main() -> int:
    cfg = load_config()
    ncfg = cfg["normalize"]
    counts: dict[str, dict] = {}

    # ── 1) Tabla base: records.csv (compiledRelease) ─────────────────────────
    rec = read_month_table(cfg, "records")
    count(counts, cfg, "records", rec)

    # Un ocid podría aparecer en dos archivos mensuales (si OECE lo re-segmenta). En ese caso nos quedamos
    # con la versión más reciente del compiledRelease y lo REPORTAMOS (no se borra en silencio).
    latest_col = f"compiledRelease/{ncfg['latest_by']}"
    rec = rec.sort_values(latest_col, ascending=False)
    dup_mask = rec["ocid"].duplicated(keep="first")
    duplicados_descartados = rec.loc[dup_mask, ["ocid", "archivo_mes", latest_col]]
    rec = rec.loc[~dup_mask]
    base = rec[list(ncfg["columns"]) + ["archivo_mes"]].rename(columns=ncfg["columns"])
    for c in ncfg["numeric_columns"]:
        base[c] = pd.to_numeric(base[c], errors="coerce")

    # ── 2) Historial: releases.csv → cuántas versiones tuvo cada proceso ─────
    rel = read_month_table(cfg, "releases")
    count(counts, cfg, "releases", rel, releases_por_ocid_promedio=round(len(rel) / rel["ocid"].nunique(), 2))
    agg_rel = rel.groupby("ocid").agg(n_releases=("ocid", "size"),
                                      fecha_primer_release=("releases/0/date", "min"),
                                      fecha_ultimo_release=("releases/0/date", "max"))

    # ── 3) Comprador y su ubicación: com_parties.csv (rol "buyer") ───────────
    par = read_month_table(cfg, "parties")
    count(counts, cfg, "parties", par)
    buyer = par[par["roles"].str.contains(ncfg["buyer_role"], na=False)].drop_duplicates("ocid")
    buyer = buyer.set_index("ocid")[["address_department", "address_region", "address_locality"]].rename(
        columns={"address_department": "departamento_raw", "address_region": "provincia_raw",
                 "address_locality": "distrito_raw"})

    # ── 4) Postores: com_ten_tenderers.csv ───────────────────────────────────
    ten = read_month_table(cfg, "tenderers")
    count(counts, cfg, "tenderers", ten)
    agg_ten = ten.groupby("ocid").agg(n_postores_filas=("id", "size"), n_postores_unicos=("id", "nunique"))

    # ── 5) Adjudicaciones y proveedores ganadores ────────────────────────────
    awa = read_month_table(cfg, "awards")
    count(counts, cfg, "awards", awa)
    awa["value_amount"] = pd.to_numeric(awa["value_amount"], errors="coerce")
    agg_awa = awa.groupby("ocid").agg(n_adjudicaciones=("id", "nunique"),
                                      monto_adjudicado=("value_amount", "sum"))
    sup = read_month_table(cfg, "award_suppliers")
    count(counts, cfg, "award_suppliers", sup)
    agg_sup = sup.groupby("ocid").agg(
        proveedores=("name", lambda s: " | ".join(sorted(set(s.dropna())))),
        proveedores_ids=("id", lambda s: " | ".join(sorted(set(s.dropna())))))

    # ── 6) Contratos ─────────────────────────────────────────────────────────
    con = read_month_table(cfg, "contracts")
    count(counts, cfg, "contracts", con)
    con["value_amount"] = pd.to_numeric(con["value_amount"], errors="coerce")
    agg_con = con.groupby("ocid").agg(n_contratos=("id", "nunique"), monto_contratado=("value_amount", "sum"),
                                      fecha_primer_contrato=("dateSigned", "min"))

    # ── 7) Unir todo a la tabla base (LEFT JOIN: nunca se pierde ni se duplica un ocid) ──
    out = base.set_index("ocid")
    for part in (agg_rel, buyer, agg_ten, agg_awa, agg_sup, agg_con):
        out = out.join(part, how="left")
    out = out.reset_index()
    for c in ("n_releases", "n_postores_filas", "n_postores_unicos", "n_adjudicaciones", "n_contratos"):
        out[c] = out[c].fillna(0).astype(int)
    # Un proceso sin adjudicación/contrato NO tiene monto 0: tiene monto desconocido → NaN, no 0.
    out.loc[out["n_adjudicaciones"] == 0, "monto_adjudicado"] = pd.NA
    out.loc[out["n_contratos"] == 0, "monto_contratado"] = pd.NA

    assert out["ocid"].is_unique, "La tabla final debe tener exactamente una fila por ocid"
    assert len(out) == rec["ocid"].nunique()

    # ── 8) Guardar ───────────────────────────────────────────────────────────
    out.to_parquet(path(ncfg["output_file"]), index=False)
    out.head(ncfg["sample_rows"]).to_csv(path(ncfg["output_csv"]), index=False, encoding="utf-8")

    report = {
        "generado": now_iso(),
        "meses": cfg["bulk"]["months"],
        "antes": counts,
        "despues": {"archivo": ncfg["output_file"], "filas": len(out), "ocid_unicos": int(out["ocid"].nunique()),
                    "columnas": list(out.columns)},
        "ocid_repetidos_entre_meses_descartados": len(duplicados_descartados),
        "detalle_repetidos": duplicados_descartados.head(ncfg["report_max_examples"]).to_dict("records"),
        "por_mes": out["archivo_mes"].value_counts().sort_index().to_dict(),
    }
    path(ncfg["report_file"]).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                                         encoding="utf-8")

    log.info("ANTES: %s", ", ".join(f"{k}={v['filas']} filas" for k, v in counts.items()))
    log.info("DESPUÉS: %d filas = %d ocid únicos (repetidos entre meses descartados: %d) → %s",
             len(out), out["ocid"].nunique(), len(duplicados_descartados), ncfg["output_file"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

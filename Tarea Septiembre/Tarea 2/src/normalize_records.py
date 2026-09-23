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

# Columnas de records.csv que conservamos → nombre corto en español.
RECORD_COLUMNS = {
    "ocid": "ocid",
    "compiledRelease/date": "fecha_compilacion",
    "compiledRelease/dataSegmentation/id": "segmento_mes",
    "compiledRelease/tender/id": "tender_id",
    "compiledRelease/tender/title": "nomenclatura",
    "compiledRelease/tender/description": "descripcion",
    "compiledRelease/tender/procurementMethod": "metodo_ocds",
    "compiledRelease/tender/procurementMethodDetails": "tipo_procedimiento",
    "compiledRelease/tender/mainProcurementCategory": "categoria",
    "compiledRelease/tender/value/amount": "monto_referencial",
    "compiledRelease/tender/value/currency": "moneda",
    "compiledRelease/tender/value/amount_PEN": "monto_referencial_pen",
    "compiledRelease/tender/datePublished": "fecha_convocatoria",
    "compiledRelease/tender/numberOfTenderers": "n_postores_declarado",
    "compiledRelease/planning/budget/amount/amount": "presupuesto",
    "compiledRelease/buyer/id": "comprador_id",
    "compiledRelease/buyer/name": "comprador_nombre",
}
NUMERIC = ["monto_referencial", "monto_referencial_pen", "presupuesto", "n_postores_declarado"]


def read_month_table(cfg: dict, name: str) -> pd.DataFrame:
    """Lee la misma tabla de todos los meses y la concatena, anotando el archivo de origen."""
    frames = []
    for ym in cfg["bulk"]["months"]:
        f = path(f"{cfg['paths']['raw_extracted']}/{ym}/{name}")
        if not f.exists():
            raise FileNotFoundError(f"Falta {f}. Ejecuta primero: python src/acquisition_bulk.py")
        df = pd.read_csv(f, dtype=str, encoding="utf-8", keep_default_na=False, na_values=[""])
        df["archivo_mes"] = ym
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def short(df: pd.DataFrame, prefix: str) -> pd.DataFrame:
    """'compiledRelease/awards/0/value/amount' → 'value_amount' (quita el prefijo de la lista)."""
    return df.rename(columns=lambda c: c.split(prefix, 1)[1].replace("/", "_") if prefix in c else c)


def main() -> int:
    cfg = load_config()
    ncfg = cfg["normalize"]
    counts: dict[str, dict] = {}

    # ── 1) Tabla base: records.csv (compiledRelease) ─────────────────────────
    rec = read_month_table(cfg, "records.csv")
    counts["records.csv"] = {"filas": len(rec), "ocid_unicos": int(rec["ocid"].nunique())}

    # Un ocid podría aparecer en dos archivos mensuales (si OECE lo re-segmenta). En ese caso nos quedamos
    # con la versión más reciente del compiledRelease y lo REPORTAMOS (no se borra en silencio).
    latest_col = f"compiledRelease/{ncfg['latest_by']}"
    rec = rec.sort_values(latest_col, ascending=False)
    dup_mask = rec["ocid"].duplicated(keep="first")
    duplicados_descartados = rec.loc[dup_mask, ["ocid", "archivo_mes", latest_col]]
    rec = rec.loc[~dup_mask]
    base = rec[list(RECORD_COLUMNS) + ["archivo_mes"]].rename(columns=RECORD_COLUMNS)
    for c in NUMERIC:
        base[c] = pd.to_numeric(base[c], errors="coerce")

    # ── 2) Historial: releases.csv → cuántas versiones tuvo cada proceso ─────
    rel = read_month_table(cfg, "releases.csv")
    counts["releases.csv"] = {"filas": len(rel), "ocid_unicos": int(rel["ocid"].nunique()),
                              "releases_por_ocid_promedio": round(len(rel) / rel["ocid"].nunique(), 2)}
    agg_rel = rel.groupby("ocid").agg(n_releases=("ocid", "size"),
                                      fecha_primer_release=("releases/0/date", "min"),
                                      fecha_ultimo_release=("releases/0/date", "max"))

    # ── 3) Comprador y su ubicación: com_parties.csv (rol "buyer") ───────────
    par = short(read_month_table(cfg, "com_parties.csv"), "parties/0/")
    counts["com_parties.csv"] = {"filas": len(par), "ocid_unicos": int(par["ocid"].nunique())}
    buyer = par[par["roles"].str.contains("buyer", na=False)].drop_duplicates("ocid")
    buyer = buyer.set_index("ocid")[["address_department", "address_region", "address_locality"]].rename(
        columns={"address_department": "departamento_raw", "address_region": "provincia_raw",
                 "address_locality": "distrito_raw"})

    # ── 4) Postores: com_ten_tenderers.csv ───────────────────────────────────
    ten = short(read_month_table(cfg, "com_ten_tenderers.csv"), "tenderers/0/")
    counts["com_ten_tenderers.csv"] = {"filas": len(ten), "ocid_unicos": int(ten["ocid"].nunique())}
    agg_ten = ten.groupby("ocid").agg(n_postores_filas=("id", "size"), n_postores_unicos=("id", "nunique"))

    # ── 5) Adjudicaciones y proveedores ganadores ────────────────────────────
    awa = short(read_month_table(cfg, "com_awards.csv"), "awards/0/")
    counts["com_awards.csv"] = {"filas": len(awa), "ocid_unicos": int(awa["ocid"].nunique())}
    awa["value_amount"] = pd.to_numeric(awa["value_amount"], errors="coerce")
    agg_awa = awa.groupby("ocid").agg(n_adjudicaciones=("id", "nunique"),
                                      monto_adjudicado=("value_amount", "sum"))
    sup = short(read_month_table(cfg, "com_awa_suppliers.csv"), "suppliers/0/")
    counts["com_awa_suppliers.csv"] = {"filas": len(sup), "ocid_unicos": int(sup["ocid"].nunique())}
    agg_sup = sup.groupby("ocid").agg(
        proveedores=("name", lambda s: " | ".join(sorted(set(s.dropna())))),
        proveedores_ids=("id", lambda s: " | ".join(sorted(set(s.dropna())))))

    # ── 6) Contratos ─────────────────────────────────────────────────────────
    con = short(read_month_table(cfg, "com_contracts.csv"), "contracts/0/")
    counts["com_contracts.csv"] = {"filas": len(con), "ocid_unicos": int(con["ocid"].nunique())}
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
    assert len(out) == counts["records.csv"]["ocid_unicos"]

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
        "detalle_repetidos": duplicados_descartados.head(50).to_dict("records"),
        "por_mes": out["archivo_mes"].value_counts().sort_index().to_dict(),
    }
    path(ncfg["report_file"]).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                                         encoding="utf-8")

    log.info("ANTES: releases.csv=%d filas (%.1f por ocid) | records.csv=%d filas | tablas hijas: %s",
             counts["releases.csv"]["filas"], counts["releases.csv"]["releases_por_ocid_promedio"],
             counts["records.csv"]["filas"],
             ", ".join(f"{k}={v['filas']}" for k, v in counts.items() if k.startswith("com_")))
    log.info("DESPUÉS: %d filas = %d ocid únicos (repetidos entre meses descartados: %d) → %s",
             len(out), out["ocid"].nunique(), len(duplicados_descartados), ncfg["output_file"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

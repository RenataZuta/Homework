"""Fase 2a — Validación de calidad + normalización territorial + informe.

Uso:
    python src/validation.py

Principio: NADA se elimina en silencio. Cada regla añade una columna `flag_<regla>` (True/False) a la tabla
de procesos y una fila al informe (data/outputs/reporte_calidad.md y .json) con: cuántos registros marcó,
sobre cuántos, y qué se hizo. Quien use los datos después (Fases 3-5) decide si filtra por esas columnas.

Reglas:
  R1  ocid duplicado                               (records.csv de todos los meses + tabla final)
  R2  monto referencial faltante o cero            (separando el cero "reservado por ley" del cero sin explicación)
  R3  proceso sin descripción
  R4  OCP #1: tenderer/parties con identificadores duplicados
  R5  OCP #2: contratos sin estado
  R6  OCP #3: documentType no declarado en la lista de códigos
  R7  OCP #4: adjudicaciones sin contrato y contratos sin adjudicación
  R8  territorio: no ubicado / provincia inconsistente con el departamento
  R9  tildes y encoding (JUNÍN vs JUNIN, textos con mojibake "Ã" o "�")
"""
from __future__ import annotations

import glob
import json
import sys

import pandas as pd

from common import ROOT, get_logger, load_config, now_iso, path
from normalize_records import read_month_table, short
from territory_mapping import NO_UBICADO, assign_department, clean_text

log = get_logger("validation")
MOJIBAKE = r"Ã|Â|�"   # huellas típicas de UTF-8 leído como Latin-1, o caracteres de reemplazo


class Report:
    def __init__(self, n_examples: int):
        self.rows: list[dict] = []
        self.n_examples = n_examples

    def add(self, rid, regla, fuente, unidad, marcados, total, accion, ejemplos=(), nota=""):
        self.rows.append({
            "id": rid, "regla": regla, "fuente": fuente, "unidad": unidad,
            "marcados": int(marcados), "total": int(total),
            "porcentaje": round(100 * marcados / total, 2) if total else 0.0,
            "accion": accion, "nota": nota, "ejemplos": list(ejemplos)[: self.n_examples],
        })
        log.info("%-4s %-55s %7d / %-7d (%5.2f%%)", rid, regla, marcados, total, self.rows[-1]["porcentaje"])


def main() -> int:
    cfg = load_config()
    vcfg = cfg["validation"]
    rep = Report(vcfg["flagged_examples_per_rule"])
    df = pd.read_parquet(ROOT / vcfg["input_file"])
    n = len(df)
    ex = lambda mask: df.loc[mask, "ocid"].head(vcfg["flagged_examples_per_rule"]).tolist()

    # ── R1: ocid duplicados ──────────────────────────────────────────────────
    rec = read_month_table(cfg, "records.csv")[["ocid", "archivo_mes"]]
    dup_raw = rec["ocid"].duplicated(keep=False)
    df["flag_ocid_duplicado"] = df["ocid"].isin(rec.loc[dup_raw, "ocid"])
    rep.add("R1", "ocid duplicado en records.csv (entre y dentro de meses)", "records.csv", "filas de records",
            dup_raw.sum(), len(rec),
            "Se conserva la versión más reciente (compiledRelease/date) en normalize_records.py y se marca "
            "flag_ocid_duplicado; la tabla final tiene 1 fila por ocid (verificado con assert).",
            rec.loc[dup_raw, "ocid"].unique(),
            nota=f"Tabla final: {df['ocid'].duplicated().sum()} duplicados.")

    # ── R2: montos faltantes o cero ──────────────────────────────────────────
    protected = read_month_table(cfg, "records.csv").set_index("ocid")[
        "compiledRelease/tender/hasTenderInformationProtectedByLaw"].eq("True")
    df["valor_reservado_por_ley"] = df["ocid"].map(protected).fillna(False).astype(bool)
    missing = df["monto_referencial"].isna()
    zero = df["monto_referencial"].eq(0)
    df["flag_monto_faltante"] = missing
    df["flag_monto_cero_reservado"] = zero & df["valor_reservado_por_ley"]
    df["flag_monto_cero_sin_explicacion"] = zero & ~df["valor_reservado_por_ley"]
    rep.add("R2a", "Monto referencial faltante (vacío)", "records.csv", "procesos", missing.sum(), n,
            "Marcado flag_monto_faltante. No se imputa: un monto inventado sesgaría cualquier suma.", ex(missing))
    rep.add("R2b", "Monto referencial = 0 con valor reservado por ley", "records.csv", "procesos",
            df["flag_monto_cero_reservado"].sum(), n,
            "Marcado flag_monto_cero_reservado. NO es error: hasTenderInformationProtectedByLaw=True significa "
            "que la entidad reservó el valor referencial; el 0 debe leerse como 'no publicado', nunca sumarse como 0.",
            ex(df["flag_monto_cero_reservado"]))
    rep.add("R2c", "Monto referencial = 0 sin explicación", "records.csv", "procesos",
            df["flag_monto_cero_sin_explicacion"].sum(), n,
            "Marcado flag_monto_cero_sin_explicacion. Se conserva el registro; tratar el monto como desconocido.",
            ex(df["flag_monto_cero_sin_explicacion"]))

    # ── R3: sin descripción ──────────────────────────────────────────────────
    desc = df["descripcion"].fillna("").str.strip()
    df["flag_sin_descripcion"] = desc.eq("")
    df["flag_descripcion_igual_nomenclatura"] = desc.ne("") & desc.eq(df["nomenclatura"].fillna("").str.strip())
    rep.add("R3a", "Proceso sin descripción", "records.csv", "procesos", df["flag_sin_descripcion"].sum(), n,
            "Marcado flag_sin_descripcion. Para el RAG, estos procesos no tienen texto que indexar.",
            ex(df["flag_sin_descripcion"]))
    rep.add("R3b", "Descripción idéntica a la nomenclatura (sin contenido real)", "records.csv", "procesos",
            df["flag_descripcion_igual_nomenclatura"].sum(), n,
            "Marcado flag_descripcion_igual_nomenclatura (descripción que solo repite el código del proceso).",
            ex(df["flag_descripcion_igual_nomenclatura"]))

    # ── R4 (OCP #1): identificadores duplicados en tenderers / parties ───────
    ten = short(read_month_table(cfg, "com_ten_tenderers.csv"), "tenderers/0/")
    par = short(read_month_table(cfg, "com_parties.csv"), "parties/0/")
    exact_ten = ten.duplicated(["ocid", "id"], keep=False)
    exact_par = par.duplicated(["ocid", "id"], keep=False)
    # Misma organización (mismo nombre) con VARIOS ids dentro del mismo proceso.
    ids_per_name = ten.groupby(["ocid", "name"])["id"].transform("nunique")
    multi_id = ids_per_name > 1
    bad_ocids = set(ten.loc[exact_ten | multi_id, "ocid"]) | set(par.loc[exact_par, "ocid"])
    df["flag_ocp1_ids_duplicados"] = df["ocid"].isin(bad_ocids)
    global_names = ten.groupby("name")["id"].nunique()
    rep.add("R4", "OCP #1 · tenderer/parties con identificadores duplicados", "com_ten_tenderers.csv, com_parties.csv",
            "procesos", len(bad_ocids), n,
            "Marcado flag_ocp1_ids_duplicados. No se fusionan organizaciones automáticamente: dos empresas "
            "pueden compartir nombre; unificar ids requiere verificación (p. ej. contra SUNAT).",
            sorted(bad_ocids),
            nota=(f"Id repetido exacto (ocid,id): tenderers={int(exact_ten.sum())}, parties={int(exact_par.sum())} filas. "
                  f"Mismo nombre con >1 id en un proceso: {int(multi_id.sum())} filas de tenderers. "
                  f"En todo el lote, {int((global_names > 1).sum())} de {len(global_names)} nombres de postor usan "
                  f"más de un id (sobre todo extranjeros con id generado 'PE-RUC-L…')."))

    # ── R5 (OCP #2): contratos sin estado ────────────────────────────────────
    con = short(read_month_table(cfg, "com_contracts.csv"), "contracts/0/")
    has_status_col = "status" in con.columns
    no_status = con["status"].isna() if has_status_col else pd.Series(True, index=con.index)
    df["flag_ocp2_contrato_sin_estado"] = df["ocid"].isin(con.loc[no_status, "ocid"])
    api_note = "Sin muestra de API en caché (ejecuta: python src/acquisition_api.py --pages)."
    api_files = glob.glob(str(path(f"{cfg['paths']['api_cache']}/records_page_*.json")))
    if api_files:
        api_contracts = [c for f in api_files for r in json.load(open(f, encoding="utf-8"))["records"]
                         for c in r["compiledRelease"].get("contracts", [])]
        api_missing = sum(1 for c in api_contracts if not c.get("status"))
        api_note = (f"Muestra de la API (JSON, {len(api_files)} páginas de /records): {api_missing} de "
                    f"{len(api_contracts)} contratos sin status "
                    f"({100 * api_missing / max(len(api_contracts), 1):.1f}%).")
    rep.add("R5", "OCP #2 · contratos sin estado (status)", "com_contracts.csv (+ muestra API)", "contratos",
            no_status.sum(), len(con),
            "Marcado flag_ocp2_contrato_sin_estado en el proceso. No se infiere el estado a partir de fechas.",
            con.loc[no_status, "ocid"].unique(),
            nota=("El CSV mensual NO incluye la columna contracts/status: en el CSV el 100% queda sin estado. "
                  if not has_status_col else "") + api_note)

    # ── R6 (OCP #3): documentType no declarado ───────────────────────────────
    allowed = set(vcfg["ocds_document_types"])
    docs = pd.concat([
        short(read_month_table(cfg, "com_ten_documents.csv"), "documents/0/").assign(origen="tender"),
        short(read_month_table(cfg, "com_con_documents.csv"), "documents/0/").assign(origen="contract"),
    ], ignore_index=True)
    undeclared = docs["documentType"].notna() & ~docs["documentType"].isin(allowed)
    empty_type = docs["documentType"].isna()
    df["flag_ocp3_documenttype_no_declarado"] = df["ocid"].isin(docs.loc[undeclared, "ocid"])
    df["flag_documento_sin_tipo"] = df["ocid"].isin(docs.loc[empty_type, "ocid"])
    rep.add("R6a", "OCP #3 · documentType con código no declarado", "com_ten_documents.csv, com_con_documents.csv",
            "documentos", undeclared.sum(), len(docs),
            "Marcado flag_ocp3_documenttype_no_declarado. El código se conserva tal cual (no se reclasifica).",
            docs.loc[undeclared, "ocid"].unique(),
            nota="Códigos encontrados: " + json.dumps(docs["documentType"].value_counts(dropna=False)
                                                       .rename(index=lambda x: str(x)).to_dict(), ensure_ascii=False))
    rep.add("R6b", "Documento sin documentType", "com_ten_documents.csv, com_con_documents.csv", "documentos",
            empty_type.sum(), len(docs), "Marcado flag_documento_sin_tipo en el proceso.",
            docs.loc[empty_type, "ocid"].unique())

    # ── R7 (OCP #4): adjudicaciones ↔ contratos ──────────────────────────────
    awa = short(read_month_table(cfg, "com_awards.csv"), "awards/0/")
    award_keys = set(zip(awa["ocid"], awa["id"]))
    contract_award_keys = set(zip(con["ocid"], con["awardID"]))
    awa_unlinked = ~pd.Series([k in contract_award_keys for k in zip(awa["ocid"], awa["id"])], index=awa.index)
    con_unlinked = ~pd.Series([k in award_keys for k in zip(con["ocid"], con["awardID"])], index=con.index)
    df["flag_ocp4_adjudicacion_sin_contrato"] = df["ocid"].isin(awa.loc[awa_unlinked, "ocid"])
    df["flag_ocp4_contrato_sin_adjudicacion"] = df["ocid"].isin(con.loc[con_unlinked, "ocid"])
    rep.add("R7a", "OCP #4 · adjudicación sin contrato vinculado", "com_awards.csv vs com_contracts.csv",
            "adjudicaciones", awa_unlinked.sum(), len(awa),
            "Marcado flag_ocp4_adjudicacion_sin_contrato. Parte es esperable (contrato aún no firmado en procesos "
            "recientes); no se crea ni se borra ningún vínculo.", awa.loc[awa_unlinked, "ocid"].unique())
    rep.add("R7b", "OCP #4 · contrato cuyo awardID no existe en awards", "com_contracts.csv vs com_awards.csv",
            "contratos", con_unlinked.sum(), len(con),
            "Marcado flag_ocp4_contrato_sin_adjudicacion. Es una inconsistencia real del publicador.",
            con.loc[con_unlinked, "ocid"].unique())

    # ── R8: territorio ───────────────────────────────────────────────────────
    df = assign_department(df)
    no_loc = df["departamento"].eq(NO_UBICADO)
    df["flag_territorio_no_ubicado"] = no_loc
    df["flag_territorio_inconsistente"] = df["territorio_inconsistente"]
    methods = df["departamento_metodo"].value_counts().to_dict()
    rep.add("R8a", "Ubicación no mapeable a los 25 departamentos", "com_parties.csv (comprador)", "procesos",
            no_loc.sum(), n,
            "Se deja departamento=NO_UBICADO y flag_territorio_no_ubicado; nunca se asigna un departamento por defecto.",
            ex(no_loc), nota="Método usado por proceso: " + json.dumps(methods, ensure_ascii=False))
    rep.add("R8b", "Provincia mal clasificada como departamento", "com_parties.csv (comprador)", "procesos",
            df["departamento_metodo"].eq("provincia_en_campo_departamento").sum(), n,
            "Se reemplaza por el departamento al que pertenece la provincia (config/departamentos.yaml).",
            ex(df["departamento_metodo"].eq("provincia_en_campo_departamento")))
    rep.add("R8c", "Provincia declarada pertenece a otro departamento", "com_parties.csv (comprador)", "procesos",
            df["flag_territorio_inconsistente"].sum(), n,
            "Se mantiene el departamento declarado y se marca flag_territorio_inconsistente para revisión.",
            ex(df["flag_territorio_inconsistente"]))

    # ── R9: tildes / encoding ────────────────────────────────────────────────
    raw = df["departamento_raw"].dropna()
    accent_fixed = raw.ne(raw.map(clean_text)) & raw.map(clean_text).notna()
    variants = df.groupby("departamento")["departamento_raw"].nunique()
    rep.add("R9a", "Departamento con tildes/mayúsculas/espacios distintos (JUNÍN vs JUNIN)",
            "com_parties.csv (comprador)", "procesos", accent_fixed.sum(), n,
            "Se normaliza a MAYÚSCULAS sin tildes (se conserva la Ñ) en la columna 'departamento'; "
            "el valor original queda en 'departamento_raw'.", df.loc[raw[accent_fixed].index, "ocid"],
            nota=f"Departamentos con más de una grafía en el dato crudo: {int((variants > 1).sum())}.")
    text_cols = ["descripcion", "comprador_nombre", "tipo_procedimiento", "proveedores"]
    moj = pd.Series(False, index=df.index)
    for c in text_cols:
        moj |= df[c].fillna("").str.contains(MOJIBAKE, regex=True)
    df["flag_texto_mojibake"] = moj
    rep.add("R9b", "Texto con mojibake o caracteres de reemplazo (Ã, Â, �)", "records.csv, com_awa_suppliers.csv",
            "procesos", moj.sum(), n,
            "Marcado flag_texto_mojibake. Los CSV se leen explícitamente como UTF-8 (verificado: el archivo es UTF-8 "
            "válido); si aparece mojibake se reporta, no se 'repara' a ciegas.", ex(moj),
            nota="Columnas revisadas: " + ", ".join(text_cols))

    # Las reglas que cuentan contratos/documentos/adjudicaciones también dicen cuántos PROCESOS tocan.
    per_process = {"R5": "flag_ocp2_contrato_sin_estado", "R6a": "flag_ocp3_documenttype_no_declarado",
                   "R6b": "flag_documento_sin_tipo", "R7a": "flag_ocp4_adjudicacion_sin_contrato",
                   "R7b": "flag_ocp4_contrato_sin_adjudicacion"}
    for row in rep.rows:
        if row["id"] in per_process:
            k = int(df[per_process[row["id"]]].sum())
            row["procesos_afectados"] = k
            row["nota"] = f"Procesos afectados: {k:,} de {n:,}. " + row["nota"]

    # ── Guardar ──────────────────────────────────────────────────────────────
    flag_cols = [c for c in df.columns if c.startswith("flag_")]
    df["n_flags"] = df[flag_cols].sum(axis=1)
    df.to_parquet(path(vcfg["output_file"]), index=False)

    summary = {
        "generado": now_iso(), "meses": cfg["bulk"]["months"], "procesos": n,
        "procesos_sin_ninguna_marca": int((df["n_flags"] == 0).sum()),
        "departamentos": df["departamento"].value_counts().to_dict(),
        "reglas": rep.rows,
    }
    path(vcfg["report_json"]).write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str),
                                         encoding="utf-8")
    path(vcfg["report_md"]).write_text(render_markdown(summary), encoding="utf-8")
    log.info("Procesos sin ninguna marca: %d de %d → %s, %s", summary["procesos_sin_ninguna_marca"], n,
             vcfg["report_md"], vcfg["output_file"])
    return 0


def render_markdown(s: dict) -> str:
    L = [
        "# Reporte de calidad de datos — SEACE V3.0 (OCDS)",
        "",
        f"Generado: {s['generado']} · Meses: {', '.join(s['meses'])} · Procesos (1 fila por ocid): **{s['procesos']:,}**",
        f" · Procesos sin ninguna marca: **{s['procesos_sin_ninguna_marca']:,}**",
        "",
        "Ningún registro se eliminó: cada regla añade una columna `flag_*` en "
        "`data/processed/procesos_validados.parquet`.",
        "",
        "| # | Regla | Unidad | Marcados | Total | % | Qué se hizo |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for r in s["reglas"]:
        L.append(f"| {r['id']} | {r['regla']} | {r['unidad']} | {r['marcados']:,} | {r['total']:,} | "
                 f"{r['porcentaje']:.2f} | {r['accion']} |")
    L += ["", "## Notas por regla", ""]
    for r in s["reglas"]:
        if r["nota"] or r["ejemplos"]:
            L.append(f"- **{r['id']}** ({r['fuente']}). {r['nota']}"
                     + (f" Ejemplos: {', '.join('`' + e + '`' for e in r['ejemplos'])}." if r["ejemplos"] else ""))
    L += ["", "## Procesos por departamento", "", "| Departamento | Procesos |", "|---|---:|"]
    L += [f"| {k} | {v:,} |" for k, v in s["departamentos"].items()]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    sys.exit(main())

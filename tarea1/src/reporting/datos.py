"""Datos para las pestañas de la interfaz: calidad de extracción, evaluación y costos.

Solo LEE archivos ya generados por las fases offline (data/processed, eval/results, logs); no recalcula nada pesado, no abre PDFs y no llama a ningún
proveedor. Devuelve listas de diccionarios (sin pandas) para que se pueda probar y usar sin la interfaz. Si un archivo falta, la función devuelve
vacío/None y la interfaz lo dice: nunca se inventan cifras.
"""
from __future__ import annotations

import csv
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from rag_engine.config import Config
from rag_engine.llm.cost_log import leer_registros, resumen


def _numero(x):
    """'0.905' -> 0.905; '' o texto -> el mismo valor (None si vacío)."""
    if x is None or x == "":
        return None
    try:
        v = float(x)
        return int(v) if v.is_integer() and "." not in str(x) else v
    except (TypeError, ValueError):
        return x


def leer_csv(ruta: Path) -> list[dict]:
    if not Path(ruta).is_file():
        return []
    with Path(ruta).open(encoding="utf-8", newline="") as f:
        return [{k: _numero(v) for k, v in fila.items()} for fila in csv.DictReader(f)]


def leer_json(ruta: Path):
    if not Path(ruta).is_file():
        return None
    try:
        return json.loads(Path(ruta).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def leer_md(ruta: Path) -> str | None:
    """Markdown listo para mostrar: se quitan las imágenes con ruta relativa (no se resuelven fuera del repositorio)."""
    if not Path(ruta).is_file():
        return None
    return re.sub(r"!\[[^\]]*\]\([^)]+\)\s*", "", Path(ruta).read_text(encoding="utf-8"))


# ───────────────────────── calidad de extracción ─────────────────────────

def extraccion(cfg: Config) -> dict:
    """{documentos: [fila por documento], detalle: {id: reporte completo}, plan_ocr: {...}|None, notas: {nombre: markdown}}."""
    base = cfg.ruta("processed")
    reporte = leer_json(base / "reporte_calidad.json") or {}
    filas, detalle = [], {}
    for d in reporte.get("documentos", []):
        p, c, q, o, l = d.get("paginas", {}), d.get("caracteres", {}).get("por_pagina", {}), d.get("indicador_calidad", {}), d.get("ocr"), d.get("limpieza", {})
        filas.append({"documento": d["documento"], "versión": d.get("version"), "páginas del PDF": p.get("total_pdf"), "procesadas": p.get("procesadas"),
                      "con texto nativo": p.get("por_origen", {}).get("texto"), "con OCR": p.get("por_origen", {}).get("ocr"), "excluidas": p.get("excluidas"),
                      "caracteres/página (mediana)": c.get("mediana"), "páginas con poco texto": len(d.get("paginas_con_poco_texto", [])),
                      "% alfabéticos": q.get("pct_alfabeticos_medio"), "palabras conocidas OCR": q.get("pct_palabras_conocidas_medio_ocr"),
                      "confianza OCR": q.get("confianza_ocr_media"), "líneas de cabecera eliminadas": l.get("lineas_de_cabecera_eliminadas")})
        detalle[d["documento"]] = d
    docs = cfg.ruta("docs")
    notas = {n: t for n in ("ocr_subset.md", "limpieza_encabezados.md", "reading_order_check.md") if (t := leer_md(docs / n))}
    plan = None
    for archivo in sorted(base.glob("*/_plan_ocr.json")):
        plan = leer_json(archivo)
    return {"documentos": filas, "detalle": detalle, "plan_ocr": plan, "notas": notas, "generado": (reporte.get("documentos") or [{}])[0].get("generado")}


# ───────────────────────── evaluación ─────────────────────────

def resumen_e2e(filas: list[dict]) -> dict:
    """Cuenta los desenlaces de una evaluación de punta a punta (eval_end_to_end.py)."""
    dentro = [f for f in filas if f.get("tipo") == "in_domain"]
    fuera = [f for f in filas if f.get("tipo") == "out_of_domain"]
    abst = ("abstuvo_umbral", "abstuvo_llm")
    return {"in_domain": len(dentro), "in_domain_respondidas": sum(f["desenlace"] == "respondida" for f in dentro),
            "in_domain_con_cita_correcta": sum(str(f.get("cita_correcta")) == "True" for f in dentro),
            "in_domain_abstenciones": sum(f["desenlace"] in abst for f in dentro), "fuera_de_dominio": len(fuera),
            "fuera_abstenciones": sum(f["desenlace"] in abst for f in fuera), "fuera_abstenciones_por_llm": sum(f["desenlace"] == "abstuvo_llm" for f in fuera),
            "fuera_respondidas": sum(f["desenlace"] == "respondida" for f in fuera), "errores": sum(f["desenlace"] == "error" for f in filas),
            "no_ejecutadas": sum(f["desenlace"] == "no_ejecutada" for f in filas)}


def _e2e_para(cfg: Config, res: Path) -> tuple[list[dict], str | None]:
    """El CSV de punta a punta del umbral configurado; si no existe, el de umbral 0 (si existe) y se avisa."""
    umbral = cfg.get("retrieval.umbral_similitud")
    exacto = res / f"e2e_umbral_{umbral:.3f}.csv"
    if exacto.is_file():
        return leer_csv(exacto), f"umbral {umbral:.3f}"
    alterno = res / "e2e_umbral_0.000.csv"
    if alterno.is_file():
        return leer_csv(alterno), "umbral 0.000 (no hay evaluación con el umbral configurado)"
    return [], None


def evaluacion(cfg: Config) -> dict:
    res = cfg.ruta("eval_results")
    run = leer_json(res / "run_eval.json") or {}
    e2e, etiqueta = _e2e_para(cfg, res)
    return {
        "set_validado": bool(cfg.get("eval.set_validado")), "umbral": cfg.get("retrieval.umbral_similitud"), "ks": cfg.get("eval.ks"),
        "recuperacion": run.get("recuperacion"), "abstencion_recuperacion": run.get("abstencion"), "por_pregunta": run.get("por_pregunta", []),
        "e2e": e2e, "e2e_etiqueta": etiqueta, "e2e_resumen": resumen_e2e(e2e) if e2e else None,
        "barrido_e2e": leer_csv(res / "umbral_e2e_barrido.csv"), "barrido_recuperacion": leer_csv(res / "umbral_barrido.csv"),
        "umbral_e2e_md": leer_md(res / "umbral_e2e_resumen.md"), "embeddings": leer_csv(res / "embeddings_comparacion.csv"),
        "chunking": leer_csv(res / "chunking_comparacion.csv"), "retrievers": leer_csv(res / "retrievers_comparacion.csv"),
        "embeddings_md": leer_md(res / "embeddings_comparacion.md"),
    }


# ───────────────────────── costos ─────────────────────────

def _percentil(valores: list[float], p: float) -> float | None:
    if not valores:
        return None
    v = sorted(valores)
    return round(v[min(len(v) - 1, int(p * (len(v) - 1) + 0.5))], 1)


def costos(cfg: Config) -> dict:
    """Agregado de logs/llm_calls.jsonl (solo llamadas reales al proveedor; las respuestas de la caché de evaluación no se registran)."""
    regs = leer_registros(cfg.ruta("llm_calls_log"))
    if not regs:
        return {"hay_datos": False}
    ok = [r for r in regs if r["exito"]]
    por_modelo = defaultdict(lambda: {"llamadas": 0, "exitosas": 0, "tokens_in": 0, "tokens_out": 0, "costo_real_usd": 0.0, "costo_referencia_usd": 0.0})
    por_dia = Counter()
    for r in regs:
        m = por_modelo[(r["proveedor"], r["modelo"], r["nivel"])]
        m["llamadas"] += 1
        m["exitosas"] += r["exito"]
        m["tokens_in"] += r["tokens_in"]
        m["tokens_out"] += r["tokens_out"]
        m["costo_real_usd"] += r["costo_usd_real"]
        m["costo_referencia_usd"] += r["costo_usd_referencia"]
        por_dia[r["timestamp"][:10]] += 1
    lat = [r["latencia_ms"] for r in ok]
    medio = statistics.mean(r["costo_usd_referencia"] for r in ok) if ok else None
    errores = Counter((r["error"] or "").split(":")[0] for r in regs if not r["exito"])
    return {"hay_datos": True, "resumen": resumen(regs), "latencia_p90_ms": _percentil(lat, 0.9),
            "por_modelo": [{"proveedor": k[0], "modelo": k[1], "nivel": k[2], **{a: (round(b, 6) if isinstance(b, float) else b) for a, b in v.items()}} for k, v in por_modelo.items()],
            "por_dia": [{"día": d, "llamadas": n} for d, n in sorted(por_dia.items())], "errores": dict(errores),
            "ultimas": list(reversed(regs[-20:])),
            "proyeccion_referencia_1000_usd": round(medio * 1000, 4) if medio is not None else None, "muestra_proyeccion": len(ok),
            "aviso_nivel_gratuito": any(r["nivel"] == "gratuito" for r in regs)}

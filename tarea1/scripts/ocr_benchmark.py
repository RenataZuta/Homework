#!/usr/bin/env python3
"""ocr_benchmark.py — compara motores/DPI de OCR sobre unas pocas páginas del DS 009-2025-EF.

Uso (desde tarea1/):  python scripts/ocr_benchmark.py
Lee las variantes y páginas de config.yaml (extraccion.benchmark). Escribe:
    eval/results/ocr_benchmark.csv        una fila por (variante, página)
    eval/results/ocr_benchmark.md         tabla resumen por variante
    eval/results/ocr_benchmark_textos/    el texto reconocido, para revisión visual
Métricas: segundos por página (sin la carga inicial del modelo, que se reporta aparte), confianza media del
motor, % de caracteres alfabéticos y tasa de palabras conocidas (proxy de exactitud, ver quality_report.py).
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pymupdf  # noqa: E402

from extraction.clean import limpiar_pagina, porcentaje_alfabetico  # noqa: E402
from extraction.ocr import ErrorOCR, crear_motor, ocr_pagina  # noqa: E402
from extraction.quality_report import construir_vocabulario, palabras, tasa_palabras_conocidas  # noqa: E402
from rag_engine.config import ConfigError, cargar_config  # noqa: E402


def vocabulario_de_referencia(cfg) -> set[str]:
    """Vocabulario del dominio a partir de los documentos con capa de texto (Ley y DS 001)."""
    textos = []
    for doc in cfg.documentos:
        if doc["id"] == "ds_009_2025_ef":
            continue
        codigo = cfg.get("extraccion.codigo_fin_norma", {}).get(doc["id"])
        with pymupdf.open(cfg.ruta("raw") / doc["archivo"]) as pdf:
            textos += [limpiar_pagina(p.get_text(), codigo).texto for p in pdf]
    return construir_vocabulario(textos)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", type=Path, default=None)
    args = ap.parse_args(argv)
    try:
        cfg = cargar_config(args.config) if args.config else cargar_config()
    except ConfigError as exc:
        print(f"ERROR de configuración: {exc}", file=sys.stderr)
        return 1

    bench = cfg.get("extraccion.benchmark")
    doc = cfg.documento(bench["documento"])
    salida = cfg.ruta("eval_results")
    dir_textos = salida / "ocr_benchmark_textos"
    dir_textos.mkdir(parents=True, exist_ok=True)

    vocab = vocabulario_de_referencia(cfg)
    print(f"Vocabulario de referencia: {len(vocab)} palabras (Ley 32069 + DS 001-2026-EF)")
    pdf = pymupdf.open(cfg.ruta("raw") / doc["archivo"])
    idioma = cfg.get("extraccion.idioma_ocr")

    motores: dict = {}
    filas: list[dict] = []
    carga: dict[str, float] = {}
    for var in bench["variantes"]:
        nombre, dpi = var["motor"], var["dpi"]
        if nombre not in motores:
            t0 = time.perf_counter()
            try:
                motores[nombre] = crear_motor(nombre, idioma)
            except ErrorOCR as exc:
                print(f"  OMITIDO {nombre}: {exc}", file=sys.stderr)
                motores[nombre] = None
            carga[nombre] = time.perf_counter() - t0
            if motores[nombre] is not None and nombre == "easyocr":  # calentamiento: la 1.ª inferencia es más lenta
                ocr_pagina(pdf[bench["paginas"][0] - 1], motores[nombre], dpi=96)
        motor = motores[nombre]
        if motor is None:
            continue
        for n in bench["paginas"] + bench.get("paginas_control", []):
            r = ocr_pagina(pdf[n - 1], motor, dpi)
            conocidas = tasa_palabras_conocidas(r.texto, vocab)
            fila = {
                "motor": nombre, "dpi": dpi, "pagina": n, "tipo": "texto" if n in bench["paginas"] else "control",
                "segundos": round(r.segundos, 2),
                "confianza_motor": round(r.confianza, 1) if r.confianza is not None else "",
                "palabras": r.n_palabras, "caracteres": len(r.texto),
                "pct_alfabeticos": round(100 * porcentaje_alfabetico(r.texto), 1),
                "pct_palabras_conocidas": round(100 * conocidas, 1),
                # Palabras conocidas ABSOLUTAS: une precisión y cobertura. Un motor que omite texto difícil sube su
                # porcentaje pero baja este número; el de mejor lectura global es el que más palabras correctas rescata.
                "palabras_conocidas_n": round(len(palabras(r.texto)) * conocidas),
            }
            filas.append(fila)
            (dir_textos / f"{nombre}_{dpi}dpi_p{n:03d}.txt").write_text(r.texto, encoding="utf-8")
            print(f"  {nombre:9s} {dpi:3d} dpi  pág {n:3d} ({fila['tipo']}): {fila['segundos']:6.1f}s  conf={fila['confianza_motor']}  conocidas={fila['pct_palabras_conocidas']}% ({fila['palabras_conocidas_n']} palabras)", flush=True)

    with (salida / "ocr_benchmark.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]))
        w.writeheader()
        w.writerows(filas)

    lineas = [
        f"# Benchmark de OCR — {doc['nombre']}", "",
        f"Páginas de texto promediadas: {bench['paginas']} · control (formulario, fuera de las medias): {bench.get('paginas_control', [])} · "
        f"vocabulario de referencia: {len(vocab)} palabras · imagen nativa del escaneo: 96 DPI (652×1039 px).", "",
        "| Motor | DPI | s/pág | Confianza motor | % alfabéticos | Caracteres leídos | % palabras conocidas | Palabras conocidas (n) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for var in bench["variantes"]:
        fs = [f for f in filas if f["motor"] == var["motor"] and f["dpi"] == var["dpi"] and f["tipo"] == "texto"]
        if not fs:
            continue
        m = lambda k: statistics.mean(f[k] for f in fs)
        lineas.append(f"| {var['motor']} | {var['dpi']} | {m('segundos'):.1f} | {m('confianza_motor'):.1f} | {m('pct_alfabeticos'):.1f} | "
                      f"{m('caracteres'):.0f} | {m('pct_palabras_conocidas'):.1f} | {m('palabras_conocidas_n'):.0f} |")
    ctrl = [f for f in filas if f["tipo"] == "control"]
    if ctrl:
        lineas += ["", f"**Control — página {ctrl[0]['pagina']} (formulario de tablas)**: caracteres leídos por variante: " +
                   ", ".join(f"{f['motor']} {f['dpi']} dpi = {f['caracteres']}" for f in ctrl) + ".", ""]
    lineas += ["Carga inicial del motor (una vez): " + ", ".join(f"{k} {v:.1f} s" for k, v in carga.items() if motores.get(k)), ""]
    (salida / "ocr_benchmark.md").write_text("\n".join(lineas), encoding="utf-8")
    print("\n" + "\n".join(lineas))
    return 0


if __name__ == "__main__":
    sys.exit(main())

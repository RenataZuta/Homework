#!/usr/bin/env python3
"""map_structure.py — mapea la estructura del DS 009-2025-EF (escaneo) SIN guardar su texto.

Para elegir con criterio qué páginas del Reglamento se procesan con OCR hace falta saber dónde empieza cada
título y capítulo, en qué página cae cada artículo y qué páginas son formularios o tablas. Este paso hace un OCR
rápido (a la resolución nativa del escaneo) de TODAS las páginas y guarda solo: tipo de página, cantidad de
caracteres, encabezados de estructura, números de artículo y conteos de palabras clave. Ese OCR de exploración
NO forma parte del corpus: el texto del corpus lo produce scripts/run_extraction.py solo para el subconjunto elegido.

Es reanudable: el mapa se reescribe de forma atómica tras cada página. Uso (desde tarea1/):
    python scripts/map_structure.py [--doc ds_009_2025_ef] [--rehacer]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pymupdf  # noqa: E402

from extraction.ocr import ErrorOCR, crear_motor, ocr_pagina  # noqa: E402
from extraction.structure import analizar_pagina  # noqa: E402
from rag_engine.config import ConfigError, cargar_config  # noqa: E402


def guardar_atomico(ruta: Path, datos: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, ruta)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--doc", default="ds_009_2025_ef")
    ap.add_argument("--rehacer", action="store_true", help="ignora el mapa existente y empieza de cero")
    args = ap.parse_args(argv)
    try:
        cfg = cargar_config()
        doc = cfg.documento(args.doc)
        ajustes = cfg.get("extraccion.mapeo")
        motor = crear_motor(ajustes["motor"], cfg.get("extraccion.idioma_ocr"))
    except (ConfigError, ErrorOCR) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    ruta_mapa = cfg.ruta("processed") / doc["id"] / "_mapa_estructura.json"
    mapa = {"documento": doc["id"], "motor": ajustes["motor"], "dpi": ajustes["dpi"], "paginas": {}}
    if ruta_mapa.is_file() and not args.rehacer:
        previo = json.loads(ruta_mapa.read_text(encoding="utf-8"))
        if previo.get("motor") == mapa["motor"] and previo.get("dpi") == mapa["dpi"]:
            mapa = previo
    pdf = pymupdf.open(cfg.ruta("raw") / doc["archivo"])
    total, t0, hechas = pdf.page_count, time.time(), 0
    for n in range(1, total + 1):
        if str(n) in mapa["paginas"]:
            continue
        r = ocr_pagina(pdf[n - 1], motor, ajustes["dpi"])
        info = analizar_pagina(r.texto, ajustes["palabras_clave"])
        info.update({
            "caracteres": len(r.texto), "confianza": round(r.confianza, 1) if r.confianza is not None else None,
            "segundos": round(r.segundos, 2),
            "tipo": "texto" if len(r.texto) >= ajustes["min_caracteres_texto"] else "escasa_lectura",
            "muestra": " ".join(r.texto.split())[:160],
        })
        mapa["paginas"][str(n)] = info
        mapa["generado"] = datetime.now().astimezone().isoformat(timespec="seconds")
        guardar_atomico(ruta_mapa, mapa)
        hechas += 1
        if hechas % 10 == 0 or n == total:
            print(f"  {n}/{total} páginas ({time.time() - t0:.0f} s)", flush=True)
    print(f"Mapa listo: {len(mapa['paginas'])} páginas en {ruta_mapa}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

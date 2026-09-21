#!/usr/bin/env python3
"""reading_order_check.py — verifica el orden de lectura del OCR en páginas de dos columnas.

Para cada página elegida (extraccion.orden_lectura.paginas) genera un recorte de la imagen ORIGINAL para
compararlo a simple vista con el texto extraído, etiquetando cada línea como columna izquierda [I] o derecha [D],
y mide cuántas veces el orden salta entre columnas (1 = bien leída; muchos = columnas mezcladas).
Escribe docs/reading_order_check.md y docs/img/orden_lectura_pNNN.png. Si el .md ya tiene una sección
"## Revisión visual", la conserva al regenerar.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pymupdf  # noqa: E402

from extraction import store  # noqa: E402
from extraction.ocr import rasterizar  # noqa: E402
from extraction.quality_report import cambios_de_columna  # noqa: E402
from rag_engine.config import ConfigError, cargar_config  # noqa: E402

MARCA_MANUAL = "## Revisión visual"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--doc", default="ds_009_2025_ef")
    args = ap.parse_args(argv)
    try:
        cfg = cargar_config(cargar_env=False)
        doc = cfg.documento(args.doc)
        aj = cfg.get("extraccion.orden_lectura")
    except ConfigError as exc:
        print(f"ERROR de configuración: {exc}", file=sys.stderr)
        return 1

    dir_doc = cfg.ruta("processed") / doc["id"]
    dir_img = cfg.ruta("docs") / "img"
    dir_img.mkdir(parents=True, exist_ok=True)
    pdf = pymupdf.open(cfg.ruta("raw") / doc["archivo"])
    dpi, banda = cfg.get("extraccion.dpi"), cfg.get("extraccion.ocr.banda_cabecera")

    L = ["# Verificación del orden de lectura del OCR", "",
         f"Documento: **{doc['nombre']}** · OCR: {cfg.get('extraccion.motor_ocr')} a {dpi} DPI · páginas de dos columnas, "
         f"revisadas: {', '.join('p' + str(n) for n in aj['paginas'])}.", "",
         "Cada bloque muestra el **recorte de la imagen original** y, debajo, las líneas extraídas **en el orden en que las entrega el OCR**, "
         "etiquetadas `[I]` (columna izquierda) o `[D]` (derecha). Si el orden fuera correcto, todas las `[I]` de la parte superior "
         "aparecerían seguidas y luego las `[D]`. El indicador **saltos de columna** cuenta los cambios I↔D en toda la página: "
         "**1 = bien leída** (baja por la izquierda y luego por la derecha); muchos saltos = columnas mezcladas.", ""]
    resumen = []
    for n in aj["paginas"]:
        e = store.leer_pagina(dir_doc, n)
        if e is None or e["origen"] != "ocr":
            print(f"  aviso: la página {n} no está procesada con OCR todavía; se omite", file=sys.stderr)
            continue
        img = rasterizar(pdf[n - 1], dpi)
        alto = img.height
        y0, y1 = int(alto * aj["recorte_desde"]), int(alto * aj["recorte_hasta"])
        ruta_img = dir_img / f"orden_lectura_p{n:03d}.png"
        img.crop((0, y0, img.width, y1)).save(ruta_img, optimize=True)

        lineas = [l for l in e["ocr_lineas"] if l[0] >= banda]                 # sin la banda de cabecera (ya limpiada)
        en_recorte = [l for l in lineas if aj["recorte_desde"] <= l[0] < aj["recorte_hasta"]]
        saltos = cambios_de_columna(lineas)
        resumen.append((n, saltos, len(lineas)))
        L += [f"## Página {n}", "",
              f"Saltos de columna en toda la página: **{saltos}** ({len(lineas)} líneas) · confianza del motor {e['confianza_ocr']}.", "",
              f"![recorte original de la página {n}](img/{ruta_img.name})", "",
              f"Líneas extraídas del recorte (de {aj['recorte_desde']:.0%} a {aj['recorte_hasta']:.0%} de la altura), en orden de salida del OCR:", "", "```text"]
        for _, _, texto, x in en_recorte[: aj["max_lineas_mostradas"]]:
            L.append(f"[{'I' if x < 0.5 else 'D'}] {texto}")
        L += ["```", ""]

    veredicto = ["## Resultado automático", "", "| Página | Saltos de columna | Líneas | Lectura |", "|---:|---:|---:|---|"]
    for n, saltos, nl in resumen:
        veredicto.append(f"| {n} | {saltos} | {nl} | {'correcta (columnas en orden)' if saltos <= aj['saltos_aceptables'] else 'REVISAR: columnas posiblemente mezcladas'} |")
    L = L[:6] + veredicto + [""] + L[6:]

    ruta_md = cfg.ruta("docs") / "reading_order_check.md"
    manual = ""
    if ruta_md.is_file():
        previo = ruta_md.read_text(encoding="utf-8")
        if MARCA_MANUAL in previo:
            manual = "\n" + previo[previo.index(MARCA_MANUAL):]
    salida = "\n".join(L) + (manual if manual else f"\n{MARCA_MANUAL}\n\n_Pendiente: comparar cada recorte con su texto y anotar hallazgos (columnas mezcladas, saltos) y su tratamiento._\n")
    tmp = ruta_md.with_suffix(".md.tmp")
    tmp.write_text(salida, encoding="utf-8")
    os.replace(tmp, ruta_md)
    for n, saltos, nl in resumen:
        print(f"  p{n}: {saltos} saltos de columna en {nl} líneas")
    print(f"Escrito: {ruta_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

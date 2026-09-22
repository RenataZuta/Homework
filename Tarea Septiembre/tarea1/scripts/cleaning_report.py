#!/usr/bin/env python3
"""cleaning_report.py — documenta la limpieza de encabezados con ANTES / DESPUÉS y verifica que no borra contenido legítimo.

Escribe docs/limpieza_encabezados.md. Sale con código 1 si alguna verificación falla (para usarlo como control).
Verificaciones (sobre TODAS las páginas procesadas):
  * Texto con capa: cada línea eliminada como cabecera/sello coincide con el patrón de cabecera de El Peruano.
  * Las páginas que empiezan con «Artículo …» (tras la cabecera) conservan esa primera línea.
  * OCR: ninguna línea eliminada por la banda de cabecera parece un encabezado legítimo (Artículo/Capítulo/Título/numeral).
  * Ninguna página quedó vacía por efecto de la limpieza.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from extraction import store  # noqa: E402
from rag_engine.config import ConfigError, cargar_config  # noqa: E402

PATRON_CABECERA = re.compile(
    r"^(\d{1,4}|NORMAS LEGALES|(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo) \d{1,2} de \w+ de \d{4}|El Peruano\s*/?|/)$", re.I)
PATRON_SELLO = re.compile(r"^(Firmado por\s*:|Fecha\s*:\s*\d{2}/\d{2}/\d{4})", re.I)
PATRON_LEGITIMO = re.compile(r"^\W{0,3}(Art[ií]culo|CAP[IÍ]TULO|T[IÍ]TULO|SUBCAP|DISPOSICI[OÓ]N|\d+\.\d+)", re.I)
PATRON_ARTICULO = re.compile(r"^[“\"]?Art[ií]culo\b")


def bloque(titulo: str, lineas: list[str], n: int) -> list[str]:
    cuerpo = [l if len(l) <= 110 else l[:107] + "…" for l in lineas[:n]]
    return [f"**{titulo}**", "", "```text", *cuerpo, "```", ""]


def main() -> int:
    try:
        cfg = cargar_config(cargar_env=False)
        demo = cfg.get("extraccion.limpieza_demo")
    except ConfigError as exc:
        print(f"ERROR de configuración: {exc}", file=sys.stderr)
        return 1
    L = ["# Limpieza de encabezados: reglas, antes/después y verificación", "",
         "_Generado por `scripts/cleaning_report.py` a partir de `data/processed/` (que guarda el texto **crudo** y el **limpio** de cada página)._", "",
         "## Reglas (`src/extraction/clean.py`)", "",
         "| Regla | Qué elimina | Dónde actúa |", "|---|---|---|",
         "| R1 | Cabecera de El Peruano: nº de página · `NORMAS LEGALES` · fecha · `El Peruano /` | Solo al INICIO de la página y solo si la firma está completa. El `/` a veces baja de línea. |",
         "| R2 | Sello de firma digital (`Firmado por: …`, `Fecha: dd/mm/aaaa hh:mm`) | Solo al FINAL de la página |",
         "| R3 | Texto de OTRAS normas tras el código de cierre de la norma (`2474920-3`) | El PDF de El Peruano trae páginas de la edición completa |",
         "| R1o | Cabecera de páginas ESCANEADAS | Por POSICIÓN: líneas cuyo borde superior está en la banda superior "
         f"(`extraccion.ocr.banda_cabecera` = {cfg.get('extraccion.ocr.banda_cabecera')} de la altura). El texto que el OCR lee ahí es impredecible. |",
         "| R4 | Espacios (NBSP, ancho cero, blancos de fin de línea, líneas en blanco repetidas) | Toda la página. **No** se quitan guiones de fin de línea: rompería `009-2025-\\nEF`. |", "",
         "El texto **crudo** nunca se pierde: queda en `texto_crudo` de cada entrada, de modo que toda regla es auditable y se puede re-aplicar (`run_extraction.py --relimpiar`) sin repetir el OCR.", ""]
    fallos: list[str] = []

    L += ["## Antes / después en tres páginas", ""]
    for doc_id, paginas in demo.items():
        for n in paginas:
            e = store.leer_pagina(cfg.ruta("processed") / doc_id, n)
            if e is None:
                L += [f"_(la página {n} de `{doc_id}` aún no está procesada)_", ""]
                continue
            crudo, limpio = e["texto_crudo"].split("\n"), e["texto"].split("\n")
            lim = e["limpieza"]
            L += [f"### `{doc_id}` — página {n} ({e['origen']}) · reglas aplicadas: {', '.join(lim['reglas']) or 'ninguna'}", ""]
            L += bloque(f"Antes (texto crudo, primeras líneas; total {len(crudo)} líneas / {len(e['texto_crudo'])} caracteres)", crudo, 9)
            L += bloque(f"Después (texto limpio, primeras líneas; total {len(limpio)} líneas / {e['caracteres']} caracteres)", limpio, 6)
            if lim["lineas_fuera_de_norma"]:
                L += [f"En esta página R3 descartó **{lim['lineas_fuera_de_norma']} líneas** de otras normas; el texto limpio termina así:", ""]
                L += bloque("Final del texto limpio", limpio[-4:], 4)

    L += ["## Verificación: la regla no borra contenido legítimo", "", "| Documento | Páginas | Con cabecera eliminada | Líneas eliminadas | Empiezan con «Artículo» | Resultado |", "|---|---:|---:|---:|---:|---|"]
    for doc in cfg.documentos:
        entradas = store.listar_paginas(cfg.ruta("processed") / doc["id"])
        if not entradas:
            continue
        eliminadas = con_cab = con_art = 0
        problemas: list[str] = []
        for e in entradas:
            lim = e["limpieza"]
            if lim["cabecera_eliminada"]:
                con_cab += 1
            eliminadas += len(lim["cabecera_eliminada"])
            if e["origen"] == "texto":
                for l in lim["cabecera_eliminada"]:
                    if not PATRON_CABECERA.match(l):
                        problemas.append(f"p{e['pagina']}: línea eliminada que no parece cabecera: {l!r}")
                for l in lim["pie_eliminado"]:
                    if not PATRON_SELLO.match(l):
                        problemas.append(f"p{e['pagina']}: sello inesperado: {l!r}")
                primera_cruda = next((l.strip() for l in e["texto_crudo"].split("\n") if l.strip() and not PATRON_CABECERA.match(l.strip())), "")
                if PATRON_ARTICULO.match(primera_cruda):
                    con_art += 1
                    if not PATRON_ARTICULO.match(e["texto"].split("\n")[0].strip()):
                        problemas.append(f"p{e['pagina']}: la primera línea «Artículo…» no se conservó")
            else:
                for l in lim["cabecera_eliminada"]:
                    if PATRON_LEGITIMO.match(l):
                        problemas.append(f"p{e['pagina']}: la banda de cabecera eliminó algo que parece un encabezado legítimo: {l!r}")
            if e["caracteres"] < 150:
                problemas.append(f"p{e['pagina']}: quedó con {e['caracteres']} caracteres")
        L.append(f"| `{doc['id']}` | {len(entradas)} | {con_cab} | {eliminadas} | {con_art} | {'✅ sin problemas' if not problemas else '❌ ' + str(len(problemas)) + ' problema(s)'} |")
        fallos += [f"{doc['id']} {p}" for p in problemas]
    if fallos:
        L += ["", "### Problemas encontrados", ""] + [f"- {f}" for f in fallos]
    L.append("")
    ruta = cfg.ruta("docs") / "limpieza_encabezados.md"
    tmp = ruta.with_suffix(".md.tmp")
    tmp.write_text("\n".join(L), encoding="utf-8")
    os.replace(tmp, ruta)
    print(f"Escrito {ruta}; problemas: {len(fallos)}")
    for f in fallos[:10]:
        print("  -", f)
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())

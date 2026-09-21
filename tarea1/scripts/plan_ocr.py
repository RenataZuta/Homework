#!/usr/bin/env python3
"""plan_ocr.py — decide qué páginas del DS 009-2025-EF se procesan con OCR y documenta la decisión.

Entradas: el mapa de estructura (scripts/map_structure.py), articulos_modificados.json y config.yaml.
Salidas:  data/processed/ds_009_2025_ef/_plan_ocr.json (una decisión por página, con su motivo)
          docs/ocr_subset.md (rangos, exclusiones y criterio, para revisión)
Con --aplicar escribe en config.yaml los valores de extraccion.rangos_paginas y extraccion.prioridad_ocr.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from extraction import store  # noqa: E402
from extraction.rangos import formatear_rangos  # noqa: E402
from extraction.structure import analizar_pagina  # noqa: E402
from extraction.subset import es_pagina_de_texto, prioridad, seleccionar  # noqa: E402
from rag_engine.config import ConfigError, cargar_config  # noqa: E402

DOC = "ds_009_2025_ef"


def escribir(ruta: Path, texto: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    tmp.write_text(texto, encoding="utf-8")
    os.replace(tmp, ruta)


def aplicar_en_config(ruta: Path, rangos: str, prio: list[int]) -> None:
    s = ruta.read_text(encoding="utf-8")
    s, n1 = re.subn(r'(?m)^(    ' + DOC + r'): (?:null|"[^"]*")[^\n]*$', rf'\1: "{rangos}"   # subconjunto de OCR: ver docs/ocr_subset.md', s, count=1)
    s, n2 = re.subn(r'(?m)^(    ' + DOC + r'): \[[^\]\n]*\][^\n]*$', rf'\1: [{", ".join(map(str, prio))}]', s, count=1)
    if n1 != 1 or n2 != 1:
        raise RuntimeError("No pude localizar las líneas de rangos_paginas / prioridad_ocr en config.yaml; edítalas a mano.")
    escribir(ruta, s)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--aplicar", action="store_true", help="escribe rangos y prioridad en config.yaml")
    args = ap.parse_args(argv)
    try:
        cfg = cargar_config(cargar_env=False)
    except ConfigError as exc:
        print(f"ERROR de configuración: {exc}", file=sys.stderr)
        return 1
    sub = cfg.get("extraccion.subconjunto")
    dir_doc = cfg.ruta("processed") / DOC
    mapa_json = json.loads((dir_doc / "_mapa_estructura.json").read_text(encoding="utf-8"))
    mapa = {int(k): v for k, v in mapa_json["paginas"].items()}
    ruta_mod = cfg.ruta("articulos_modificados")
    mod = json.loads(ruta_mod.read_text(encoding="utf-8"))
    articulos_mod = sorted({c["articulo"] for c in mod["cambios"]})

    decisiones = seleccionar(mapa, articulos_mod, sub["max_articulo"], sub["paginas_objetivo"], sub["paginas_minimo"], sub["pesos"], sub["criterio_texto"])
    incluidas = [d.pagina for d in decisiones if d.incluida]
    prio = prioridad(decisiones)
    rangos = formatear_rangos(incluidas)
    if len(incluidas) < sub["paginas_minimo"]:
        print(f"ERROR: el subconjunto tiene {len(incluidas)} páginas (< {sub['paginas_minimo']}).", file=sys.stderr)
        return 1

    # cobertura de artículos modificados
    from extraction.subset import articulo_a_pagina
    a_pag = articulo_a_pagina(mapa, sub["max_articulo"])
    cubiertos = [a for a in articulos_mod if a_pag.get(a) in set(incluidas)]
    sin_cubrir = [a for a in articulos_mod if a not in cubiertos]

    escribir(dir_doc / "_plan_ocr.json", json.dumps({
        "documento": DOC, "generado": date.today().isoformat(), "paginas_incluidas": incluidas, "rangos": rangos, "prioridad": prio,
        "cobertura_articulos_modificados": {"total": len(articulos_mod), "con_pagina_incluida": len(cubiertos), "sin_cubrir": sin_cubrir},
        "decisiones": [{"pagina": d.pagina, "incluida": d.incluida, "puntaje": d.puntaje, "modificados": d.modificados,
                        "encabezados": d.encabezados, "motivos": d.motivos} for d in decisiones],
    }, ensure_ascii=False, indent=1))

    ocr = store.listar_paginas(dir_doc)
    vistos: dict[int, list[int]] = {}
    for e in ocr:
        for a in set(analizar_pagina(e["texto"])["articulos"]):
            vistos.setdefault(a, []).append(e["pagina"])
    hallados = [a for a in articulos_mod if a in vistos]
    no_hallados = [a for a in articulos_mod if a not in vistos]
    total = len(decisiones)
    crit = sub["criterio_texto"]
    texto = sorted(p for p, v in mapa.items() if es_pagina_de_texto(v, crit))
    escasas = sorted(p for p, v in mapa.items() if not es_pagina_de_texto(v, crit))
    excl_texto = [d.pagina for d in decisiones if not d.incluida and es_pagina_de_texto(mapa[d.pagina], crit)]
    L = [
        "# Subconjunto del DS 009-2025-EF procesado con OCR", "",
        f"_Generado por `scripts/plan_ocr.py` el {date.today().isoformat()}. Es un PLAN reproducible: si cambia el mapa o los pesos de "
        f"`config.yaml`, se regenera._", "",
        "## Resumen", "",
        f"- El PDF tiene **{total} páginas**, todas escaneadas (0 caracteres de capa de texto).",
        f"- **{len(incluidas)} páginas procesadas con OCR** (mínimo exigido: {sub['paginas_minimo']}): `{rangos}`.",
        f"- Páginas con texto normativo legible: {len(texto)} (págs. {min(texto)}–{max(texto)}); se procesa el {100 * len(incluidas) / len(texto):.0f} % de ellas.",
        (f"- **Cobertura del manejo de versiones (verificada sobre el texto OCR):** el texto original de **{len(hallados)} de {len(articulos_mod)}** artículos "
         f"modificados o incorporados por el DS 001-2026-EF está en el corpus (estimación previa al OCR, por interpolación de páginas: {len(cubiertos)})."
         if ocr else
         f"- **Cobertura del manejo de versiones (estimada por interpolación, aún sin verificar con OCR):** {len(cubiertos)} de {len(articulos_mod)} artículos "
         f"modificados o incorporados por el DS 001-2026-EF empiezan en una página del subconjunto."), "",
        "## Convención de número de página", "",
        "`pagina` es el índice del PDF empezando en 1 (la primera página del archivo es la 1). En este PDF coincide con el número impreso en la "
        "cabecera de El Peruano (p. ej. la página 60 dice «60 NORMAS LEGALES»), pero el sistema usa siempre el índice del PDF, igual que en una "
        "corrida completa del OCR; así las citas son las mismas con o sin subconjunto.", "",
        "## Cómo se eligió", "",
        "1. **Mapeo de estructura** (`scripts/map_structure.py`): un OCR rápido de las 196 páginas que guarda solo estructura (tipo de página, "
        "encabezados, números de artículo, conteos de palabras clave), **no el texto**. Ese OCR de exploración no forma parte del corpus.",
        "2. **Solo páginas de texto**: al menos "
        f"{crit['min_caracteres']} caracteres leídos **y** confianza del motor ≥ {crit['min_confianza']:g}. Las portadas, formularios y tablas (`escasa_lectura`) "
        "quedan fuera. Ninguna de las dos condiciones basta sola: los formularios del anexo dan miles de caracteres de ruido con confianza ≈ 55, "
        "y algunas páginas de formulario dan confianza alta con casi nada de texto.",
        "3. **Cobertura obligatoria:** la página donde empieza cada título, capítulo, subcapítulo, disposición y anexo detectados.",
        "4. **Versiones:** se prioriza el texto ORIGINAL de los artículos que el DS 001-2026-EF modifica o incorpora "
        f"(`data/processed/articulos_modificados.json`, {len(articulos_mod)} artículos). Sin él no se puede mostrar cuándo el reglamento original quedó desactualizado.",
        f"5. **Relevancia para una MYPE:** el resto del presupuesto ({sub['paginas_objetivo']} páginas) se llena por puntaje "
        f"(`{sub['pesos']['modificados']:g}` × artículos modificados que empiezan en la página + densidad de palabras clave sobre contratación menor, "
        "registro de proveedores, procedimientos de selección, garantías y penalidades, controversias y Pladicop).", "",
        "## Estructura detectada y página de inicio", "", "| Página | Nivel | Encabezado (leído por OCR) | ¿En el subconjunto? |", "|---:|---|---|---|",
    ]
    for d in decisiones:
        for e in mapa[d.pagina]["encabezados"]:
            L.append(f"| {d.pagina} | {e['nivel']} | {e['texto']} | {'sí' if d.incluida else 'no'} |")
    L += ["", "Los encabezados se leen con OCR a baja resolución y pueden tener errores de numeración (p. ej. `TÍTULO 1x` por IX). "
          "La revisión visual está pendiente `[MANUAL]`.", "",
          "## Páginas excluidas y motivo", "",
          f"- **`escasa_lectura` — {len(escasas)} páginas** (`{formatear_rangos(escasas)}`): portadas, formularios y tablas de anexos. El OCR lee casi nada "
          "(la p. 150 es un formulario de estados financieros: 7 palabras reconocidas) y no contienen normativa consultable.",
          f"- **`menor prioridad` — {len(excl_texto)} páginas de texto** (`{formatear_rangos(excl_texto)}`): sin encabezado, con pocos o ningún artículo modificado "
          "que empiece en ellas y bajo puntaje MYPE. Su contenido queda **fuera del índice a propósito**: una pregunta cuya respuesta solo esté ahí debe "
          "producir una abstención (requisito de «conocer los límites del corpus»).", ""]
    if sin_cubrir:
        L += ["## Artículos modificados cuyo texto original NO está en el subconjunto", "",
              f"`{', '.join(map(str, sin_cubrir))}`. Para estos, el motor solo tendrá el texto del DS 001-2026-EF (la modificatoria).", ""]
    # verificación POSTERIOR al OCR: ¿el texto original de cada artículo modificado está realmente en el corpus?
    if ocr:
        fantasma = sorted(a for a in vistos if a > 389)
        L += ["## Verificación posterior al OCR: artículos modificados presentes en el corpus", "",
              f"Se buscó, en el texto ya extraído de las {len(ocr)} páginas, una línea que empiece con «Artículo N.» para cada uno de los {len(articulos_mod)} artículos "
              f"que el DS 001-2026-EF modifica o incorpora: **{len(hallados)} encontrados**, {len(no_hallados)} no encontrados"
              + (f" (`{', '.join(map(str, no_hallados))}`)." if no_hallados else ".") +
              " Un «no encontrado» puede ser un artículo cuyo número el OCR leyó mal o cuya página quedó fuera del subconjunto; para ninguno de ellos hay "
              "garantía de que el texto original esté indexado.", ""]
        if fantasma:
            L += [f"Números de artículo que el OCR leyó pero que no existen en el Reglamento (> 389; errores de lectura): `{', '.join(map(str, fantasma))}`. "
                  "La extracción de `articulos_mencionados` (Fase 4) debe descartarlos.", ""]
        (dir_doc / "_verificacion_versiones.json").write_text(json.dumps(
            {"encontrados": hallados, "no_encontrados": no_hallados, "articulos_leidos_fuera_de_rango": fantasma}, ensure_ascii=False, indent=1), encoding="utf-8")
    L += ["## Limitaciones", "",
          "- La página de inicio de cada artículo se **detecta** por OCR (cobertura de detección medida en el mapa) o se **interpola** entre artículos vecinos "
          "(error típico de ±1 página). Un artículo puede empezar en una página incluida y terminar en una excluida.",
          "- El escaneo es de **96 DPI nativos**; el OCR tiene errores de carácter (ver `eval/results/ocr_benchmark.md`).", "",
          "## Detalle por página", "", "El detalle completo (puntaje y motivo de cada una de las páginas) está en "
          "`data/processed/ds_009_2025_ef/_plan_ocr.json`.", ""]
    escribir(cfg.ruta("docs") / "ocr_subset.md", "\n".join(L))

    print(f"Incluidas: {len(incluidas)}/{total} → {rangos}")
    print(f"Prioridad (obligatorias, {len(prio)}): {prio}")
    print(f"Artículos modificados cubiertos: {len(cubiertos)}/{len(articulos_mod)}; sin cubrir: {sin_cubrir}")
    if args.aplicar:
        aplicar_en_config(cfg.archivo, rangos, prio)
        print("config.yaml actualizado (extraccion.rangos_paginas y extraccion.prioridad_ocr).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

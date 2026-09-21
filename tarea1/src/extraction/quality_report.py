"""Métricas de calidad de extracción (y, más adelante, el reporte por documento)."""
from __future__ import annotations

import re

RE_PALABRA = re.compile(r"[a-záéíóúüñ]{3,}")


def palabras(texto: str) -> list[str]:
    """Palabras de 3+ letras en minúscula (el proxy de calidad ignora números y siglas cortas)."""
    return RE_PALABRA.findall(texto.lower())


def construir_vocabulario(textos: list[str]) -> set[str]:
    vocab: set[str] = set()
    for t in textos:
        vocab.update(palabras(t))
    return vocab


def tasa_palabras_conocidas(texto: str, vocabulario: set[str]) -> float:
    """Fracción de palabras del texto que existen en el vocabulario de referencia (0.0 si no hay palabras).

    Es un PROXY de la exactitud del OCR: una palabra mal reconocida ("Articulo" sin tilde, "mvolucrados")
    cae fuera del vocabulario. El vocabulario sale de textos con capa de texto exacta del mismo dominio, así
    que los términos legítimos casi siempre están. No sustituye a una transcripción de referencia.
    """
    ws = palabras(texto)
    return sum(w in vocabulario for w in ws) / len(ws) if ws else 0.0


def cambios_de_columna(lineas: list[list], corte_x: float = 0.5) -> int:
    """Cuántas veces el orden de lectura salta entre la columna izquierda y la derecha.

    En una página de dos columnas bien leída el texto baja por la izquierda y luego por la derecha: 1 salto.
    Muchos saltos delatan columnas MEZCLADAS (línea 1 izquierda, línea 1 derecha, línea 2 izquierda…).
    Solo se consideran líneas de cuerpo (con texto de 12+ caracteres, para ignorar títulos centrados y números).
    """
    lado = [0 if l[3] < corte_x else 1 for l in lineas if len(l[2]) >= 12]
    return sum(1 for a, b in zip(lado, lado[1:]) if a != b)


# ───────────────────────── reporte de calidad por documento ─────────────────────────
import json
import os
import statistics
from datetime import datetime
from pathlib import Path

POCO_TEXTO = 200   # caracteres limpios por debajo de los cuales una página se lista como "con poco texto"


def _resumen_numerico(valores: list[float]) -> dict | None:
    if not valores:
        return None
    return {"media": round(statistics.mean(valores), 2), "mediana": round(statistics.median(valores), 2),
            "min": round(min(valores), 2), "max": round(max(valores), 2)}


def reporte_documento(doc: dict, entradas: list[dict], paginas_pdf: int, plan: dict | None = None) -> dict:
    """Arma el reporte de calidad de UN documento a partir de sus entradas por página (ya extraídas)."""
    ocr = [e for e in entradas if e["origen"] == "ocr"]
    procesadas = [e["pagina"] for e in entradas]
    excluidas = sorted(set(range(1, paginas_pdf + 1)) - set(procesadas))
    motivos: dict[str, list[int]] = {}
    if plan:
        for d in plan["decisiones"]:
            if not d["incluida"] and d["pagina"] in excluidas:
                clave = "escasa_lectura (portada, formulario o tabla)" if d["motivos"] and d["motivos"][0].startswith("escasa_lectura") \
                    else "menor prioridad (fuera del subconjunto de OCR)"
                motivos.setdefault(clave, []).append(d["pagina"])
    elif excluidas:
        motivos["sin procesar"] = excluidas

    limpieza = [e.get("limpieza", {}) for e in entradas]
    medio = entradas[len(entradas) // 2] if entradas else None
    conocidas = [e["calidad"]["pct_palabras_conocidas"] for e in ocr if e["calidad"].get("pct_palabras_conocidas") is not None]
    confs = [e["confianza_ocr"] for e in ocr if e.get("confianza_ocr") is not None]
    segs = [e["ocr_segundos"] for e in ocr if e.get("ocr_segundos") is not None]
    return {
        "documento": doc["id"], "nombre": doc["nombre"], "version": doc["version"], "generado": datetime.now().astimezone().isoformat(timespec="seconds"),
        "convencion_pagina": "pagina = índice del PDF, empezando en 1",
        "paginas": {"total_pdf": paginas_pdf, "procesadas": len(entradas), "por_origen": {"texto": len(entradas) - len(ocr), "ocr": len(ocr)},
                    "excluidas": len(excluidas), "excluidas_por_motivo": {k: v for k, v in motivos.items()}},
        "caracteres": {"total": sum(e["caracteres"] for e in entradas), "por_pagina": _resumen_numerico([e["caracteres"] for e in entradas])},
        "paginas_con_poco_texto": [{"pagina": e["pagina"], "caracteres": e["caracteres"], "origen": e["origen"]} for e in entradas if e["caracteres"] < POCO_TEXTO],
        "ocr": None if not ocr else {"paginas": len(ocr), "motor": ocr[0].get("ocr_motor"), "dpi": ocr[0].get("ocr_dpi"),
                                     "segundos_por_pagina": _resumen_numerico(segs), "segundos_total": round(sum(segs), 1),
                                     "confianza_motor": _resumen_numerico(confs)},
        "limpieza": {
            "paginas_con_cabecera_eliminada": sum(1 for l in limpieza if l.get("cabecera_eliminada")),
            "lineas_de_cabecera_eliminadas": sum(len(l.get("cabecera_eliminada", [])) for l in limpieza),
            "paginas_con_sello_de_firma": sum(1 for l in limpieza if l.get("pie_eliminado")),
            "paginas_recortadas_por_fin_de_norma": sum(1 for l in limpieza if l.get("lineas_fuera_de_norma")),
            "lineas_de_otras_normas_descartadas": sum(l.get("lineas_fuera_de_norma", 0) for l in limpieza),
        },
        "indicador_calidad": {
            "pct_alfabeticos_medio": round(statistics.mean(e["calidad"]["pct_alfabeticos"] for e in entradas), 3) if entradas else None,
            "pct_palabras_conocidas_medio_ocr": round(statistics.mean(conocidas), 3) if conocidas else None,
            "confianza_ocr_media": round(statistics.mean(confs), 1) if confs else None,
        },
        "muestra_del_medio": None if medio is None else {"pagina": medio["pagina"], "origen": medio["origen"], "texto": medio["texto"][:900]},
    }


def reporte_a_markdown(r: dict) -> str:
    p, c, q, l = r["paginas"], r["caracteres"], r["indicador_calidad"], r["limpieza"]
    L = [f"# Reporte de calidad de extracción — {r['nombre']}", "",
         f"_Versión: `{r['version']}` · generado {r['generado']} · página = índice del PDF (empieza en 1)_", "",
         "| Indicador | Valor |", "|---|---|",
         f"| Páginas del PDF / procesadas / excluidas | {p['total_pdf']} / {p['procesadas']} / {p['excluidas']} |",
         f"| Origen del texto | {p['por_origen']['texto']} con capa de texto · {p['por_origen']['ocr']} con OCR |",
         f"| Caracteres (texto limpio) | {c['total']:,} en total · {c['por_pagina']['media']:.0f} por página (mediana {c['por_pagina']['mediana']:.0f}, mín {c['por_pagina']['min']:.0f}, máx {c['por_pagina']['max']:.0f}) |"
         if c["por_pagina"] else "| Caracteres | — |",
         f"| Letras entre los caracteres no blancos | {100 * q['pct_alfabeticos_medio']:.1f} % (media) |" if q["pct_alfabeticos_medio"] is not None else "| Letras | — |"]
    if r["ocr"]:
        o = r["ocr"]
        L += [f"| OCR | {o['motor']} a {o['dpi']} DPI sobre {o['paginas']} páginas |",
              f"| Tiempo de OCR por página | media {o['segundos_por_pagina']['media']:.1f} s · mediana {o['segundos_por_pagina']['mediana']:.1f} s · máx {o['segundos_por_pagina']['max']:.1f} s (total {o['segundos_total']:.0f} s) |",
              f"| Confianza del motor | {q['confianza_ocr_media']:.1f} / 100 (media por página) |"]
        if q["pct_palabras_conocidas_medio_ocr"] is not None:
            L.append(f"| Palabras reconocidas (proxy de exactitud) | {100 * q['pct_palabras_conocidas_medio_ocr']:.1f} % están en el vocabulario de la Ley y del DS 001 |")
    L += [f"| Cabeceras eliminadas | {l['paginas_con_cabecera_eliminada']} páginas ({l['lineas_de_cabecera_eliminadas']} líneas) |",
          f"| Sellos de firma digital eliminados | {l['paginas_con_sello_de_firma']} páginas |",
          f"| Texto de otras normas descartado (fin de norma) | {l['lineas_de_otras_normas_descartadas']} líneas en {l['paginas_recortadas_por_fin_de_norma']} página(s) |", ""]
    if p["excluidas_por_motivo"]:
        L += ["## Páginas excluidas y motivo", ""]
        for motivo, paginas in p["excluidas_por_motivo"].items():
            L.append(f"- **{motivo}** — {len(paginas)} páginas")
        L.append("")
    if r["paginas_con_poco_texto"]:
        L += [f"## Páginas procesadas con menos de {POCO_TEXTO} caracteres", "",
              ", ".join(f"p{x['pagina']} ({x['caracteres']})" for x in r["paginas_con_poco_texto"]), ""]
    m = r["muestra_del_medio"]
    if m:
        L += [f"## Muestra del medio del documento (página {m['pagina']}, origen {m['origen']})", "", "```text", m["texto"], "```", ""]
    return "\n".join(L)


def escribir_reporte(dir_salida: Path, r: dict) -> None:
    dir_salida.mkdir(parents=True, exist_ok=True)
    for nombre, contenido in (("reporte_calidad.json", json.dumps(r, ensure_ascii=False, indent=1) + "\n"), ("reporte_calidad.md", reporte_a_markdown(r))):
        tmp = dir_salida / (nombre + ".tmp")
        tmp.write_text(contenido, encoding="utf-8")
        os.replace(tmp, dir_salida / nombre)

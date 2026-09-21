#!/usr/bin/env python3
"""run_extraction.py — PDFs -> una entrada JSON por página en data/processed/<doc_id>/ (proceso OFFLINE).

Uso (desde tarea1/):
    python scripts/run_extraction.py                    # los 3 documentos
    python scripts/run_extraction.py --solo ley_32069   # uno solo
    python scripts/run_extraction.py --relimpiar        # vuelve a aplicar la limpieza SIN repetir el OCR
    python scripts/run_extraction.py --max-paginas 5    # procesa como máximo 5 páginas nuevas (pruebas)

* Páginas con capa de texto: se leen con PyMuPDF. Páginas escaneadas (pocos caracteres útiles + imagen a página
  completa): OCR, solo para las páginas del subconjunto de config.yaml (extraccion.rangos_paginas).
* Cada página se guarda apenas termina (escritura atómica). Ctrl+C es seguro: la siguiente corrida continúa donde
  quedó y una corrida completa nunca repite el OCR de una página ya procesada.
* Orden del OCR: primero extraccion.prioridad_ocr (una página representativa por capítulo), luego el resto.
* Se guarda el texto CRUDO (y la geometría del OCR) además del limpio, para poder re-limpiar y auditar.

Códigos de salida: 0 = bien, 1 = error, 130 = interrumpido con Ctrl+C (reanudable).
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pymupdf  # noqa: E402

from extraction import store  # noqa: E402
from extraction.clean import (caracteres_utiles, limpiar_ocr, limpiar_pagina, porcentaje_alfabetico)  # noqa: E402
from extraction.ocr import ErrorOCR, crear_motor, ocr_pagina  # noqa: E402
from extraction.pdf_text import es_escaneada, texto_pagina  # noqa: E402
from extraction.quality_report import construir_vocabulario, tasa_palabras_conocidas  # noqa: E402
from extraction.rangos import parsear_rangos  # noqa: E402
from rag_engine.config import Config, ConfigError, cargar_config  # noqa: E402

VERSION_REGLAS = 1


@dataclass
class Resumen:
    texto: int = 0
    ocr: int = 0
    en_cache: int = 0
    relimpiadas: int = 0
    excluidas: int = 0
    segundos_ocr: list[float] = field(default_factory=list)
    interrumpido: bool = False


def orden_de_proceso(disponibles: list[int], prioridad: list[int]) -> list[int]:
    """Prioritarias primero (en el orden dado, solo las disponibles), luego el resto en orden ascendente."""
    conjunto = set(disponibles)
    primeras = [p for p in dict.fromkeys(prioridad) if p in conjunto]
    return primeras + [p for p in sorted(conjunto) if p not in set(primeras)]


def construir_entrada(doc: dict, n: int, crudo: str, escaneada: bool, ajustes: dict, motor, vocab: set[str] | None, pagina) -> dict:
    codigo = ajustes["codigo_fin_norma"].get(doc["id"])
    if escaneada:
        r = ocr_pagina(pagina, motor, ajustes["dpi"])
        limpio = limpiar_ocr(r.lineas, ajustes["ocr"]["banda_cabecera"])
        base = {"origen": "ocr", "texto_crudo": r.texto, "ocr_lineas": r.lineas, "ocr_segundos": round(r.segundos, 2),
                "ocr_motor": r.motor, "ocr_dpi": r.dpi, "confianza_ocr": round(r.confianza, 1) if r.confianza is not None else None}
    else:
        limpio = limpiar_pagina(crudo, codigo)
        base = {"origen": "texto", "texto_crudo": crudo, "ocr_segundos": None, "ocr_motor": None, "ocr_dpi": None, "confianza_ocr": None}
    texto = limpio.texto
    calidad = {"pct_alfabeticos": round(porcentaje_alfabetico(texto), 3), "confianza_ocr": base["confianza_ocr"],
               "pct_palabras_conocidas": round(tasa_palabras_conocidas(texto, vocab), 3) if (escaneada and vocab) else None}
    return {
        "documento": doc["id"], "version": doc["version"], "pagina": n, "pagina_impresa": limpio.pagina_impresa,
        "texto": texto, "caracteres": len(texto), "caracteres_utiles_crudo": caracteres_utiles(base["texto_crudo"]),
        "calidad": calidad,
        "limpieza": {"version_reglas": VERSION_REGLAS, "reglas": limpio.reglas, "cabecera_eliminada": limpio.cabecera_eliminada,
                     "pie_eliminado": limpio.pie_eliminado, "lineas_fuera_de_norma": limpio.lineas_fuera_de_norma},
        **base,
    }


def relimpiar_entrada(entrada: dict, ajustes: dict) -> dict:
    """Vuelve a aplicar la limpieza desde lo guardado (texto crudo / líneas de OCR). No toca el PDF ni el OCR."""
    if entrada["origen"] == "ocr":
        limpio = limpiar_ocr(entrada["ocr_lineas"], ajustes["ocr"]["banda_cabecera"])
    else:
        limpio = limpiar_pagina(entrada["texto_crudo"], ajustes["codigo_fin_norma"].get(entrada["documento"]))
    entrada = dict(entrada)
    entrada.update({
        "texto": limpio.texto, "caracteres": len(limpio.texto), "pagina_impresa": limpio.pagina_impresa,
        "limpieza": {"version_reglas": VERSION_REGLAS, "reglas": limpio.reglas, "cabecera_eliminada": limpio.cabecera_eliminada,
                     "pie_eliminado": limpio.pie_eliminado, "lineas_fuera_de_norma": limpio.lineas_fuera_de_norma},
    })
    entrada["calidad"] = dict(entrada["calidad"], pct_alfabeticos=round(porcentaje_alfabetico(limpio.texto), 3))
    entrada.pop("esquema", None)
    return entrada


def procesar_documento(cfg: Config, doc: dict, ajustes: dict, *, motor=None, vocab: set[str] | None = None,
                       relimpiar: bool = False, forzar: bool = False, max_paginas: int | None = None,
                       mostrar=print) -> Resumen:
    dir_doc = cfg.ruta("processed") / doc["id"]
    store.borrar_temporales(dir_doc)                       # restos de una interrupción anterior
    res = Resumen()

    if relimpiar:
        for e in store.listar_paginas(dir_doc):
            store.guardar_pagina(dir_doc, relimpiar_entrada(e, ajustes))
            res.relimpiadas += 1
        return res

    with pymupdf.open(cfg.ruta("raw") / doc["archivo"]) as pdf:
        subconjunto = parsear_rangos(ajustes["rangos_paginas"].get(doc["id"]), pdf.page_count)
        disponibles = subconjunto or list(range(1, pdf.page_count + 1))
        res.excluidas = pdf.page_count - len(disponibles)
        orden = orden_de_proceso(disponibles, ajustes["prioridad_ocr"].get(doc["id"], []))
        nuevas = 0
        motor_en_uso = motor.nombre if motor is not None else ajustes["motor_ocr"]   # la caché depende del motor REAL
        try:
            for n in orden:
                previa = None if forzar else store.leer_pagina(dir_doc, n)
                pagina = pdf[n - 1]
                crudo = texto_pagina(pagina)
                escaneada = es_escaneada(pagina, crudo, ajustes["umbral_caracteres_ocr"])
                if previa is not None and not (escaneada and (previa["origen"] != "ocr" or previa.get("ocr_motor") != motor_en_uso
                                                               or previa.get("ocr_dpi") != ajustes["dpi"])):
                    res.en_cache += 1
                    continue
                if max_paginas is not None and nuevas >= max_paginas:
                    break
                if escaneada and motor is None:
                    raise ErrorOCR(f"La página {n} de {doc['id']} es un escaneo pero no hay motor de OCR disponible.")
                t0 = time.perf_counter()
                entrada = construir_entrada(doc, n, crudo, escaneada, ajustes, motor, vocab, pagina)
                store.guardar_pagina(dir_doc, entrada)
                nuevas += 1
                if escaneada:
                    res.ocr += 1
                    res.segundos_ocr.append(entrada["ocr_segundos"])
                    mostrar(f"  {doc['id']} p{n:04d} ocr   {entrada['ocr_segundos']:5.1f}s conf={entrada['confianza_ocr']} car={entrada['caracteres']}")
                else:
                    res.texto += 1
                    mostrar(f"  {doc['id']} p{n:04d} texto {time.perf_counter() - t0:5.2f}s car={entrada['caracteres']}")
        except KeyboardInterrupt:
            res.interrumpido = True
    return res


def vocabulario_de_referencia(cfg: Config, ajustes: dict) -> set[str]:
    """Vocabulario del dominio a partir de las páginas con capa de texto ya extraídas (proxy de calidad del OCR)."""
    textos = []
    for d in cfg.documentos:
        textos += [e["texto"] for e in store.listar_paginas(cfg.ruta("processed") / d["id"]) if e["origen"] == "texto"]
    return construir_vocabulario(textos)


def escribir_articulos_modificados(cfg: Config) -> Path | None:
    """Con las páginas ya limpias del DS 001-2026-EF, escribe data/processed/articulos_modificados.json."""
    import json
    import os

    from extraction import versions_parser

    doc = cfg.documento("ds_001_2026_ef")
    with pymupdf.open(cfg.ruta("raw") / doc["archivo"]) as pdf:
        total = pdf.page_count
    entradas = store.listar_paginas(cfg.ruta("processed") / doc["id"])
    if [e["pagina"] for e in entradas] != list(range(1, total + 1)):
        return None                                   # extracción incompleta: no se genera a medias
    resultado = versions_parser.analizar([e["texto"] for e in entradas])
    datos = versions_parser.a_json(resultado, doc["id"], doc["modifica"])
    ruta = cfg.ruta("articulos_modificados")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, ruta)
    return ruta


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--solo", action="append", metavar="ID")
    ap.add_argument("--relimpiar", action="store_true")
    ap.add_argument("--forzar", action="store_true", help="rehace todas las páginas (incluido el OCR)")
    ap.add_argument("--max-paginas", type=int, default=None)
    args = ap.parse_args(argv)
    try:
        cfg = cargar_config(args.config) if args.config else cargar_config()
        docs = [cfg.documento(i) for i in args.solo] if args.solo else cfg.documentos
    except ConfigError as exc:
        print(f"ERROR de configuración: {exc}", file=sys.stderr)
        return 1
    ajustes = dict(cfg.get("extraccion"))

    # Los documentos con capa de texto van primero: su texto forma el vocabulario de referencia del OCR.
    docs = sorted(docs, key=lambda d: d["id"] == "ds_009_2025_ef")
    motor = None
    rc = 0
    for doc in docs:
        t0 = time.time()
        subset = parsear_rangos(ajustes["rangos_paginas"].get(doc["id"]))
        print(f"{doc['id']}: {'todas las páginas' if subset is None else f'{len(subset)} páginas del subconjunto'}")
        try:
            necesita_ocr = doc["id"] == "ds_009_2025_ef" and not args.relimpiar
            if necesita_ocr and motor is None:
                motor = crear_motor(ajustes["motor_ocr"], ajustes["idioma_ocr"])
            r = procesar_documento(cfg, doc, ajustes, motor=motor, vocab=None if args.relimpiar else vocabulario_de_referencia(cfg, ajustes),
                                   relimpiar=args.relimpiar, forzar=args.forzar, max_paginas=args.max_paginas)
        except ErrorOCR as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        seg = f", OCR medio {sum(r.segundos_ocr) / len(r.segundos_ocr):.1f} s/pág" if r.segundos_ocr else ""
        print(f"  => texto={r.texto} ocr={r.ocr} en_cache={r.en_cache} relimpiadas={r.relimpiadas} excluidas={r.excluidas}{seg} ({time.time() - t0:.1f} s)")
        if r.interrumpido:
            print("\nInterrumpido con Ctrl+C. Todo lo terminado quedó guardado: vuelve a ejecutar el mismo comando para continuar.")
            return 130
    if not args.solo or "ds_001_2026_ef" in args.solo:
        ruta = escribir_articulos_modificados(cfg)
        if ruta:
            print(f"articulos_modificados.json actualizado: {ruta}")
    return rc


if __name__ == "__main__":
    sys.exit(main())

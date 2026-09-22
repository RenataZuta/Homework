"""Almacenamiento de una entrada JSON por página en data/processed/<doc_id>/pNNNN.json.

Cada página se escribe apenas termina, de forma ATÓMICA (archivo temporal + rename): si el proceso se
interrumpe (Ctrl+C, corte de luz) queda una página completa o ninguna, nunca una a medias. Esto es lo que
hace reanudable el OCR: la siguiente corrida solo procesa las páginas cuyo archivo no existe.

Convención de número de página: ``pagina`` es el índice del PDF, empezando en 1 (la primera página del
archivo es la 1), no el número impreso en el papel. El número impreso, cuando se detecta, va en
``pagina_impresa``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

VERSION_ESQUEMA = 1
CAMPOS_OBLIGATORIOS = (
    "documento", "version", "pagina", "texto", "texto_crudo", "caracteres", "origen", "ocr_segundos", "calidad",
)


def ruta_pagina(dir_doc: Path, pagina: int) -> Path:
    return dir_doc / f"p{pagina:04d}.json"


def guardar_pagina(dir_doc: Path, entrada: dict) -> Path:
    faltan = [c for c in CAMPOS_OBLIGATORIOS if c not in entrada]
    if faltan:
        raise ValueError(f"La entrada de la página {entrada.get('pagina')} no tiene los campos: {', '.join(faltan)}")
    if entrada["origen"] not in ("texto", "ocr"):
        raise ValueError(f"'origen' debe ser 'texto' u 'ocr', no {entrada['origen']!r}")
    dir_doc.mkdir(parents=True, exist_ok=True)
    destino = ruta_pagina(dir_doc, entrada["pagina"])
    temporal = destino.with_suffix(".json.tmp")
    with temporal.open("w", encoding="utf-8") as f:
        json.dump({"esquema": VERSION_ESQUEMA, **entrada}, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporal, destino)
    return destino


def leer_pagina(dir_doc: Path, pagina: int) -> dict | None:
    """Devuelve la entrada o None si no existe o está corrupta (se tratará como pendiente)."""
    ruta = ruta_pagina(dir_doc, pagina)
    try:
        entrada = json.loads(ruta.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return entrada if all(c in entrada for c in CAMPOS_OBLIGATORIOS) else None


def listar_paginas(dir_doc: Path) -> list[dict]:
    """Todas las entradas válidas del documento, ordenadas por página."""
    entradas = []
    for ruta in sorted(dir_doc.glob("p[0-9][0-9][0-9][0-9].json")):
        e = leer_pagina(dir_doc, int(ruta.stem[1:]))
        if e is not None:
            entradas.append(e)
    return entradas


def borrar_temporales(dir_doc: Path) -> int:
    """Elimina restos de escrituras interrumpidas (*.json.tmp). Devuelve cuántos había."""
    restos = list(dir_doc.glob("*.json.tmp")) if dir_doc.is_dir() else []
    for r in restos:
        r.unlink(missing_ok=True)
    return len(restos)

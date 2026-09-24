"""Punto ÚNICO donde la Tarea 2 se conecta con el código de la Tarea 1 (reutilización real, no copia).

``asegurar_import_tarea1()`` añade ``../Tarea 1/src`` a ``sys.path`` (una sola vez por proceso) para que se
pueda hacer ``import rag_engine.embeddings...`` / ``import rag_engine.llm...`` con el código TAL CUAL vive en
la Tarea 1: si mañana se corrige un bug en el cliente de Gemini o se cambia el modelo local de embeddings,
la Tarea 2 lo hereda sin tocar una línea aquí.

Por qué no se copian esos módulos: duplicarlos violaría exactamente lo que pide el enunciado ("reutilizará
rag_engine de la Tarea 1") y, peor, los dos motores podrían divergir en silencio (p. ej. comparar embeddings
"locales" que en realidad ya no son el mismo modelo).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Este archivo vive en:  .../Tarea Septiembre/Tarea 2/src/radar_engine/bootstrap_t1.py
# parents[0]=radar_engine  [1]=src  [2]=Tarea 2  [3]=Tarea Septiembre
_TAREA_SEPTIEMBRE = Path(__file__).resolve().parents[3]
_TAREA1_SRC = _TAREA_SEPTIEMBRE / "Tarea 1" / "src"


class Tarea1NoEncontrada(Exception):
    """La carpeta ``../Tarea 1/src`` no existe. El motor de la Tarea 2 no puede arrancar sin ella."""


def asegurar_import_tarea1() -> Path:
    """Añade ``../Tarea 1/src`` a ``sys.path`` si no está ya. Devuelve la ruta usada."""
    if not _TAREA1_SRC.is_dir():
        raise Tarea1NoEncontrada(
            f"No se encontró '{_TAREA1_SRC}'. La Tarea 2 reutiliza rag_engine de la Tarea 1: "
            "ambas carpetas deben vivir juntas dentro de 'Tarea Septiembre/' del mismo repositorio."
        )
    ruta = str(_TAREA1_SRC)
    if ruta not in sys.path:
        sys.path.insert(0, ruta)
    return _TAREA1_SRC

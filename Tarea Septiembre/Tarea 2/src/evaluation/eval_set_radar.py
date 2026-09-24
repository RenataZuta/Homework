"""Lee ``eval/preguntas_radar.csv``: preguntas en lenguaje natural con los ``ocid`` que se esperan entre los
resultados (in_domain) o sin ninguno (out_of_domain, sirve para medir abstención). Los filtros de las
columnas ``departamento``/``categoria``/``monto_min``/``monto_max`` son EXPLÍCITOS (simulan la barra lateral
de la app); casi todas las filas los dejan vacíos a propósito, para que la evaluación también ponga a prueba
la extracción automática de filtros desde la pregunta (``radar_engine/filtros.py``).
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from radar_engine.filtros import Filtros


@dataclass(frozen=True)
class Pregunta:
    id: str
    tipo: str            # in_domain | out_of_domain
    estilo: str           # directa | coloquial
    pregunta: str
    ocids_esperados: tuple[str, ...]
    filtros: Filtros


def _float_o_none(v: str) -> float | None:
    v = (v or "").strip()
    return float(v) if v else None


def cargar_preguntas(ruta: str | Path) -> list[Pregunta]:
    with open(ruta, encoding="utf-8", newline="") as f:
        filas = list(csv.DictReader(f))
    preguntas = []
    for fila in filas:
        ocids = tuple(o.strip() for o in (fila.get("ocids_esperados") or "").split("|") if o.strip())
        filtros = Filtros(departamento=(fila.get("departamento") or "").strip() or None,
                          categoria=(fila.get("categoria") or "").strip() or None,
                          monto_min=_float_o_none(fila.get("monto_min")), monto_max=_float_o_none(fila.get("monto_max")))
        preguntas.append(Pregunta(id=fila["id"], tipo=fila["tipo"], estilo=fila["estilo"], pregunta=fila["pregunta"],
                                  ocids_esperados=ocids, filtros=filtros))
    return preguntas

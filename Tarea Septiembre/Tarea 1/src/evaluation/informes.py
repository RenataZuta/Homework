"""Escritura de tablas de resultados (CSV + Markdown) y aviso de resultados provisionales."""
from __future__ import annotations

import csv
import os
from pathlib import Path

from rag_engine.config import Config


def aviso_set(cfg: Config) -> str:
    if cfg.get("eval.set_validado"):
        return ""
    return ("> **PROVISIONAL.** Estas métricas dependen de `eval/preguntas.csv`, cuyas páginas esperadas aún no han sido validadas por la persona "
            "(Fase 3, punto manual). Se recalculan sin cambios de código cuando `eval.set_validado` pasa a `true`.\n\n")


def escribir_atomico(ruta: Path, texto: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    tmp.write_text(texto, encoding="utf-8")
    os.replace(tmp, ruta)


def escribir_csv(ruta: Path, filas: list[dict]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]))
        w.writeheader()
        w.writerows(filas)
    os.replace(tmp, ruta)


def tabla_markdown(filas: list[dict], columnas: list[tuple[str, str, str]]) -> str:
    """`columnas`: (clave, encabezado, formato). Los None se muestran como «—»."""
    def fmt(v, f):
        return "—" if v is None else (format(v, f) if f else str(v))
    L = ["| " + " | ".join(h for _, h, _ in columnas) + " |", "|" + "|".join("---" for _ in columnas) + "|"]
    for fila in filas:
        L.append("| " + " | ".join(fmt(fila.get(k), f) for k, _, f in columnas) + " |")
    return "\n".join(L)

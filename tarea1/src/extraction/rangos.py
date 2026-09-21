"""Rangos de páginas escritos como texto ("2-30, 45, 60-64"), base 1, en config.yaml."""
from __future__ import annotations

import re


def parsear_rangos(texto: str | None, total: int | None = None) -> list[int] | None:
    """"1-3, 7" -> [1, 2, 3, 7]. None/vacío -> None (todas las páginas). Valida contra `total` si se da."""
    if texto is None or not str(texto).strip():
        return None
    paginas: set[int] = set()
    for trozo in str(texto).split(","):
        trozo = trozo.strip()
        if not trozo:
            continue
        m = re.fullmatch(r"(\d+)(?:\s*-\s*(\d+))?", trozo)
        if not m:
            raise ValueError(f"Rango de páginas inválido: '{trozo}' (usa el formato '2-30, 45, 60-64')")
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        if a < 1 or b < a:
            raise ValueError(f"Rango de páginas inválido: '{trozo}'")
        paginas.update(range(a, b + 1))
    ordenadas = sorted(paginas)
    if total is not None and ordenadas and ordenadas[-1] > total:
        raise ValueError(f"El rango incluye la página {ordenadas[-1]} pero el PDF solo tiene {total}")
    return ordenadas


def formatear_rangos(paginas: list[int]) -> str:
    """[1, 2, 3, 7] -> "1-3, 7" (inverso de parsear_rangos)."""
    if not paginas:
        return ""
    ps = sorted(set(paginas))
    trozos, ini, prev = [], ps[0], ps[0]
    for p in ps[1:]:
        if p != prev + 1:
            trozos.append(f"{ini}-{prev}" if ini != prev else str(ini))
            ini = p
        prev = p
    trozos.append(f"{ini}-{prev}" if ini != prev else str(ini))
    return ", ".join(trozos)

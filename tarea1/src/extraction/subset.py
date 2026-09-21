"""Selección del subconjunto de páginas del DS 009-2025-EF que se procesan con OCR.

Reglas (deterministas; los pesos y el tamaño objetivo están en config.yaml, extraccion.subconjunto):
  1. Solo son candidatas las páginas de TEXTO. Portadas, formularios y tablas ("escasa_lectura") se excluyen: el OCR
     no las lee (a 96 DPI nativos) y no contienen normativa consultable.
  2. OBLIGATORIAS: la página donde empieza cada título, capítulo, subcapítulo, disposición y anexo detectados. Así
     el subconjunto cubre toda la estructura del Reglamento.
  3. El resto del presupuesto se llena por puntaje:  puntaje = peso_modificados × (artículos modificados por el
     DS 001-2026-EF que empiezan en la página) + peso_mype × (densidad de palabras clave útiles a una MYPE).
     Los artículos modificados pesan más: sin su texto ORIGINAL no se puede mostrar el manejo de versiones.
  4. Orden de proceso: primero las páginas obligatorias (una representativa por encabezado), luego el resto.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field


@dataclass
class Decision:
    pagina: int
    incluida: bool
    motivos: list[str] = field(default_factory=list)
    puntaje: float = 0.0
    modificados: list[int] = field(default_factory=list)
    encabezados: list[str] = field(default_factory=list)


def anclas_monotonas(pares: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """De pares (artículo, página) con ruido de OCR, conserva la subsecuencia más larga estrictamente creciente
    en artículo Y no decreciente en página. Descarta lecturas erróneas ("Artículo 479" leído en la p. 20)."""
    pares = sorted(pares)
    if not pares:
        return []
    # LIS sobre la página (los artículos ya vienen ordenados y son únicos por construcción)
    colas: list[int] = []
    indices: list[int] = []
    previo = [-1] * len(pares)
    for i, (_, pag) in enumerate(pares):
        k = bisect.bisect_right(colas, pag)
        if k == len(colas):
            colas.append(pag)
            indices.append(i)
        else:
            colas[k], indices[k] = pag, i
        previo[i] = indices[k - 1] if k > 0 else -1
    salida, i = [], indices[-1]
    while i != -1:
        salida.append(pares[i])
        i = previo[i]
    return salida[::-1]


def articulo_a_pagina(mapa: dict[int, dict], max_articulo: int) -> dict[int, int]:
    """Página de inicio (detectada o interpolada linealmente entre anclas) de cada artículo 1..max_articulo."""
    primera: dict[int, int] = {}
    for pag in sorted(mapa):
        for art in mapa[pag]["articulos"]:
            if 1 <= art <= max_articulo:
                primera.setdefault(art, pag)
    anclas = anclas_monotonas(list(primera.items()))
    if not anclas:
        return {}
    resultado: dict[int, int] = {}
    for art in range(1, max_articulo + 1):
        i = bisect.bisect_right([a for a, _ in anclas], art) - 1
        if i < 0:
            resultado[art] = anclas[0][1]
        elif anclas[i][0] == art or i == len(anclas) - 1:
            resultado[art] = anclas[i][1]
        else:
            (a1, p1), (a2, p2) = anclas[i], anclas[i + 1]
            resultado[art] = int(p1 + (art - a1) * (p2 - p1) / (a2 - a1))
    return resultado


def seleccionar(mapa: dict[int, dict], articulos_modificados: list[int], max_articulo: int, objetivo: int,
                minimo: int, pesos: dict) -> list[Decision]:
    """Devuelve una Decision por cada página del mapa (incluida o excluida, con sus motivos)."""
    a_pag = articulo_a_pagina(mapa, max_articulo)
    modificados_en: dict[int, list[int]] = {}
    for art in sorted(set(articulos_modificados)):
        if art in a_pag:
            modificados_en.setdefault(a_pag[art], []).append(art)

    decisiones = {p: Decision(pagina=p, incluida=False) for p in mapa}
    candidatas = [p for p in mapa if mapa[p]["tipo"] == "texto"]
    for p in mapa:
        if p not in candidatas:
            decisiones[p].motivos.append("escasa_lectura: portada, formulario o tabla; el OCR no la lee a 96 DPI y no es normativa consultable")

    obligatorias: list[int] = []
    for p in candidatas:
        d = decisiones[p]
        d.encabezados = [e["texto"] for e in mapa[p]["encabezados"]]
        d.modificados = modificados_en.get(p, [])
        car = max(mapa[p]["caracteres"], 1)
        densidad = sum(mapa[p]["palabras_clave"].values()) * 1000 / car
        d.puntaje = round(pesos["modificados"] * len(d.modificados) + pesos["mype"] * densidad, 3)
        if d.encabezados:
            obligatorias.append(p)
            d.incluida = True
            d.motivos.append("cobertura de estructura: empieza " + "; ".join(d.encabezados[:2]))

    if len(obligatorias) > objetivo:
        raise ValueError(f"Las {len(obligatorias)} páginas obligatorias (una por encabezado) superan el objetivo de {objetivo}; sube 'paginas_objetivo'.")

    resto = sorted((p for p in candidatas if not decisiones[p].incluida), key=lambda p: (-decisiones[p].puntaje, p))
    for p in resto[: max(objetivo, minimo) - len(obligatorias)]:
        d = decisiones[p]
        d.incluida = True
        if d.modificados:
            d.motivos.append(f"artículos modificados por el DS 001-2026-EF que empiezan aquí: {', '.join(map(str, d.modificados))}")
        if not d.modificados or d.puntaje > pesos["modificados"] * len(d.modificados):
            d.motivos.append("relevancia para una MYPE (palabras clave)")
    for rank, p in enumerate(resto[max(objetivo, minimo) - len(obligatorias):], start=1):
        decisiones[p].motivos.append(f"menor prioridad (puesto {rank} de los excluidos): sin encabezado, con {len(decisiones[p].modificados)} artículos "
                                     f"modificados y puntaje {decisiones[p].puntaje}")
    for p in obligatorias:
        d = decisiones[p]
        if d.modificados:
            d.motivos.append(f"además: artículos modificados que empiezan aquí: {', '.join(map(str, d.modificados))}")
    return [decisiones[p] for p in sorted(decisiones)]


def prioridad(decisiones: list[Decision]) -> list[int]:
    """Páginas obligatorias (una representativa por encabezado) primero, en orden de página."""
    return [d.pagina for d in decisiones if d.incluida and d.encabezados]

"""Extrae del DS 001-2026-EF qué artículos del Reglamento modifica o incorpora, y en qué página lo hace.

Estructura del decreto (verificada leyendo el PDF):
  Art. 2  "Modificar el numeral 15.1 del artículo 15; el artículo 16; …, en los siguientes términos:"
  Art. 3  "Incorporar el numeral 3.5 en el artículo 3; …, en los siguientes términos:"
  y a continuación el texto nuevo, cada artículo entre comillas:  “Artículo 15. Compradores Públicos …”
No hay derogaciones (las palabras "suprimir" que aparecen son parte del texto de los artículos).

El resultado alimenta el manejo de versiones del motor: si un fragmento del Reglamento original menciona un
artículo modificado, se marca como posiblemente desactualizado y se fuerzan los fragmentos del decreto.
"""
from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field

MARCA_PAG = "\x00P{n}\x00"
RE_ITEM_DEL = re.compile(r"^(?:el|la|los|las)\s+(?P<detalle>.+?)\s+del\s+art[ií]culo\s+(?P<art>\d+)$", re.I)
RE_ITEM_EN = re.compile(r"^(?:el|la|los|las)\s+(?P<detalle>.+?)\s+en\s+el\s+art[ií]culo\s+(?P<art>\d+)$", re.I)
RE_ITEM_ART = re.compile(r"^el\s+art[ií]culo\s+(?P<art>\d+)$", re.I)
RE_NO_ARTICULO = re.compile(r"Disposici[oó]n(?:es)?\s+Complementari|Anexo", re.I)
RE_BLOQUE = re.compile(r"“\s*Art[ií]culo\s+(\d+)\s*\.")


@dataclass
class Cambio:
    articulo: int
    tipo: str                      # "modifica" | "incorpora"
    detalle: str
    pagina_ds001: int | None = None
    fuente: str = ""               # "Artículo 2" | "Artículo 3" del decreto


@dataclass
class Resultado:
    cambios: list[Cambio] = field(default_factory=list)
    otras_disposiciones: list[dict] = field(default_factory=list)
    sin_bloque_citado: list[int] = field(default_factory=list)
    bloque_sin_lista: list[tuple[str, int]] = field(default_factory=list)   # citado en el texto pero no enumerado


def _plano(texto: str) -> str:
    return re.sub(r"[ \t\r\n]+", " ", texto)


def _unir_paginas(paginas: list[str]) -> tuple[str, list[int], list[int]]:
    """Une las páginas en un texto plano CON marcas de posición (solo para localizar, nunca para trocear)."""
    trozos, inicios, numeros, pos = [], [], [], 0
    for n, t in enumerate(paginas, 1):
        p = _plano(t) + " "
        inicios.append(pos)
        numeros.append(n)
        trozos.append(p)
        pos += len(p)
    return "".join(trozos), inicios, numeros


def _pagina_de(pos: int, inicios: list[int], numeros: list[int]) -> int:
    return numeros[bisect.bisect_right(inicios, pos) - 1]


def _lista(texto: str, arranque: str, hasta: str) -> str:
    """Devuelve la enumeración entre `arranque` (p. ej. 'Modificar') y 'en los siguientes términos'."""
    i = texto.index(arranque)
    j = texto.index("en los siguientes términos", i)
    return texto[i + len(arranque): j].strip().rstrip(",")


def _items(lista: str) -> list[str]:
    lista = re.sub(r",?\s+(?:en|del|al)\s+(?:el\s+)?Reglamento de la Ley\s+N[º°o]\s*32069.*$", "", lista)  # cola común
    partes = re.split(r";\s*(?:así como\s+|y\s+)?", lista)
    # Un "y" sin ";" también puede unir dos ítems ("…en el artículo 373 y los numerales 5, 6…"): se separa solo
    # cuando lo que sigue empieza con artículo determinado; "42.2 y 42.3" o "a), b) y h)" no se tocan.
    items: list[str] = []
    for parte in partes:
        items += re.split(r"\s+y\s+(?=(?:el|la|los|las)\s)", parte.strip())
    return [i.strip().rstrip(",").strip() for i in items if i.strip()]


def analizar(paginas: list[str]) -> Resultado:
    """`paginas`: texto LIMPIO de cada página del DS 001 (índice 0 = página 1)."""
    texto, inicios, numeros = _unir_paginas(paginas)
    i2, i3, i4 = texto.index("Artículo 2.-"), texto.index("Artículo 3.-"), texto.index("Artículo 4.-")
    secciones = {"modifica": ("Artículo 2", i2, i3), "incorpora": ("Artículo 3", i3, i4)}

    # bloques citados: (artículo, posición, sección)
    bloques: dict[tuple[str, int], int] = {}
    for m in RE_BLOQUE.finditer(texto):
        for tipo, (_, ini, fin) in secciones.items():
            if ini <= m.start() < fin:
                bloques.setdefault((tipo, int(m.group(1))), _pagina_de(m.start(), inicios, numeros))

    res = Resultado()
    for tipo, (nombre, ini, fin) in secciones.items():
        seccion = texto[ini:fin]
        lista = _lista(seccion, "Modificar" if tipo == "modifica" else "Incorporar", "en los siguientes términos")
        for item in _items(lista):
            if RE_NO_ARTICULO.search(item) and not re.search(r"art[ií]culo\s+\d+", item, re.I):
                res.otras_disposiciones.append({"tipo": tipo, "elemento": item, "fuente": nombre})
                continue
            for patron in (RE_ITEM_DEL, RE_ITEM_EN, RE_ITEM_ART):
                m = patron.match(item)
                if m:
                    art = int(m.group("art"))
                    detalle = m.groupdict().get("detalle") or "artículo completo"
                    res.cambios.append(Cambio(art, tipo, detalle, bloques.get((tipo, art)), nombre))
                    break
            else:
                res.otras_disposiciones.append({"tipo": tipo, "elemento": item, "fuente": nombre, "sin_clasificar": True})
    res.sin_bloque_citado = sorted({c.articulo for c in res.cambios if c.pagina_ds001 is None})
    enumerados = {(c.tipo, c.articulo) for c in res.cambios}
    res.bloque_sin_lista = sorted(k for k in bloques if k not in enumerados)
    return res


def a_json(res: Resultado, norma_modificatoria: str, norma_modificada: str) -> dict:
    por_art: dict[int, list[str]] = {}
    for c in res.cambios:
        por_art.setdefault(c.articulo, []).append(c.tipo)
    return {
        "norma_modificatoria": norma_modificatoria,
        "norma_modificada": norma_modificada,
        "convencion_pagina": "pagina_ds001 = número de página del PDF del DS 001-2026-EF (1 = primera)",
        "resumen": {
            "articulos_distintos": len(por_art),
            "cambios_modifica": sum(c.tipo == "modifica" for c in res.cambios),
            "cambios_incorpora": sum(c.tipo == "incorpora" for c in res.cambios),
            "otras_disposiciones": len(res.otras_disposiciones),
            "sin_bloque_citado": res.sin_bloque_citado,
            "bloques_citados_no_enumerados": [{"tipo": t, "articulo": a} for t, a in res.bloque_sin_lista],
        },
        "cambios": [
            {"articulo": c.articulo, "tipo": c.tipo, "detalle": c.detalle, "pagina_ds001": c.pagina_ds001, "fuente": c.fuente}
            for c in sorted(res.cambios, key=lambda c: (c.articulo, c.tipo))
        ],
        "otras_disposiciones": res.otras_disposiciones,
    }

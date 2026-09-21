"""Detección de estructura (títulos, capítulos, artículos) en el texto de una página, tolerante a errores de OCR.

Se usa en el paso de MAPEO del DS 009-2025-EF: antes de decidir qué páginas se procesan con OCR hay que saber
dónde empieza cada título y capítulo. El mapeo guarda solo estructura y conteos, no el texto de las páginas.
"""
from __future__ import annotations

import re
import unicodedata

ROMANOS = r"[IVXLC1l|]{1,6}"
RE_TITULO = re.compile(rf"^\W{{0,3}}T[IÍ]TULO\s+({ROMANOS}|PRELIMINAR|[ÚU]NICO)\b\s*(.*)$", re.I)
RE_CAPITULO = re.compile(rf"^\W{{0,3}}CAP[IÍ]TULO\s+({ROMANOS}|[ÚU]NICO)\b\s*(.*)$", re.I)
RE_SUBCAPITULO = re.compile(rf"^\W{{0,3}}(SUBCAP[IÍ]TULO|SECCI[OÓ]N)\s+({ROMANOS}|[ÚU]NICA?)\b\s*(.*)$", re.I)
RE_DISPOSICION = re.compile(r"^\W{0,3}(DISPOSICI[OÓ]N(?:ES)?\s+COMPLEMENTARIAS?\s+(?:FINAL(?:ES)?|TRANSITORIAS?|DEROGATORIAS?|MODIFICATORIAS?))\b", re.I)
RE_ANEXO = re.compile(rf"^\W{{0,3}}ANEXO\s*({ROMANOS}|\d{{1,2}}|[A-Z])?\b\s*(.*)$")
# Encabezado de artículo tolerante a OCR: "Artículo 69." / "Articulo 69, Contenido" (coma en vez de punto) /
# "Artículo-64." / variantes de la palabra ("Aríículo", "Artfculo"). Solo al INICIO de línea y con mayúscula inicial:
# las referencias en minúscula dentro de una frase ("… del artículo 69 de la Ley") no cuentan.
RE_ARTICULO = re.compile(r"^\W{0,3}A[rn][tíf1l][íi1lf]?c[uo]l[oa0][\s\-]{0,2}(\d{1,3})\s*[.,\-–°º:]")


def sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def _es_mayusculas(linea: str) -> bool:
    letras = [c for c in linea if c.isalpha()]
    return len(letras) >= 4 and sum(c.isupper() for c in letras) / len(letras) > 0.8


def analizar_pagina(texto: str, palabras_clave: dict[str, list[str]] | None = None) -> dict:
    """Devuelve encabezados de estructura, números de artículo y conteos de palabras clave de UNA página."""
    lineas = [l.strip() for l in texto.split("\n")]
    encabezados: list[dict] = []
    articulos: list[int] = []
    for i, linea in enumerate(lineas):
        if not linea:
            continue
        if m := RE_ARTICULO.match(linea):
            articulos.append(int(m.group(1)))
            continue
        for nivel, patron in (("titulo", RE_TITULO), ("capitulo", RE_CAPITULO), ("subcapitulo", RE_SUBCAPITULO)):
            if m := patron.match(linea):
                if not (linea.isupper() or _es_mayusculas(linea) or linea[:3].upper() == linea[:3]):
                    break  # una frase que solo empieza con "Título…" no es un encabezado
                resto = m.group(m.lastindex).strip()
                if not resto and i + 1 < len(lineas) and lineas[i + 1] and _es_mayusculas(lineas[i + 1]):
                    resto = lineas[i + 1]
                encabezados.append({"nivel": nivel, "texto": re.sub(r"\s+", " ", f"{linea.split()[0]} {m.group(m.lastindex - 1) if patron is RE_SUBCAPITULO else m.group(1)} {resto}".strip())})
                break
        else:
            if m := RE_DISPOSICION.match(linea):
                encabezados.append({"nivel": "disposicion", "texto": re.sub(r"\s+", " ", m.group(1).upper())})
            elif (m := RE_ANEXO.match(linea)) and _es_mayusculas(linea) and len(linea) < 80:
                encabezados.append({"nivel": "anexo", "texto": re.sub(r"\s+", " ", linea)})
    plano = sin_tildes(texto).lower()
    conteos = {}
    for grupo, terminos in (palabras_clave or {}).items():
        n = sum(plano.count(sin_tildes(t).lower()) for t in terminos)
        if n:
            conteos[grupo] = n
    return {"encabezados": encabezados, "articulos": articulos, "palabras_clave": conteos}

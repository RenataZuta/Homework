"""Lectura de texto por página con PyMuPDF y detección de páginas escaneadas.

La página viaja como metadato desde este primer paso: cada función trabaja sobre UNA página. Nunca se une el
documento entero en un solo string para trocearlo después (se perderían las citas). Quien procesa abre el PDF
(``with pymupdf.open(ruta) as pdf``) y mantiene el documento abierto mientras use sus páginas.
"""
from __future__ import annotations

import pymupdf

from extraction.clean import caracteres_utiles


def cobertura_de_imagen(pagina: pymupdf.Page) -> float:
    """Fracción del área de la página cubierta por imágenes realmente dibujadas en ella.

    Ojo: ``page.get_images()`` NO sirve aquí: en el DS 009 devuelve el diccionario de recursos compartido por
    las 196 páginas. ``get_image_info()`` sí lista solo las imágenes dibujadas en esta página.
    """
    area = pagina.rect.width * pagina.rect.height
    if area <= 0:
        return 0.0
    cubierto = 0.0
    for im in pagina.get_image_info():
        r = pymupdf.Rect(im["bbox"]) & pagina.rect
        cubierto += max(r.width, 0) * max(r.height, 0)
    return min(cubierto / area, 1.0)


def es_escaneada(pagina: pymupdf.Page, texto_crudo: str, umbral_caracteres: int, cobertura_minima: float = 0.5) -> bool:
    """Una página necesita OCR si tiene pocos caracteres útiles Y una imagen que ocupa casi toda la página.

    La segunda condición evita mandar a OCR una página legítima casi vacía (p. ej. la última de un documento).
    """
    return caracteres_utiles(texto_crudo) < umbral_caracteres and cobertura_de_imagen(pagina) >= cobertura_minima


def texto_pagina(pagina: pymupdf.Page) -> str:
    """Texto crudo de UNA página (con la capa de texto del PDF; vacío si es un escaneo)."""
    return pagina.get_text("text")

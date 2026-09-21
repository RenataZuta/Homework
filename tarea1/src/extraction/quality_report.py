"""Métricas de calidad de extracción (y, más adelante, el reporte por documento)."""
from __future__ import annotations

import re

RE_PALABRA = re.compile(r"[a-záéíóúüñ]{3,}")


def palabras(texto: str) -> list[str]:
    """Palabras de 3+ letras en minúscula (el proxy de calidad ignora números y siglas cortas)."""
    return RE_PALABRA.findall(texto.lower())


def construir_vocabulario(textos: list[str]) -> set[str]:
    vocab: set[str] = set()
    for t in textos:
        vocab.update(palabras(t))
    return vocab


def tasa_palabras_conocidas(texto: str, vocabulario: set[str]) -> float:
    """Fracción de palabras del texto que existen en el vocabulario de referencia (0.0 si no hay palabras).

    Es un PROXY de la exactitud del OCR: una palabra mal reconocida ("Articulo" sin tilde, "mvolucrados")
    cae fuera del vocabulario. El vocabulario sale de textos con capa de texto exacta del mismo dominio, así
    que los términos legítimos casi siempre están. No sustituye a una transcripción de referencia.
    """
    ws = palabras(texto)
    return sum(w in vocabulario for w in ws) / len(ws) if ws else 0.0


def cambios_de_columna(lineas: list[list], corte_x: float = 0.5) -> int:
    """Cuántas veces el orden de lectura salta entre la columna izquierda y la derecha.

    En una página de dos columnas bien leída el texto baja por la izquierda y luego por la derecha: 1 salto.
    Muchos saltos delatan columnas MEZCLADAS (línea 1 izquierda, línea 1 derecha, línea 2 izquierda…).
    Solo se consideran líneas de cuerpo (con texto de 12+ caracteres, para ignorar títulos centrados y números).
    """
    lado = [0 if l[3] < corte_x else 1 for l in lineas if len(l[2]) >= 12]
    return sum(1 for a, b in zip(lado, lado[1:]) if a != b)

"""OCR de páginas escaneadas. Cada motor recibe una imagen y devuelve texto + confianza.

Motores (se elige con ``extraccion.motor_ocr`` en config.yaml; la elección está justificada con el
mini-benchmark de scripts/ocr_benchmark.py, no por costumbre):

* ``tesseract``: LSTM (--oem 1) con análisis de diseño automático (--psm 3), idioma ``spa``. Necesita el
  ejecutable instalado; su ruta se toma de la variable TESSERACT_CMD (.env) o del PATH.
* ``easyocr``: detección CRAFT + reconocimiento CRNN. No hace análisis de columnas: aquí se le da la pista
  de diseño de 2 columnas (los cuerpos de El Peruano lo son), lo que le da ventaja en la comparación.

La página se rasteriza con PyMuPDF a un DPI configurable. La imagen incrustada del DS 009-2025-EF es de
96 DPI nativos: subir el DPI solo interpola, y el benchmark mide si aun así ayuda.
"""
from __future__ import annotations

import io
import os
import shutil
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import pymupdf
from PIL import Image


class ErrorOCR(Exception):
    """El motor de OCR no está disponible o falló (mensaje pensado para el usuario)."""


@dataclass
class ResultadoOCR:
    texto: str
    confianza: float | None      # 0-100, media por palabra; None si el motor no la da
    segundos: float              # rasterizar + reconocer
    motor: str
    dpi: int
    n_palabras: int
    # [[y_superior_frac_altura, nº_de_bloque, texto, x_izquierda_frac_ancho], ...]: permite limpiar por POSICIÓN
    # (p. ej. la banda de cabecera) sin depender de lo que el OCR haya leído en ella.
    lineas: list[list] = field(default_factory=list)


class Motor(Protocol):
    nombre: str

    def reconocer(self, imagen: Image.Image) -> tuple[str, float | None, int, list[list]]:
        """Devuelve (texto, confianza_media_0_100, n_palabras, líneas[y_frac, bloque, texto])."""


def rasterizar(pagina: pymupdf.Page, dpi: int) -> Image.Image:
    """Página -> imagen en escala de grises al DPI pedido."""
    pix = pagina.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")


class MotorTesseract:
    nombre = "tesseract"

    def __init__(self, idioma: str = "spa", comando: str | None = None, psm: int = 3, oem: int = 1):
        try:
            import pytesseract
        except ImportError as exc:
            raise ErrorOCR("Falta el paquete pytesseract (pip install pytesseract).") from exc
        comando = comando or os.environ.get("TESSERACT_CMD", "").strip() or shutil.which("tesseract")
        if not comando or not os.path.exists(comando):
            raise ErrorOCR(
                "No se encontró Tesseract. Instálalo (Windows: instalador de UB-Mannheim, marcando el idioma Spanish) "
                "y define TESSERACT_CMD en .env con la ruta completa a tesseract.exe.")
        pytesseract.pytesseract.tesseract_cmd = comando
        self._pt, self.idioma, self.comando = pytesseract, idioma, comando
        self._config = f"--oem {oem} --psm {psm}"
        try:
            idiomas = self._pt.get_languages(config="")
        except Exception as exc:
            raise ErrorOCR(f"Tesseract no responde ({comando}): {exc}") from exc
        if idioma not in idiomas:
            raise ErrorOCR(f"Tesseract no tiene el idioma '{idioma}' (disponibles: {', '.join(sorted(idiomas)[:8])}…). "
                           f"Instala el paquete de idioma Spanish.")

    def reconocer(self, imagen: Image.Image) -> tuple[str, float | None, int, list[list]]:
        d = self._pt.image_to_data(imagen, lang=self.idioma, config=self._config, output_type=self._pt.Output.DICT)
        alto, ancho = float(imagen.height), float(imagen.width)
        lineas: list[list] = []          # [y_frac, bloque, texto, x_frac]
        clave_linea = None
        confs: list[float] = []
        n = 0
        for i, palabra in enumerate(d["text"]):
            palabra = palabra.strip()
            if not palabra or float(d["conf"][i]) < 0:
                continue
            clave = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
            arriba, izquierda = d["top"][i] / alto, d["left"][i] / ancho
            if clave != clave_linea:
                lineas.append([arriba, d["block_num"][i], palabra, izquierda])
                clave_linea = clave
            else:
                lineas[-1][0] = min(lineas[-1][0], arriba)
                lineas[-1][3] = min(lineas[-1][3], izquierda)
                lineas[-1][2] += " " + palabra
            confs.append(float(d["conf"][i]))
            n += 1
        lineas = [[round(y, 4), b, t, round(x, 4)] for y, b, t, x in lineas]
        return texto_desde_lineas(lineas), (sum(confs) / len(confs) if confs else None), n, lineas


def texto_desde_lineas(lineas: list[list]) -> str:
    """Reconstruye el texto: un salto por línea y una línea en blanco entre bloques de texto distintos."""
    salida: list[str] = []
    bloque_previo = None
    for _, bloque, texto, *_ in lineas:
        if bloque_previo is not None and bloque != bloque_previo:
            salida.append("")
        salida.append(texto)
        bloque_previo = bloque
    return "\n".join(salida)


class MotorEasyOCR:
    nombre = "easyocr"

    def __init__(self, idiomas: tuple[str, ...] = ("es",)):
        try:
            import easyocr
        except ImportError as exc:
            raise ErrorOCR("Falta el paquete easyocr (pip install easyocr).") from exc
        self._lector = easyocr.Reader(list(idiomas), gpu=False, verbose=False)

    def reconocer(self, imagen: Image.Image) -> tuple[str, float | None, int, list[list]]:
        import numpy as np
        ancho = imagen.width
        cajas = self._lector.readtext(np.array(imagen), detail=1, paragraph=False)
        # Pista de diseño: 2 columnas. Columna = mitad izquierda/derecha por el centro horizontal de la caja.
        elementos = []
        for caja, texto, conf in cajas:
            xs = [p[0] for p in caja]
            ys = [p[1] for p in caja]
            centro_x, arriba = sum(xs) / 4, min(ys)
            elementos.append((0 if centro_x < ancho / 2 else 1, arriba, min(xs), texto.strip(), float(conf) * 100))
        elementos = [e for e in elementos if e[3]]
        lineas: list[str] = []
        for col in (0, 1):
            fila: list[tuple[float, float, str]] = []
            ultima_y = None
            for _, y, x, texto, _c in sorted((e for e in elementos if e[0] == col), key=lambda e: (round(e[1] / 6), e[2])):
                if ultima_y is not None and abs(y - ultima_y) > 8 and fila:
                    lineas.append(" ".join(t for _, _, t in sorted(fila, key=lambda f: f[0])))
                    fila = []
                fila.append((x, y, texto))
                ultima_y = y if not fila[:-1] else ultima_y
            if fila:
                lineas.append(" ".join(t for _, _, t in sorted(fila, key=lambda f: f[0])))
        confs = [e[4] for e in elementos]
        # EasyOCR no da líneas con posición fiable tras el reordenado por columnas: se reporta y=0 y bloque=0
        return "\n".join(lineas), (sum(confs) / len(confs) if confs else None), len(elementos), [[0.0, 0, l, 0.0] for l in lineas]


def crear_motor(nombre: str, idioma: str = "spa") -> Motor:
    """Fábrica: el nombre viene de config.yaml (extraccion.motor_ocr)."""
    if nombre == "tesseract":
        return MotorTesseract(idioma=idioma)
    if nombre == "easyocr":
        return MotorEasyOCR(("es",))
    raise ErrorOCR(f"Motor de OCR desconocido: '{nombre}'. Opciones: tesseract, easyocr.")


def ocr_pagina(pagina: pymupdf.Page, motor: Motor, dpi: int) -> ResultadoOCR:
    """Rasteriza y reconoce una página midiendo el tiempo total."""
    t0 = time.perf_counter()
    imagen = rasterizar(pagina, dpi)
    texto, confianza, n, lineas = motor.reconocer(imagen)
    return ResultadoOCR(texto=texto, confianza=confianza, segundos=time.perf_counter() - t0,
                        motor=motor.nombre, dpi=dpi, n_palabras=n, lineas=lineas)

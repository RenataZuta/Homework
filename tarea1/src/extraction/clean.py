"""Limpieza de texto de página. Reglas documentadas (regex + posición); ninguna se aplica "en cualquier parte".

R1  Cabecera de El Peruano. Solo si al INICIO de la página hay una cabecera con la firma completa
    ``[nº de página] · NORMAS LEGALES · [fecha] · El Peruano [/]`` se elimina ese bloque contiguo.
    Las líneas tipo "33", "NORMAS LEGALES" o "El Peruano" en el CUERPO de la página nunca se tocan, y una
    página que empieza con "Artículo N" no tiene firma de cabecera, así que queda intacta.
R2  Sello de firma digital al FINAL de la página ("Firmado por: …" y "Fecha: dd/mm/aaaa hh:mm").
R3  Fin de norma. El PDF de El Peruano incluye páginas de la edición completa: tras el código de cierre
    de la norma (p. ej. ``2474920-3``) sigue texto de OTRAS normas. Si config.yaml declara ``codigo_fin_norma``
    para el documento, se descarta todo lo que sigue a esa línea (queda en ``texto_crudo``, auditable).
R1o Cabecera en páginas ESCANEADAS (OCR). El texto que el OCR lee en la cabecera es impredecible (a 200 DPI sale
    "Miércoses 22 48 enero de 2005 / E54 ElPerano", a 300 a veces solo "10" o nada), así que aquí la regla es de
    POSICIÓN: se descartan las líneas cuyo borde superior cae en la banda superior de la página
    (``extraccion.ocr.banda_cabecera``, fracción de la altura), sea cual sea el texto leído.
R4  Espacios: NBSP -> espacio, sin caracteres de ancho cero, sin espacios al final de línea, a lo más una
    línea en blanco seguida y sin blancos al inicio/fin. Los saltos de línea se conservan; NO se quitan
    guiones de fin de línea (rompería "009-2025-\\nEF").
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

RE_NUMERO_PAGINA = re.compile(r"^\d{1,4}$")
RE_NORMAS_LEGALES = re.compile(r"^NORMAS\s+LEGALES$", re.IGNORECASE)
RE_FECHA_EDICION = re.compile(
    r"^(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\s+\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4}$",
    re.IGNORECASE,
)
RE_EL_PERUANO = re.compile(r"^El\s+Peruano\s*/?$", re.IGNORECASE)
RE_BARRA = re.compile(r"^/$")
RE_FIRMADO_POR = re.compile(r"^Firmado\s+por\s*:", re.IGNORECASE)
RE_FECHA_FIRMA = re.compile(r"^Fecha\s*:\s*\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}$", re.IGNORECASE)

MAX_LINEAS_CABECERA = 8
_CARACTERES_ANCHO_CERO = dict.fromkeys(map(ord, "​‌‍⁠﻿"), None)


@dataclass
class ResultadoLimpieza:
    texto: str
    pagina_impresa: int | None = None
    cabecera_eliminada: list[str] = field(default_factory=list)
    pie_eliminado: list[str] = field(default_factory=list)
    lineas_fuera_de_norma: int = 0
    reglas: list[str] = field(default_factory=list)


def normalizar_espacios(texto: str) -> str:
    """R4."""
    texto = texto.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ").translate(_CARACTERES_ANCHO_CERO)
    lineas = [re.sub(r"[ \t]+", " ", l).strip() if l.strip() else "" for l in texto.split("\n")]
    salida, en_blanco = [], 0
    for linea in lineas:
        if linea == "":
            en_blanco += 1
            if en_blanco > 1:
                continue
        else:
            en_blanco = 0
        salida.append(linea)
    return "\n".join(salida).strip("\n")


def _quitar_cabecera(lineas: list[str]) -> tuple[list[str], list[str], int | None]:
    """R1. Devuelve (lineas_restantes, lineas_eliminadas, nº_de_página_impreso)."""
    no_vacias = [(i, l.strip()) for i, l in enumerate(lineas) if l.strip()][:MAX_LINEAS_CABECERA]
    pos_normas = next((k for k, (_, l) in enumerate(no_vacias) if RE_NORMAS_LEGALES.match(l)), None)
    if pos_normas is None or pos_normas > 1:
        return lineas, [], None  # sin firma de cabecera: no se toca nada

    consumidas: list[tuple[int, str]] = []
    pagina_impresa = None
    k = 0
    if pos_normas == 1:  # el nº de página va ANTES de "NORMAS LEGALES"
        if not RE_NUMERO_PAGINA.match(no_vacias[0][1]):
            return lineas, [], None
        pagina_impresa = int(no_vacias[0][1])
        consumidas.append(no_vacias[0])
        k = 1
    consumidas.append(no_vacias[k])  # "NORMAS LEGALES"
    k += 1
    vio_fecha = vio_peruano = False
    while k < len(no_vacias):
        i, l = no_vacias[k]
        if RE_FECHA_EDICION.match(l) and not vio_fecha:
            vio_fecha = True
        elif RE_EL_PERUANO.match(l) and not vio_peruano:
            vio_peruano = True
        elif RE_BARRA.match(l) and vio_peruano:
            pass
        else:
            break
        consumidas.append((i, l))
        k += 1
    if not (vio_fecha and vio_peruano):
        return lineas, [], None  # firma incompleta: por prudencia no se borra nada
    ultimo = consumidas[-1][0]
    return lineas[ultimo + 1:], [l for _, l in consumidas], pagina_impresa


def _quitar_sello_firma(lineas: list[str]) -> tuple[list[str], list[str]]:
    """R2. Consume desde el final mientras las líneas sean parte del sello."""
    fin = len(lineas)
    eliminadas: list[str] = []
    while fin > 0:
        l = lineas[fin - 1].strip()
        if not l:
            fin -= 1
        elif RE_FIRMADO_POR.match(l) or RE_FECHA_FIRMA.match(l):
            eliminadas.insert(0, l)
            fin -= 1
        else:
            break
    return lineas[:fin], eliminadas


def _cortar_fin_de_norma(lineas: list[str], codigo: str) -> tuple[list[str], int]:
    """R3."""
    for i, l in enumerate(lineas):
        if l.strip() == codigo:
            return lineas[:i], len(lineas) - i
    return lineas, 0


def limpiar_pagina(texto_crudo: str, codigo_fin_norma: str | None = None) -> ResultadoLimpieza:
    """Aplica R1-R4 y devuelve el texto limpio con el detalle de lo eliminado."""
    lineas = texto_crudo.replace("\r\n", "\n").replace("\xa0", " ").split("\n")
    res = ResultadoLimpieza(texto="")

    lineas, res.cabecera_eliminada, res.pagina_impresa = _quitar_cabecera(lineas)
    if res.cabecera_eliminada:
        res.reglas.append("R1_cabecera_el_peruano")
    lineas, res.pie_eliminado = _quitar_sello_firma(lineas)
    if res.pie_eliminado:
        res.reglas.append("R2_sello_firma")
    if codigo_fin_norma:
        lineas, res.lineas_fuera_de_norma = _cortar_fin_de_norma(lineas, codigo_fin_norma)
        if res.lineas_fuera_de_norma:
            res.reglas.append("R3_fin_de_norma")
    res.texto = normalizar_espacios("\n".join(lineas))
    return res


def limpiar_ocr(lineas: list[list], banda_cabecera: float) -> ResultadoLimpieza:
    """R1o + R4 sobre las líneas de OCR ``[y_frac, bloque, texto]``.

    Lo descartado se guarda en ``cabecera_eliminada`` para poder auditarlo (y queda también en ``texto_crudo``).
    """
    from extraction.ocr import texto_desde_lineas  # import local: clean.py no depende del OCR salvo aquí

    res = ResultadoLimpieza(texto="")
    conservadas = [l for l in lineas if l[0] >= banda_cabecera]
    res.cabecera_eliminada = [l[2] for l in lineas if l[0] < banda_cabecera]
    if res.cabecera_eliminada:
        res.reglas.append("R1o_banda_cabecera")
    res.texto = normalizar_espacios(texto_desde_lineas(conservadas))
    return res


def caracteres_utiles(texto: str) -> int:
    """Cuenta letras y dígitos: es lo que decide si una página tiene texto o necesita OCR."""
    return sum(c.isalnum() for c in texto)


def porcentaje_alfabetico(texto: str) -> float:
    """Proporción de letras entre los caracteres que no son espacio (0.0 si no hay ninguno)."""
    sin_espacios = [c for c in texto if not c.isspace()]
    return sum(c.isalpha() for c in sin_espacios) / len(sin_espacios) if sin_espacios else 0.0

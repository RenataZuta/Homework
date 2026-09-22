"""OCR: reconstrucción de texto, limpieza por posición y una prueba real con Tesseract (se omite si no está)."""
import os
import shutil

import pymupdf
import pytest

from extraction.clean import limpiar_ocr
from extraction.ocr import ErrorOCR, crear_motor, ocr_pagina, texto_desde_lineas

LINEAS = [
    [0.085, 1, "NORMAS LEGALES"],
    [0.088, 2, "Miércoses 22 48 enero de 2005 / E54 ElPerano"],      # cabecera ilegible, tal como la lee Tesseract a 200 DPI
    [0.110, 3, "años, aplicando estándares internacionales"],
    [0.122, 3, "de seguridad de la información."],
    [0.160, 4, "Artículo 257. Obligatoriedad"],
]


def test_texto_desde_lineas_separa_bloques_con_linea_en_blanco():
    assert texto_desde_lineas(LINEAS) == (
        "NORMAS LEGALES\n\nMiércoses 22 48 enero de 2005 / E54 ElPerano\n\n"
        "años, aplicando estándares internacionales\nde seguridad de la información.\n\nArtículo 257. Obligatoriedad")


def test_limpiar_ocr_descarta_la_banda_superior_sin_mirar_el_texto():
    r = limpiar_ocr(LINEAS, banda_cabecera=0.10)
    assert r.cabecera_eliminada == ["NORMAS LEGALES", "Miércoses 22 48 enero de 2005 / E54 ElPerano"]
    assert r.texto == "años, aplicando estándares internacionales\nde seguridad de la información.\n\nArtículo 257. Obligatoriedad"
    assert r.reglas == ["R1o_banda_cabecera"]


def test_limpiar_ocr_no_toca_una_pagina_sin_nada_en_la_banda():
    r = limpiar_ocr(LINEAS[2:], banda_cabecera=0.10)
    assert r.cabecera_eliminada == [] and r.reglas == [] and r.texto.startswith("años, aplicando")


def test_limpiar_ocr_conserva_una_linea_que_empieza_justo_en_el_limite():
    assert "borde" in limpiar_ocr([[0.10, 1, "borde"]], banda_cabecera=0.10).texto


def test_el_motor_desconocido_da_un_error_claro():
    with pytest.raises(ErrorOCR, match="desconocido"):
        crear_motor("magia")


def test_tesseract_sin_ejecutable_da_instrucciones(monkeypatch):
    monkeypatch.setenv("TESSERACT_CMD", "/ruta/que/no/existe/tesseract")
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(ErrorOCR, match="TESSERACT_CMD"):
        crear_motor("tesseract")


# ── prueba real: solo si Tesseract está disponible ──

def _tesseract_disponible() -> bool:
    ruta = os.environ.get("TESSERACT_CMD", "").strip() or shutil.which("tesseract")
    return bool(ruta) and os.path.exists(ruta)


@pytest.mark.skipif(not _tesseract_disponible(), reason="Tesseract no está instalado / TESSERACT_CMD no definido")
def test_tesseract_real_da_posicion_y_permite_quitar_la_cabecera(tmp_path):
    doc = pymupdf.open()
    pag = doc.new_page()                                                    # 595 x 842 pt
    pag.insert_text((72, 60), "NORMAS LEGALES  Miércoles 22 de enero de 2025", fontsize=14)   # banda superior (60/842 = 7 %)
    pag.insert_textbox(pymupdf.Rect(72, 160, 520, 400),
                       "Artículo 257. Obligatoriedad y valor legal del uso de la Pladicop.\n"
                       "Los actos y procedimientos se llevan a cabo a través de la plataforma.", fontsize=13)
    motor = crear_motor("tesseract", "spa")
    r = ocr_pagina(pag, motor, dpi=200)
    assert r.n_palabras > 10 and r.confianza and r.confianza > 60
    ys = [l[0] for l in r.lineas]
    assert ys == sorted(ys), "las líneas deben venir de arriba hacia abajo"
    assert r.lineas[0][0] < 0.10 < r.lineas[1][0]                          # cabecera arriba, cuerpo después
    limpio = limpiar_ocr(r.lineas, banda_cabecera=0.10)
    assert "NORMAS" in r.texto and "NORMAS" not in limpio.texto             # antes / después
    assert "Obligatoriedad" in limpio.texto and limpio.cabecera_eliminada


# ── orden de lectura: saltos entre columnas ──

def test_cambios_de_columna_una_pagina_bien_leida_tiene_un_salto():
    from extraction.quality_report import cambios_de_columna
    izq = [[0.1 + i * 0.02, 1, f"texto de la columna izquierda {i}", 0.08] for i in range(5)]
    der = [[0.1 + i * 0.02, 2, f"texto de la columna derecha {i}", 0.52] for i in range(5)]
    assert cambios_de_columna(izq + der) == 1


def test_cambios_de_columna_detecta_columnas_mezcladas():
    from extraction.quality_report import cambios_de_columna
    mezcladas = []
    for i in range(5):
        mezcladas.append([0.1 + i * 0.02, 1, f"texto de la columna izquierda {i}", 0.08])
        mezcladas.append([0.1 + i * 0.02, 2, f"texto de la columna derecha {i}", 0.52])
    assert cambios_de_columna(mezcladas) == 9


def test_cambios_de_columna_ignora_lineas_cortas_y_titulos():
    from extraction.quality_report import cambios_de_columna
    lineas = [[0.1, 1, "60", 0.9], [0.1, 1, "izquierda con texto suficiente", 0.08], [0.2, 2, "derecha con texto suficiente", 0.52], [0.3, 3, "ok", 0.08]]
    assert cambios_de_columna(lineas) == 1

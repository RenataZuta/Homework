"""Detección de páginas escaneadas con PDFs sintéticos (sin depender de los PDFs oficiales)."""
import io

import pymupdf
import pytest
from PIL import Image

from extraction.pdf_text import cobertura_de_imagen, es_escaneada, texto_pagina

TEXTO = "Artículo 1. Objeto de la norma. Regula las contrataciones del Estado. " * 12


def png_bytes(ancho=300, alto=400):
    buf = io.BytesIO()
    Image.new("RGB", (ancho, alto), "white").save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def pdf_mixto(tmp_path):
    doc = pymupdf.open()
    p1 = doc.new_page()                                              # 1: texto normal, sin imágenes
    p1.insert_textbox(pymupdf.Rect(50, 50, 545, 700), TEXTO)
    p2 = doc.new_page()                                              # 2: escaneada (imagen a página completa, sin texto)
    p2.insert_image(p2.rect, stream=png_bytes(), keep_proportion=False)
    doc.new_page()                                                   # 3: en blanco (sin texto ni imagen)
    p4 = doc.new_page()                                              # 4: imagen pequeña + poco texto (un logo)
    p4.insert_image(pymupdf.Rect(10, 10, 60, 60), stream=png_bytes(50, 50))
    p4.insert_text((72, 300), "Fin.")
    p5 = doc.new_page()                                              # 5: imagen a página completa PERO con capa de texto (OCR previo)
    p5.insert_image(p5.rect, stream=png_bytes(), keep_proportion=False)
    p5.insert_textbox(pymupdf.Rect(50, 50, 545, 700), TEXTO)
    ruta = tmp_path / "mixto.pdf"
    doc.save(ruta)
    doc.close()
    return ruta


def test_clasificacion_de_paginas(pdf_mixto):
    with pymupdf.open(pdf_mixto) as pdf:
        veredictos = {n: es_escaneada(pdf[n - 1], texto_pagina(pdf[n - 1]), umbral_caracteres=100) for n in range(1, 6)}
    assert veredictos == {1: False, 2: True, 3: False, 4: False, 5: False}


def test_pagina_en_blanco_no_va_a_ocr(pdf_mixto):
    """Una página sin texto pero también sin imagen es legítimamente vacía: mandarla a OCR sería trabajo perdido."""
    with pymupdf.open(pdf_mixto) as pdf:
        pag = pdf[2]
        assert texto_pagina(pag).strip() == "" and cobertura_de_imagen(pag) == 0.0
        assert not es_escaneada(pag, texto_pagina(pag), 100)


def test_cobertura_de_imagen(pdf_mixto):
    with pymupdf.open(pdf_mixto) as pdf:
        cob = {n: cobertura_de_imagen(pdf[n - 1]) for n in range(1, 6)}
    assert cob[1] == 0.0 and cob[3] == 0.0
    assert cob[2] > 0.99 and cob[5] > 0.99
    assert 0 < cob[4] < 0.05


def test_texto_pagina_devuelve_la_capa_de_texto(pdf_mixto):
    with pymupdf.open(pdf_mixto) as pdf:
        assert "Artículo 1. Objeto" in texto_pagina(pdf[0])
        assert texto_pagina(pdf[1]).strip() == ""


def test_el_umbral_es_configurable(pdf_mixto):
    with pymupdf.open(pdf_mixto) as pdf:
        pag = pdf[4]
        assert not es_escaneada(pag, texto_pagina(pag), umbral_caracteres=100)
        assert es_escaneada(pag, texto_pagina(pag), umbral_caracteres=10**6)  # umbral absurdo: imagen grande => OCR

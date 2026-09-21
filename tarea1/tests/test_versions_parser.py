"""Parser del DS 001-2026-EF: pruebas unitarias con texto sintético y de integración con el PDF oficial."""
from pathlib import Path

import pymupdf
import pytest

from extraction import versions_parser as vp
from extraction.clean import limpiar_pagina

PDF_DS001 = Path(__file__).resolve().parents[1] / "data" / "raw" / "ds_001_2026_ef.pdf"


# ── unitarias ──

def test_items_separa_por_punto_y_coma_y_por_y_entre_articulos():
    lista = ("el numeral 15.1 del artículo 15; el artículo 16; los numerales 42.2 y 42.3 del artículo 42; "
             "el literal b) del numeral 37.3 del artículo 37; así como la Decimocuarta Disposición Complementaria Final; "
             "y los numerales 13, 30 y 67 del Anexo I “Definiciones” del Reglamento de la Ley Nº 32069, Ley General "
             "de Contrataciones Públicas, aprobado mediante el Decreto Supremo Nº 009-2025-EF")
    assert vp._items(lista) == [
        "el numeral 15.1 del artículo 15", "el artículo 16", "los numerales 42.2 y 42.3 del artículo 42",
        "el literal b) del numeral 37.3 del artículo 37", "la Decimocuarta Disposición Complementaria Final",
        "los numerales 13, 30 y 67 del Anexo I “Definiciones”",
    ]


def test_items_un_y_sin_punto_y_coma_une_dos_elementos_distintos():
    lista = "el numeral 373.2 en el artículo 373 y los numerales 5, 6, 7 y 8 de la Decimotercera Disposición Complementaria Transitoria"
    assert vp._items(lista) == ["el numeral 373.2 en el artículo 373", "los numerales 5, 6, 7 y 8 de la Decimotercera Disposición Complementaria Transitoria"]


def test_items_no_parte_listas_de_numerales_ni_literales():
    assert vp._items("los numerales 353.1, 353.5 y 353.10 del artículo 353; los literales a), b) y h) del numeral 318.1 del artículo 318") == [
        "los numerales 353.1, 353.5 y 353.10 del artículo 353", "los literales a), b) y h) del numeral 318.1 del artículo 318"]


PAGINAS_SINTETICAS = [
    "Artículo 1.- Objeto\nSe aprueba la modificación.\nArtículo 2.- Modificación de diversos artículos\n"
    "Modificar el numeral 15.1 del artículo 15; el artículo 16, en los siguientes términos:",
    "“Artículo 15. Compradores Públicos\n15.1. Texto nuevo.\n(…)”\n“Artículo 16. Certificación\nTexto nuevo.”",
    "Artículo 3.- Incorporación de numerales\nIncorporar el numeral 3.5 en el artículo 3; el numeral 373.2 en el artículo 373 y los "
    "numerales 5 y 6 de la Decimotercera Disposición Complementaria Transitoria, en los siguientes términos:\n"
    "“Artículo 3. Acrónimos\n3.5. Nuevo.”\n“Artículo 373. Otro\n373.2. Nuevo.”\nArtículo 4.- Publicación",
]


def test_analiza_texto_sintetico_completo():
    r = vp.analizar(PAGINAS_SINTETICAS)
    esperado = {(c.articulo, c.tipo, c.detalle, c.pagina_ds001) for c in r.cambios}
    assert esperado == {
        (15, "modifica", "numeral 15.1", 2), (16, "modifica", "artículo completo", 2),
        (3, "incorpora", "numeral 3.5", 3), (373, "incorpora", "numeral 373.2", 3),
    }
    assert [o["elemento"] for o in r.otras_disposiciones] == ["los numerales 5 y 6 de la Decimotercera Disposición Complementaria Transitoria"]
    assert r.sin_bloque_citado == [] and r.bloque_sin_lista == []


def test_un_articulo_enumerado_sin_texto_citado_queda_reportado():
    paginas = list(PAGINAS_SINTETICAS)
    paginas[1] = "“Artículo 15. Compradores Públicos\n15.1. Texto nuevo.”"     # falta el bloque del artículo 16
    r = vp.analizar(paginas)
    assert r.sin_bloque_citado == [16]


def test_un_bloque_citado_que_no_esta_en_la_lista_queda_reportado():
    paginas = list(PAGINAS_SINTETICAS)
    paginas[1] += "\n“Artículo 99. Sorpresa\nTexto.”"
    assert ("modifica", 99) in vp.analizar(paginas).bloque_sin_lista


# ── integración con el PDF oficial ──

@pytest.fixture(scope="module")
def resultado_real():
    if not PDF_DS001.is_file():
        pytest.skip("falta data/raw/ds_001_2026_ef.pdf (ejecuta scripts/download_pdfs.py)")
    with pymupdf.open(PDF_DS001) as pdf:
        return vp.analizar([limpiar_pagina(p.get_text(), "2474920-3").texto for p in pdf])


def test_conteos_del_decreto_real(resultado_real):
    j = vp.a_json(resultado_real, "ds_001_2026_ef", "ds_009_2025_ef")["resumen"]
    assert (j["articulos_distintos"], j["cambios_modifica"], j["cambios_incorpora"]) == (105, 96, 15)
    assert j["sin_bloque_citado"] == [] and j["bloques_citados_no_enumerados"] == []


def test_ejemplos_concretos_del_decreto_real(resultado_real):
    por = {(c.articulo, c.tipo): c for c in resultado_real.cambios}
    assert por[(15, "modifica")].detalle == "numeral 15.1" and por[(15, "modifica")].pagina_ds001 == 2
    assert por[(16, "modifica")].detalle == "artículo completo"
    assert (42, "modifica") in por and (42, "incorpora") in por          # un artículo con ambos tipos de cambio
    assert por[(373, "incorpora")].pagina_ds001 == 15                    # el caso del "y" sin punto y coma
    assert por[(186, "incorpora")].detalle == "numerales 186.7 y 186.8"


def test_todas_las_paginas_citadas_existen(resultado_real):
    assert all(c.pagina_ds001 is not None and 1 <= c.pagina_ds001 <= 16 for c in resultado_real.cambios)

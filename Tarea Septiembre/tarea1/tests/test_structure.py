"""Detección de estructura tolerante a OCR."""
import pytest

from extraction.structure import analizar_pagina

CLAVES = {"mype": ["mype", "micro y pequeña"], "seleccion": ["procedimiento de selección"]}


def niveles(texto):
    return [(e["nivel"], e["texto"]) for e in analizar_pagina(texto)["encabezados"]]


def test_capitulo_con_titulo_en_la_linea_siguiente():
    assert niveles("CAPÍTULO II\nESTANDARIZACIÓN DE REQUERIMIENTOS\nArtículo 259.") == [("capitulo", "CAPÍTULO II ESTANDARIZACIÓN DE REQUERIMIENTOS")]


@pytest.mark.parametrize("linea", ["CAPITULO Il", "CAPÍTULO III", "  CAPITULO ll"])
def test_errores_tipicos_de_ocr_en_capitulo(linea):
    r = niveles(linea)
    assert len(r) == 1 and r[0][0] == "capitulo"


def test_titulo_y_subcapitulo():
    r = niveles("TÍTULO IV\nSUBCAPÍTULO I\nDISPOSICIONES GENERALES")
    assert [n for n, _ in r] == ["titulo", "subcapitulo"]


def test_una_frase_que_menciona_titulo_o_capitulo_no_es_encabezado():
    assert niveles("Título quinto de la ley establece que\nel capítulo segundo regula lo siguiente.") == []


def test_disposiciones_y_anexos():
    r = niveles("DISPOSICIONES COMPLEMENTARIAS FINALES\nANEXO I\nDEFINICIONES")
    assert ("disposicion", "DISPOSICIONES COMPLEMENTARIAS FINALES") in r and ("anexo", "ANEXO I") in r


def test_articulos_solo_al_inicio_de_linea_y_con_o_sin_tilde():
    t = "Articulo 257. Obligatoriedad\nArtículo 258.- Interoperabilidad\nsegún lo dispuesto en el artículo 12. del reglamento\n“Artículo 300. Citado"
    assert analizar_pagina(t)["articulos"] == [257, 258, 300]


def test_palabras_clave_ignoran_tildes_y_mayusculas():
    t = "Las MYPE y la Micro y Pequeña empresa participan en el Procedimiento de Selección."
    assert analizar_pagina(t, CLAVES)["palabras_clave"] == {"mype": 2, "seleccion": 1}


def test_pagina_sin_estructura():
    r = analizar_pagina("texto corrido sin nada especial", CLAVES)
    assert r == {"encabezados": [], "articulos": [], "palabras_clave": {}}


@pytest.mark.parametrize("linea, numero", [
    ("Artículo 69, Contenido de las ofertas", 69),        # coma en vez de punto (muy frecuente en el OCR)
    ("Artículo-64. Cronograma de los procedimientos", 64),  # guion pegado
    ("Articulo 100, Condiciones generales", 100),
    ("Aríículo 12. Objeto", 12),                            # errores en la palabra
    ("“Artículo 15. Compradores Públicos", 15),
])
def test_encabezados_de_articulo_con_errores_tipicos_de_ocr(linea, numero):
    assert analizar_pagina(linea)["articulos"] == [numero]


@pytest.mark.parametrize("linea", [
    "el numeral 64.1 puede reducirse conforme a lo que señalen",
    "del articulo 69.",                       # referencia en minúscula
    "Anexo 12, Formularios",                  # otra palabra que empieza con A
    "Artículo de la ley",                     # sin número
])
def test_no_toma_referencias_ni_otras_palabras_como_encabezado(linea):
    assert analizar_pagina(linea)["articulos"] == []

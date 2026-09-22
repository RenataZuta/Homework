"""Pruebas de las reglas de limpieza, con texto REAL de El Peruano (DS 001-2026-EF) y casos de borde."""
import pytest

from extraction.clean import caracteres_utiles, limpiar_pagina, normalizar_espacios, porcentaje_alfabetico

# Texto tal como lo entrega PyMuPDF (medido en data/raw/ds_001_2026_ef.pdf)
PAG1 = ("33\nNORMAS LEGALES\nJueves 8 de enero de 2026\n El Peruano / \nECONOMÍA Y FINANZAS\nDecreto \nSupremo \n"
        "que \nmodifica \nel \nReglamento de la Ley N° 32069\nEL PRESIDENTE DE LA REPÚBLICA\nCONSIDERANDO:\n"
        "del artículo 318; el literal b) del artículo 320; el numeral \nFirmado por: Editora Peru\nFecha: 08/01/2026 07:30\n")
PAG2 = ("34\nNORMAS LEGALES\nJueves 8 de enero de 2026\n El Peruano \n/\n332.2 del artículo 332; el numeral 338.2 del artículo 338;\n"
        "el numeral 346.3 del artículo 346;\n")
PAG16 = ("48\nNORMAS LEGALES\nJueves 8 de enero de 2026\n El Peruano \n/\nDado en la Casa de Gobierno, en Lima, a los siete \n"
         "días del mes de enero del año dos mil veintiséis.\nJOSÉ ENRIQUE JERÍ ORÉ\nPresidente de la República\n"
         "DENISSE AZUCENA MIRALLES MIRALLES\nMinistra de Economía y Finanzas\n2474920-3\n"
         "Fijan índices de corrección monetaria para \nefectos de determinar el costo\nRESOLUCIÓN VICEMINISTERIAL\n"
         "2474593-1\nQue, a través del Decreto Supremo\n")


# ── R1: cabecera ──

def test_r1_cabecera_con_barra_en_la_misma_linea():
    r = limpiar_pagina(PAG1)
    assert r.pagina_impresa == 33
    assert r.cabecera_eliminada == ["33", "NORMAS LEGALES", "Jueves 8 de enero de 2026", "El Peruano /"]
    assert r.texto.startswith("ECONOMÍA Y FINANZAS")
    assert "NORMAS LEGALES" not in r.texto and "Jueves 8 de enero" not in r.texto


def test_r1_cabecera_con_barra_en_linea_aparte():
    r = limpiar_pagina(PAG2)
    assert r.pagina_impresa == 34
    assert r.texto.startswith("332.2 del artículo 332")


@pytest.mark.parametrize("primera_linea", [
    "Artículo 45. Contratos de obra",
    "“Artículo 72. Requisitos de calificación",
    "45. El plazo de ejecución contractual",
    "332",                                    # número suelto SIN firma de cabecera: es contenido, no cabecera
])
def test_r1_paginas_que_empiezan_con_contenido_legitimo_no_se_tocan(primera_linea):
    crudo = f"{primera_linea}\nTexto del cuerpo de la norma.\nNORMAS LEGALES aplicables al caso.\n"
    r = limpiar_pagina(crudo)
    assert r.cabecera_eliminada == [] and r.pagina_impresa is None
    assert r.texto.splitlines()[0] == primera_linea
    assert "NORMAS LEGALES aplicables al caso." in r.texto


def test_r1_no_borra_cabeceras_incompletas():
    crudo = "12\nNORMAS LEGALES\nTexto que sigue sin fecha ni El Peruano\n"
    r = limpiar_pagina(crudo)
    assert r.cabecera_eliminada == [] and "NORMAS LEGALES" in r.texto


def test_r1_solo_actua_al_inicio_no_en_medio_de_la_pagina():
    crudo = "Artículo 1. Objeto\nTexto\n33\nNORMAS LEGALES\nJueves 8 de enero de 2026\n El Peruano /\nmás texto\n"
    r = limpiar_pagina(crudo)
    assert r.cabecera_eliminada == [] and "NORMAS LEGALES" in r.texto


# ── R2: sello de firma ──

def test_r2_sello_de_firma_al_final():
    r = limpiar_pagina(PAG1)
    assert r.pie_eliminado == ["Firmado por: Editora Peru", "Fecha: 08/01/2026 07:30"]
    assert r.texto.endswith("el numeral")


def test_r2_una_mencion_a_fecha_en_el_cuerpo_no_se_borra():
    r = limpiar_pagina("Artículo 3.\nFecha: el plazo se cuenta desde la notificación.\nFin del artículo.")
    assert "Fecha: el plazo" in r.texto and r.pie_eliminado == []


# ── R3: fin de norma ──

def test_r3_descarta_texto_de_otras_normas_tras_el_codigo_de_cierre():
    r = limpiar_pagina(PAG16, codigo_fin_norma="2474920-3")
    assert r.lineas_fuera_de_norma > 0
    assert r.texto.endswith("Ministra de Economía y Finanzas")
    assert "Fijan índices" not in r.texto and "2474593-1" not in r.texto and "Pronied" not in r.texto
    assert "R3_fin_de_norma" in r.reglas


def test_r3_sin_codigo_configurado_no_recorta():
    assert "Fijan índices" in limpiar_pagina(PAG16).texto


def test_r3_pagina_que_no_contiene_el_codigo_queda_igual():
    r = limpiar_pagina(PAG2, codigo_fin_norma="2474920-3")
    assert r.lineas_fuera_de_norma == 0 and "R3_fin_de_norma" not in r.reglas


# ── R4: espacios ──

def test_r4_normaliza_espacios_sin_quitar_guiones_de_fin_de_linea():
    crudo = "  \nDecreto Supremo N° 009-2025-\nEF   con\xa0espacios \n\n\n\n  \nfin​ \n"
    assert normalizar_espacios(crudo) == "Decreto Supremo N° 009-2025-\nEF con espacios\n\nfin"


def test_texto_del_compendio_con_lineas_de_solo_espacios():
    crudo = "  \nArtículo 2. Finalidad de la Ley \nLa presente ley tiene \n  \n3.1. La presente ley \n"
    assert limpiar_pagina(crudo).texto == "Artículo 2. Finalidad de la Ley\nLa presente ley tiene\n\n3.1. La presente ley"


# ── métricas ──

def test_caracteres_utiles_y_porcentaje_alfabetico():
    assert caracteres_utiles("Ab 12 -- !!") == 4
    assert caracteres_utiles("   \n ") == 0
    assert porcentaje_alfabetico("abcd") == 1.0
    assert porcentaje_alfabetico("ab12") == 0.5
    assert porcentaje_alfabetico("") == 0.0

"""La limpieza aplicada a los documentos REALES no borra contenido legítimo (usa data/processed/, versionado)."""
import re
from pathlib import Path

import pytest

from extraction import store
from extraction.clean import normalizar_espacios

PROCESSED = Path(__file__).resolve().parents[1] / "data" / "processed"
PATRON_CABECERA = re.compile(
    r"^(\d{1,4}|NORMAS LEGALES|(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo) \d{1,2} de \w+ de \d{4}|El Peruano\s*/?|/)$", re.I)


def entradas(doc_id):
    e = store.listar_paginas(PROCESSED / doc_id)
    if not e:
        pytest.skip(f"falta data/processed/{doc_id} (ejecuta scripts/run_extraction.py)")
    return e


def test_la_ley_no_recibe_ninguna_regla_de_el_peruano_y_solo_cambian_los_espacios():
    for e in entradas("ley_32069"):
        assert e["limpieza"]["reglas"] == [], f"p{e['pagina']}: una regla de El Peruano se aplicó a la Ley"
        assert e["texto"] == normalizar_espacios(e["texto_crudo"]), f"p{e['pagina']}: cambió algo más que los espacios"


def test_ds001_cada_linea_eliminada_de_cabecera_es_realmente_cabecera():
    for e in entradas("ds_001_2026_ef"):
        assert e["limpieza"]["cabecera_eliminada"], f"p{e['pagina']}: no se detectó cabecera"
        for linea in e["limpieza"]["cabecera_eliminada"]:
            assert PATRON_CABECERA.match(linea), f"p{e['pagina']}: se eliminó una línea que no parece cabecera: {linea!r}"
        assert e["pagina_impresa"] == 32 + e["pagina"]           # 33..48


def test_ds001_las_paginas_que_empiezan_con_articulo_conservan_esa_linea():
    con_articulo = [e for e in entradas("ds_001_2026_ef") if re.match(r"[“\"]?Art[ií]culo", e["texto"])]
    assert len(con_articulo) >= 4                                # 4, 9, 13, 15 empiezan con “Artículo tras la cabecera
    for e in con_articulo:
        primera_cruda = next(l for l in e["texto_crudo"].split("\n") if re.match(r"[“\"]?Art[ií]culo", l.strip()))
        assert e["texto"].split("\n")[0].split()[0] == primera_cruda.split()[0]


def test_ds001_sello_de_firma_solo_en_la_pagina_1_y_fin_de_norma_solo_en_la_16():
    por = {e["pagina"]: e["limpieza"] for e in entradas("ds_001_2026_ef")}
    assert [p for p, l in por.items() if l["pie_eliminado"]] == [1]
    assert [p for p, l in por.items() if l["lineas_fuera_de_norma"]] == [16]
    assert por[16]["lineas_fuera_de_norma"] > 100


def test_ds001_el_texto_limpio_no_contiene_texto_de_otras_normas():
    ultima = entradas("ds_001_2026_ef")[-1]
    for ajeno in ("Fijan índices", "corrección monetaria", "Pronied", "2474593-1"):
        assert ajeno not in ultima["texto"], f"texto ajeno en la p. 16: {ajeno}"
    assert "Ministra de Economía y Finanzas" in ultima["texto"]


def test_lo_eliminado_sigue_disponible_en_el_texto_crudo():
    for e in entradas("ds_001_2026_ef"):
        for linea in e["limpieza"]["cabecera_eliminada"] + e["limpieza"]["pie_eliminado"]:
            assert linea.split()[0] in e["texto_crudo"]


def test_ninguna_pagina_quedo_vacia_por_la_limpieza():
    for doc in ("ley_32069", "ds_001_2026_ef"):
        for e in entradas(doc):
            assert e["caracteres"] > 150, f"{doc} p{e['pagina']} quedó con {e['caracteres']} caracteres"

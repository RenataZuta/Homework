"""Selección del subconjunto de OCR con un mapa sintético."""
import pytest

from extraction.subset import Decision, anclas_monotonas, articulo_a_pagina, prioridad, seleccionar

PESOS = {"modificados": 10.0, "mype": 1.0}


def pagina(tipo="texto", cap=None, arts=(), claves=None, car=6000):
    return {"tipo": tipo, "caracteres": car, "articulos": list(arts), "palabras_clave": claves or {},
            "encabezados": [{"nivel": "capitulo", "texto": cap}] if cap else []}


# ── anclas y artículo→página ──

def test_anclas_descartan_lecturas_erroneas_de_ocr():
    # el artículo 479 leído en la página 3 y el 1 leído en la 20 son ruido
    pares = [(1, 3), (5, 4), (10, 5), (479, 3), (18, 6), (2, 20), (25, 7)]
    assert anclas_monotonas(pares) == [(1, 3), (5, 4), (10, 5), (18, 6), (25, 7)]


def test_articulo_a_pagina_interpola_entre_anclas():
    mapa = {3: pagina(arts=[1]), 4: pagina(arts=[5]), 5: pagina(arts=[9]), 7: pagina(arts=[17])}
    a = articulo_a_pagina(mapa, 20)
    assert (a[1], a[5], a[9], a[17]) == (3, 4, 5, 7)     # detectados
    assert a[13] == 6                                    # interpolado entre (9, p5) y (17, p7)
    assert a[19] == 7                                    # tras la última ancla: se queda en su página


# ── selección ──

def mapa_sintetico():
    m = {1: pagina("escasa_lectura", car=100), 2: pagina("escasa_lectura", car=200)}
    m[3] = pagina(cap="CAPÍTULO I", arts=[1])
    m[4] = pagina(arts=[5], claves={"mype": 8})
    m[5] = pagina(arts=[9])
    m[6] = pagina(cap="CAPÍTULO II", arts=[13], claves={"mype": 1})
    m[7] = pagina(arts=[17])
    m[8] = pagina("escasa_lectura", car=300)
    return m


def test_seleccion_incluye_encabezados_y_modificados_y_excluye_formularios():
    ds = {d.pagina: d for d in seleccionar(mapa_sintetico(), [17], max_articulo=20, objetivo=4, minimo=4, pesos=PESOS)}
    assert [p for p, d in ds.items() if d.incluida] == [3, 4, 6, 7]     # 2 encabezados + p7 (art. 17 modificado) + p4 (MYPE)
    assert not ds[5].incluida and any("menor prioridad" in m for m in ds[5].motivos)
    assert all(not ds[p].incluida and "escasa_lectura" in ds[p].motivos[0] for p in (1, 2, 8))
    assert ds[7].modificados == [17] and any("17" in m for m in ds[7].motivos)


def test_las_paginas_obligatorias_van_primero_en_la_prioridad():
    ds = seleccionar(mapa_sintetico(), [17], max_articulo=20, objetivo=4, minimo=4, pesos=PESOS)
    assert prioridad(ds) == [3, 6]


def test_falla_si_las_obligatorias_superan_el_objetivo():
    with pytest.raises(ValueError, match="obligatorias"):
        seleccionar(mapa_sintetico(), [], max_articulo=20, objetivo=1, minimo=1, pesos=PESOS)


def test_el_minimo_manda_sobre_un_objetivo_menor():
    ds = seleccionar(mapa_sintetico(), [], max_articulo=20, objetivo=2, minimo=5, pesos=PESOS)
    assert sum(d.incluida for d in ds) == 5


def test_desempate_por_numero_de_pagina():
    m = {3: pagina(cap="CAPÍTULO I", arts=[1]), 4: pagina(arts=[5]), 5: pagina(arts=[9])}
    ds = {d.pagina: d for d in seleccionar(m, [], max_articulo=10, objetivo=2, minimo=2, pesos=PESOS)}
    assert ds[4].incluida and not ds[5].incluida


def test_devuelve_una_decision_por_pagina_del_mapa():
    m = mapa_sintetico()
    ds = seleccionar(m, [], max_articulo=20, objetivo=4, minimo=4, pesos=PESOS)
    assert [d.pagina for d in ds] == sorted(m) and all(isinstance(d, Decision) for d in ds)

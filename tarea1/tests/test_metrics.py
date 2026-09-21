"""Métricas de recuperación con recuperadores guiados (sin modelos)."""
from types import SimpleNamespace

import pytest

from evaluation.eval_set import Pregunta
from evaluation.metrics import evaluar_recuperacion

L, D9, D1 = "ley_32069", "ds_009_2025_ef", "ds_001_2026_ef"


def q(id_, tipo="in_domain", estilo="coloquial", mod=False, esperados=None):
    return Pregunta(id=id_, pregunta=f"pregunta {id_}?", tipo=tipo, estilo=estilo, modificada_2026=mod, esperados=esperados or {}, notas="x")


def r(doc, pag, sim=0.8):
    return SimpleNamespace(documento=doc, pagina=pag, similitud=sim)


def guiado(tabla):
    return lambda texto, k: tabla[texto][:k]


def test_recall_cuenta_el_acierto_en_la_posicion_correcta():
    qs = [q("a", esperados={L: [10]}), q("b", esperados={L: [20]}), q("c", esperados={L: [30]}), q("d", esperados={L: [40]})]
    tabla = {"pregunta a?": [r(L, 10), r(L, 1)],                        # rango 1
             "pregunta b?": [r(L, 1), r(L, 2), r(L, 20)],               # rango 3
             "pregunta c?": [r(L, 1), r(L, 2), r(L, 3), r(L, 4), r(L, 30)],   # rango 5
             "pregunta d?": [r(L, 1), r(L, 2), r(L, 3), r(L, 4), r(L, 5)]}    # no aparece
    ev = evaluar_recuperacion(qs, guiado(tabla), (1, 3, 5))
    assert [ev.recall(k) for k in (1, 3, 5)] == [0.25, 0.5, 0.75]
    assert ev.mrr() == pytest.approx((1 + 1 / 3 + 1 / 5 + 0) / 4)
    assert [x.id for x in ev.fallos(5)] == ["d"]


def test_acierta_por_documento_y_pagina_no_solo_por_pagina():
    ev = evaluar_recuperacion([q("a", esperados={L: [10]})], guiado({"pregunta a?": [r(D9, 10), r(L, 11), r(L, 10)]}))
    assert ev.por_pregunta[0].rango_acierto == 3


def test_varias_paginas_y_varios_documentos_esperados_cualquiera_vale():
    qq = q("a", esperados={D1: [8, 9], D9: [47]})
    for recuperado, rango in (([r(D1, 9)], 1), ([r(D9, 47)], 1), ([r(D1, 7), r(D9, 47)], 2)):
        assert evaluar_recuperacion([qq], guiado({"pregunta a?": recuperado})).por_pregunta[0].rango_acierto == rango


def test_recall_de_la_modificatoria_exige_el_fragmento_del_ds_001():
    qq = q("m", mod=True, esperados={D1: [4], D9: [18]})
    solo_original = evaluar_recuperacion([qq], guiado({"pregunta m?": [r(D9, 18)]}))
    assert solo_original.recall(1) == 1.0 and solo_original.recall_modificatoria(1) == 0.0       # acierta, pero desactualizado
    con_modificatoria = evaluar_recuperacion([qq], guiado({"pregunta m?": [r(D9, 18), r(D1, 4)]}))
    assert con_modificatoria.recall_modificatoria(1) == 0.0 and con_modificatoria.recall_modificatoria(3) == 1.0


def test_las_preguntas_fuera_de_dominio_no_entran_en_el_recall_pero_guardan_su_similitud():
    qs = [q("a", esperados={L: [1]}), q("o", tipo="out_of_domain")]
    ev = evaluar_recuperacion(qs, guiado({"pregunta a?": [r(L, 1)], "pregunta o?": [r(L, 5, 0.77)]}))
    assert ev.recall(1) == 1.0
    assert [x.mejor_similitud for x in ev.por_pregunta if x.tipo == "out_of_domain"] == [0.77]


def test_recall_por_estilo():
    qs = [q("a", estilo="coloquial", esperados={L: [1]}), q("b", estilo="juridico", esperados={L: [2]})]
    ev = evaluar_recuperacion(qs, guiado({"pregunta a?": [r(L, 1)], "pregunta b?": [r(L, 9)]}))
    s = ev.resumen()
    assert s["recall@1_coloquial"] == 1.0 and s["recall@1_juridico"] == 0.0 and s["recall@1"] == 0.5


def test_recuperador_vacio_no_rompe():
    ev = evaluar_recuperacion([q("a", esperados={L: [1]})], guiado({"pregunta a?": []}))
    assert ev.recall(5) == 0.0 and ev.por_pregunta[0].mejor_similitud == 0.0

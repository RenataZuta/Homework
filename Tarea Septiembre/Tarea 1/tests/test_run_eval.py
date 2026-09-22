"""run_eval: métricas de recuperación, abstención correcta/incorrecta y código de salida para el CI."""
from types import SimpleNamespace

import pytest

from evaluation.eval_set import Pregunta
from evaluation.run_eval import codigo_de_salida, evaluar, tasa

L = "ley_32069"


def q(id_, tipo="in_domain", pag=1, mod=False, estilo="coloquial"):
    return Pregunta(id=id_, pregunta=id_, tipo=tipo, estilo=estilo, modificada_2026=mod, esperados={L: [pag]} if tipo == "in_domain" else {}, notas="x")


def rec(pag, sim, doc=L):
    return SimpleNamespace(documento=doc, pagina=pag, similitud=sim)


TABLA = {"a": [rec(1, 0.90)],                 # in_domain, acierta, sim alta
         "b": [rec(9, 0.88), rec(2, 0.87)],   # in_domain, acierta en rango 2
         "c": [rec(7, 0.83)],                 # in_domain, falla y sim baja (abstención incorrecta)
         "o1": [rec(5, 0.80)],                # fuera, sim baja (abstención correcta)
         "o2": [rec(5, 0.89)]}                # fuera, sim alta (respuesta indebida)
PREGUNTAS = [q("a", pag=1), q("b", pag=2), q("c", pag=3), q("o1", "out_of_domain"), q("o2", "out_of_domain")]


def evaluar_tabla(umbral=0.85):
    return evaluar(PREGUNTAS, lambda t, k: TABLA[t][:k], (1, 3, 5), umbral)


def test_recall_y_conteos_de_abstencion():
    r = evaluar_tabla()
    assert r["recuperacion"]["recall@1"] == pytest.approx(1 / 3) and r["recuperacion"]["recall@3"] == pytest.approx(2 / 3)
    ab = r["abstencion"]
    assert (ab["in_domain_respondidas"], ab["abstenciones_incorrectas"], ab["abstenciones_correctas"], ab["respuestas_indebidas"]) == (2, 1, 1, 1)
    assert ab["tasa_abstencion_incorrecta"] == 0.3333 and ab["tasa_abstencion_correcta"] == 0.5 and ab["tasa_abstencion_global"] == 0.4


def test_el_umbral_cambia_la_abstencion_pero_no_el_recall():
    bajo, alto = evaluar_tabla(0.0), evaluar_tabla(0.99)
    assert bajo["recuperacion"] == alto["recuperacion"]
    assert bajo["abstencion"]["tasa_abstencion_global"] == 0.0 and alto["abstencion"]["tasa_abstencion_global"] == 1.0


def test_misma_regla_que_el_motor_se_abstiene_si_es_menor_no_si_es_igual():
    assert evaluar_tabla(0.83)["abstencion"]["abstenciones_incorrectas"] == 0          # sim 0.83 == umbral: responde
    assert evaluar_tabla(0.8301)["abstencion"]["abstenciones_incorrectas"] == 1


def test_detalle_por_pregunta():
    d = {x["id"]: x for x in evaluar_tabla()["por_pregunta"]}
    assert d["b"]["rango_acierto"] == 2 and d["c"]["rango_acierto"] is None and d["o2"]["se_abstiene"] is False and d["o1"]["se_abstiene"] is True
    assert d["a"]["primero"] == "ley_32069 p.1"


def test_los_conteos_sin_preguntas_no_dividen_por_cero():
    r = evaluar([q("a")], lambda t, k: [rec(1, 0.9)], (1, 3), 0.5)
    assert r["abstencion"]["tasa_abstencion_correcta"] is None and r["abstencion"]["out_of_domain"] == 0
    assert tasa(1, 0) is None


# ── código de salida para el CI ──

def test_falla_si_el_recall_3_es_menor_que_el_minimo():
    r = evaluar_tabla()
    codigo, msg = codigo_de_salida(r, minimo=0.9, codigo_fallo=1)
    assert codigo == 1 and "FALLA" in msg and "0.667" in msg and "0.9" in msg


def test_pasa_si_el_recall_3_alcanza_el_minimo_incluso_igual():
    r = evaluar_tabla()
    assert codigo_de_salida(r, minimo=0.6, codigo_fallo=1)[0] == 0
    assert codigo_de_salida(r, minimo=r["recuperacion"]["recall@3"], codigo_fallo=1)[0] == 0


def test_el_codigo_de_fallo_es_configurable():
    assert codigo_de_salida(evaluar_tabla(), minimo=1.0, codigo_fallo=7)[0] == 7


def test_sin_preguntas_del_dominio_falla_en_vez_de_pasar_en_silencio():
    r = evaluar([q("o", "out_of_domain")], lambda t, k: [rec(1, 0.5)], (1, 3, 5), 0.5)
    assert codigo_de_salida(r, minimo=0.0, codigo_fallo=1)[0] == 1

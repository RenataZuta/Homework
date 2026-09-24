"""Pruebas de evaluation.metrics_radar: Recall@k y abstención, con datos sintéticos (no llaman al índice real)."""
from __future__ import annotations

from evaluation.metrics_radar import Evaluacion, ResultadoPregunta, evaluar_abstencion


def _ev(filas: list[ResultadoPregunta], ks=(1, 3, 5)) -> Evaluacion:
    return Evaluacion(ks=ks, por_pregunta=filas)


def test_recall_at_1_perfecto():
    filas = [ResultadoPregunta("q1", "in_domain", "directa", rango_acierto=1, mejor_similitud=0.9),
             ResultadoPregunta("q2", "in_domain", "directa", rango_acierto=1, mejor_similitud=0.8)]
    assert _ev(filas).recall(1) == 1.0


def test_recall_ignora_out_of_domain():
    filas = [ResultadoPregunta("q1", "in_domain", "directa", rango_acierto=1, mejor_similitud=0.9),
             ResultadoPregunta("o1", "out_of_domain", "directa", rango_acierto=None, mejor_similitud=0.5)]
    assert _ev(filas).recall(1) == 1.0          # 1/1 in_domain, la out_of_domain no cuenta


def test_recall_none_sin_preguntas_in_domain():
    filas = [ResultadoPregunta("o1", "out_of_domain", "directa", mejor_similitud=0.5)]
    assert _ev(filas).recall(1) is None


def test_recall_at_3_cuenta_aciertos_tardios():
    filas = [ResultadoPregunta("q1", "in_domain", "directa", rango_acierto=3, mejor_similitud=0.7)]
    assert _ev(filas).recall(1) == 0.0
    assert _ev(filas).recall(3) == 1.0


def test_recall_por_estilo():
    filas = [ResultadoPregunta("q1", "in_domain", "coloquial", rango_acierto=1, mejor_similitud=0.9),
             ResultadoPregunta("q2", "in_domain", "directa", rango_acierto=None, mejor_similitud=0.6)]
    r = _ev(filas).resumen()
    assert r["recall@1_coloquial"] == 1.0
    assert r["recall@1_directa"] == 0.0


def test_mrr():
    filas = [ResultadoPregunta("q1", "in_domain", "directa", rango_acierto=1), ResultadoPregunta("q2", "in_domain", "directa", rango_acierto=2)]
    assert abs(_ev(filas).mrr() - (1 + 0.5) / 2) < 1e-9


def test_fallos_devuelve_solo_los_que_no_acertaron_en_k():
    filas = [ResultadoPregunta("q1", "in_domain", "directa", rango_acierto=1), ResultadoPregunta("q2", "in_domain", "directa", rango_acierto=None)]
    fallos = _ev(filas).fallos(1)
    assert [f.id for f in fallos] == ["q2"]


def test_evaluar_abstencion_umbral_alto_abstiene_todo():
    filas = [ResultadoPregunta("q1", "in_domain", "directa", mejor_similitud=0.5), ResultadoPregunta("o1", "out_of_domain", "directa", mejor_similitud=0.4)]
    r = evaluar_abstencion(_ev(filas), umbral=0.9)
    assert r.respondidas_correctas == 0
    assert r.abstenciones_incorrectas == 1        # la in_domain se perdió
    assert r.abstenciones_correctas == 1           # la out_of_domain se rechazó bien
    assert r.indebidas == 0


def test_evaluar_abstencion_umbral_bajo_responde_todo():
    filas = [ResultadoPregunta("q1", "in_domain", "directa", mejor_similitud=0.5), ResultadoPregunta("o1", "out_of_domain", "directa", mejor_similitud=0.4)]
    r = evaluar_abstencion(_ev(filas), umbral=0.1)
    assert r.respondidas_correctas == 1
    assert r.indebidas == 1            # la out_of_domain se respondió indebidamente

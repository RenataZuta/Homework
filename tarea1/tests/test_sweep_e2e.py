"""Calibración del umbral con resultados de punta a punta: la compuerta solo ahorra llamadas cuando el LLM ya rechaza lo ajeno."""
import csv

import pytest

from evaluation.sweep_threshold import Punto, barrido
from evaluation.sweep_threshold_e2e import elegir_conservador, puntos_desde_csv

COLS = ["id", "tipo", "desenlace", "cita_correcta", "mejor_similitud"]


def escribir(ruta, filas):
    with ruta.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        w.writerows(filas)


def fila(id_, tipo, desenlace, cita, sim):
    return dict(id=id_, tipo=tipo, desenlace=desenlace, cita_correcta=cita, mejor_similitud=sim)


def test_una_pregunta_que_el_llm_no_respondio_nunca_cuenta_como_respondida(tmp_path):
    r = tmp_path / "e2e.csv"
    escribir(r, [fila("q1", "in_domain", "respondida", "True", 0.9), fila("q2", "in_domain", "abstuvo_llm", "False", 0.95),
                 fila("o1", "out_of_domain", "abstuvo_llm", "", 0.9), fila("o2", "out_of_domain", "respondida", "", 0.88)])
    p = puntos_desde_csv(r)
    assert [(x.tipo, x.similitud, x.acierto) for x in p] == [("in_domain", 0.9, True), ("in_domain", -1.0, False), ("out_of_domain", -1.0, False), ("out_of_domain", 0.88, False)]
    filas = barrido(p, 0.0, 1.0, 0.01, 0.5)
    bajo = next(f for f in filas if f["umbral"] == 0.5)
    assert (bajo["correctas"], bajo["abstenciones_incorrectas"], bajo["abstenciones_correctas"], bajo["indebidas"]) == (1, 1, 1, 1)


@pytest.mark.parametrize("desenlace", ["abstuvo_umbral", "no_ejecutada", "error"])
def test_un_csv_donde_algunas_preguntas_no_llegaron_al_llm_no_sirve_para_calibrar(tmp_path, desenlace):
    r = tmp_path / "e2e.csv"
    escribir(r, [fila("q1", "in_domain", "respondida", "True", 0.9), fila("q2", "in_domain", desenlace, "False", 0.5)])
    with pytest.raises(ValueError, match="umbral 0"):
        puntos_desde_csv(r)


def test_sin_el_csv_el_mensaje_dice_que_comando_ejecutar(tmp_path):
    with pytest.raises(FileNotFoundError, match="eval_end_to_end"):
        puntos_desde_csv(tmp_path / "no.csv")


def test_se_elige_el_tope_de_la_meseta_menos_el_margen_no_el_centro():
    # correcta con sim 0.84: subir el umbral por encima la pierde -> F-β cae; por debajo la meseta es plana (el LLM ya rechaza lo ajeno)
    puntos = [Punto("in_domain", 0.84, True), Punto("in_domain", 0.90, True), Punto("out_of_domain", -1.0, False), Punto("out_of_domain", -1.0, False)]
    filas = barrido(puntos, 0.0, 1.0, 0.005, 0.5)
    elegido, tope, maximo = elegir_conservador(filas, 0.005, 0.005)
    assert tope == pytest.approx(0.84) and elegido == pytest.approx(0.835) and maximo == max(f["fbeta"] for f in filas)
    assert elegido > 0.5                                                          # el centro de la meseta habría sido ~0.42


def test_con_margen_cero_el_elegido_es_el_borde_y_nunca_negativo():
    puntos = [Punto("in_domain", 0.0, True)]
    elegido, tope, _ = elegir_conservador(barrido(puntos, 0.0, 1.0, 0.005, 0.5), 0.05, 0.005)
    assert elegido == 0.0 and tope == 0.0
    puntos2 = [Punto("in_domain", 0.84, True)]
    assert elegir_conservador(barrido(puntos2, 0.0, 1.0, 0.005, 0.5), 0.0, 0.005)[0] == pytest.approx(0.84)

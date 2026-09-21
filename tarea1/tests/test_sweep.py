"""Barrido de umbral: los cinco conteos, el criterio F-beta y la elección del centro de la meseta."""
import pytest

matplotlib = pytest.importorskip("matplotlib")

from evaluation.sweep_threshold import Punto, barrido, elegir, fbeta, grafico, umbrales

# 3 preguntas del dominio (2 con acierto, 1 sin) y 2 fuera de dominio
PUNTOS = [Punto("in_domain", 0.90, True), Punto("in_domain", 0.86, True), Punto("in_domain", 0.84, False),
          Punto("out_of_domain", 0.83, False), Punto("out_of_domain", 0.80, False)]


def fila(filas, t):
    return next(f for f in filas if abs(f["umbral"] - t) < 1e-9)


def test_los_umbrales_incluyen_ambos_extremos_y_no_acumulan_error_de_punto_flotante():
    u = umbrales(0.0, 1.0, 0.005)
    assert u[0] == 0.0 and u[-1] == 1.0 and len(u) == 201 and u[3] == 0.015


def test_conteos_con_umbral_muy_bajo_todo_se_responde():
    f = fila(barrido(PUNTOS, 0.0, 1.0, 0.01, 0.5), 0.0)
    assert (f["correctas"], f["erroneas"], f["indebidas"], f["abstenciones_correctas"], f["abstenciones_incorrectas"]) == (2, 1, 2, 0, 0)


def test_conteos_con_umbral_muy_alto_todo_se_abstiene():
    f = fila(barrido(PUNTOS, 0.0, 1.0, 0.01, 0.5), 0.95)
    assert (f["correctas"], f["erroneas"], f["indebidas"], f["abstenciones_correctas"], f["abstenciones_incorrectas"]) == (0, 0, 0, 2, 3)
    assert f["precision"] is None and f["fbeta"] == 0.0


def test_conteos_en_un_umbral_intermedio():
    f = fila(barrido(PUNTOS, 0.0, 1.0, 0.01, 0.5), 0.85)          # responde 0.90 y 0.86; se abstiene de 0.84, 0.83 y 0.80
    assert (f["correctas"], f["erroneas"], f["indebidas"], f["abstenciones_correctas"], f["abstenciones_incorrectas"]) == (2, 0, 0, 2, 1)
    assert f["precision"] == 1.0 and f["cobertura"] == pytest.approx(2 / 3, abs=1e-3)


def test_el_umbral_es_inclusivo_una_similitud_igual_al_umbral_se_responde():
    f = fila(barrido([Punto("in_domain", 0.5, True)], 0.0, 1.0, 0.1, 0.5), 0.5)
    assert f["correctas"] == 1


def test_fbeta_con_beta_menor_que_1_prefiere_la_precision():
    solo_precision = fbeta(1.0, 0.5, 0.5)           # precisa pero poco cobertura
    solo_cobertura = fbeta(0.5, 1.0, 0.5)           # cobertura total pero imprecisa
    assert solo_precision > solo_cobertura
    assert fbeta(1.0, 0.5, 2.0) < fbeta(0.5, 1.0, 2.0)            # con beta > 1 sería al revés
    assert fbeta(None, 0.0, 0.5) == 0.0 and fbeta(0.0, 0.0, 0.5) == 0.0


def test_se_elige_el_centro_de_la_meseta_de_maximo():
    filas = barrido(PUNTOS, 0.80, 0.95, 0.01, 0.5)
    elegido, meseta = elegir(filas)
    assert meseta == sorted(meseta) and meseta[0] <= elegido <= meseta[-1]
    assert fila(filas, elegido)["fbeta"] == max(f["fbeta"] for f in filas)
    assert 0.85 <= elegido <= 0.86                                    # con estos puntos, entre "0.84 fuera" y "0.86 dentro"


def test_responder_mal_pesa_mas_que_no_responder():
    """Un umbral que responde a costa de una respuesta indebida no puede ganar a otro que se abstiene de una respuesta correcta."""
    filas = barrido(PUNTOS, 0.75, 0.95, 0.01, 0.5)
    e, _ = elegir(filas)
    assert fila(filas, e)["indebidas"] == 0


def test_el_grafico_se_genera_en_ambos_temas(tmp_path):
    filas = barrido(PUNTOS, 0.0, 1.0, 0.01, 0.5)
    for tema in ("claro", "oscuro"):
        ruta = tmp_path / f"{tema}.png"
        grafico(filas, 0.85, ruta, tema, 0.75, 0.95)
        assert ruta.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and ruta.stat().st_size > 5000

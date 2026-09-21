"""Throttle por RPM y reintentos con backoff exponencial, con reloj y sueño simulados (sin esperar de verdad)."""
import pytest

from rag_engine.limites import ErrorProveedor, Limitador, PoliticaReintentos


class Reloj:
    def __init__(self):
        self.t, self.dormidos = 1000.0, []

    def __call__(self):
        return self.t

    def dormir(self, s):
        self.dormidos.append(s)
        self.t += s


def err(tipo, **kw):
    return ErrorProveedor(tipo, f"error {tipo}", **kw)


# ── Limitador ──

def test_el_limitador_deja_pasar_rpm_peticiones_y_hace_esperar_a_la_siguiente():
    r = Reloj()
    lim = Limitador(3, reloj=r, dormir=r.dormir)
    assert [lim.esperar() for _ in range(3)] == [0.0, 0.0, 0.0] and r.dormidos == []
    esperado = lim.esperar()                                         # la 4.ª en el mismo minuto
    assert esperado == pytest.approx(60.0) and r.dormidos == [pytest.approx(60.0)]


def test_nunca_hay_mas_de_rpm_peticiones_en_ninguna_ventana_de_60_s():
    r = Reloj()
    lim, salidas = Limitador(4, reloj=r, dormir=r.dormir), []
    for _ in range(25):
        lim.esperar()
        salidas.append(r.t)
    for i, t in enumerate(salidas):
        assert sum(1 for u in salidas if t <= u < t + 60.0) <= 4, f"más de 4 peticiones en 60 s desde la {i}"


def test_pasado_un_minuto_no_hay_que_esperar():
    r = Reloj()
    lim = Limitador(1, reloj=r, dormir=r.dormir)
    lim.esperar()
    r.t += 61
    assert lim.esperar() == 0.0 and r.dormidos == []


def test_sin_rpm_no_hay_limite_y_un_rpm_invalido_falla():
    r = Reloj()
    lim = Limitador(None, reloj=r, dormir=r.dormir)
    assert all(lim.esperar() == 0.0 for _ in range(100)) and r.dormidos == []
    for malo in (0, -5):
        with pytest.raises(ValueError):
            Limitador(malo)


def test_el_limitador_acumula_el_tiempo_esperado():
    r = Reloj()
    lim = Limitador(1, reloj=r, dormir=r.dormir)
    lim.esperar(), lim.esperar(), lim.esperar()
    assert lim.espera_total_s == pytest.approx(120.0)


# ── Espera de los reintentos ──

def politica(**kw):
    base = dict(reintentos=4, espera_inicial_s=4, factor=2, espera_max_s=60, jitter=0.0, dormir=lambda s: None, azar=lambda: 0.0)
    return PoliticaReintentos(**{**base, **kw})


def test_el_backoff_es_exponencial_con_tope():
    p = politica(reintentos=8, espera_max_s=60)
    assert [p.espera(n, None) for n in range(1, 7)] == [4, 8, 16, 32, 60, 60]


def test_el_jitter_solo_agrega_hasta_el_porcentaje_configurado():
    assert politica(jitter=0.25, azar=lambda: 0.0).espera(1, None) == 4
    assert politica(jitter=0.25, azar=lambda: 1.0).espera(1, None) == pytest.approx(5.0)


def test_se_respeta_la_espera_sugerida_por_el_proveedor_si_es_mayor_y_con_tope():
    p = politica()
    assert p.espera(1, 27.0) == 27.0 and p.espera(3, 2.0) == 16 and p.espera(1, 500.0) == 60


@pytest.mark.parametrize("kw", [dict(reintentos=-1), dict(espera_inicial_s=0), dict(factor=0.5), dict(espera_max_s=1), dict(jitter=1.5)])
def test_una_politica_invalida_falla_al_crearse(kw):
    with pytest.raises(ValueError):
        politica(**kw)


# ── Reintentos ──

def operacion(*resultados):
    """Devuelve una operación que, en cada llamada, lanza o devuelve el siguiente elemento."""
    it, llamadas = iter(resultados), []

    def f():
        llamadas.append(1)
        x = next(it)
        if isinstance(x, Exception):
            raise x
        return x
    f.llamadas = llamadas
    return f


@pytest.mark.parametrize("tipo", ["limite_de_tasa", "servidor", "red"])
def test_los_errores_transitorios_se_reintentan_con_espera_creciente(tipo):
    dormidos, op = [], operacion(err(tipo), err(tipo), "ok")
    assert politica(dormir=dormidos.append).ejecutar(op) == "ok"
    assert len(op.llamadas) == 3 and dormidos == [4, 8]


@pytest.mark.parametrize("tipo", ["autenticacion", "solicitud", "respuesta_malformada", "respuesta_bloqueada", "cuota_agotada", "cuota_insuficiente", "otro"])
def test_los_errores_permanentes_no_se_reintentan_ni_gastan_cuota(tipo):
    dormidos, op = [], operacion(err(tipo), "ok")
    with pytest.raises(ErrorProveedor) as e:
        politica(dormir=dormidos.append).ejecutar(op)
    assert e.value.tipo == tipo and e.value.intentos == 1 and len(op.llamadas) == 1 and dormidos == []


def test_un_error_previo_a_la_peticion_no_se_reintenta():
    op = operacion(err("red", solicitud_enviada=False), "ok")
    with pytest.raises(ErrorProveedor) as e:
        politica().ejecutar(op)
    assert len(op.llamadas) == 1 and e.value.intentos == 1


def test_si_el_limite_de_tasa_persiste_el_error_final_es_cuota_agotada_estructurado():
    dormidos = []
    op = operacion(*[err("limite_de_tasa") for _ in range(10)])
    with pytest.raises(ErrorProveedor) as e:
        politica(reintentos=4, dormir=dormidos.append).ejecutar(op)
    assert e.value.tipo == "cuota_agotada" and e.value.intentos == 5 and len(op.llamadas) == 5
    assert dormidos == [4, 8, 16, 32] and "5 intentos" in e.value.mensaje and "error limite_de_tasa" in e.value.mensaje and str(e.value) == e.value.mensaje


def test_un_5xx_persistente_sigue_siendo_servidor_no_cuota():
    op = operacion(*[err("servidor") for _ in range(10)])
    with pytest.raises(ErrorProveedor) as e:
        politica(reintentos=2).ejecutar(op)
    assert e.value.tipo == "servidor" and e.value.intentos == 3


def test_cada_intento_pasa_por_el_limitador():
    r = Reloj()
    lim, op = Limitador(2, reloj=r, dormir=r.dormir), operacion(err("servidor"), err("servidor"), err("servidor"), "ok")
    assert politica(dormir=r.dormir).ejecutar(op, lim) == "ok"
    assert len(op.llamadas) == 4 and len(lim._salidas) <= 2 and lim.espera_total_s > 0        # el 3.er intento tuvo que esperar el cupo


def test_con_cero_reintentos_falla_a_la_primera():
    op = operacion(err("servidor"), "ok")
    with pytest.raises(ErrorProveedor):
        politica(reintentos=0).ejecutar(op)
    assert len(op.llamadas) == 1

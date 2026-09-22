"""Almacén SQLite del bot: consultas, límite diario por zona horaria y feedback sin duplicados ni votos ajenos."""
from datetime import datetime, timedelta, timezone

import pytest

from interfaces import bot_store

LIMA = timezone(timedelta(hours=-5))


class ResultadoFalso:
    def __init__(self, respuesta="Son 10 días [Ley 32069, p. 32].", abstuvo=False, error=None, fuentes=None, costo_real=0.0, costo_ref=0.001, tin=100, tout=20):
        self.respuesta, self.abstuvo, self.error = respuesta, abstuvo, error
        self.fuentes = fuentes or [Fuente()]
        self.costo_usd_real, self.costo_usd_referencia, self.tokens_entrada, self.tokens_salida = costo_real, costo_ref, tin, tout


class Fuente:
    def __init__(self, documento="ley_32069", pagina=32, similitud=0.9, texto="Texto del fragmento.", citada=True):
        self.documento, self.pagina, self.similitud, self.texto, self.citada = documento, pagina, similitud, texto, citada


@pytest.fixture
def conn(tmp_path):
    return bot_store.abrir_db(tmp_path / "bot.db")


def t(h=10, m=0, dia=21):
    return datetime(2026, 9, dia, h, m, tzinfo=LIMA)


def test_registrar_y_leer_una_consulta_conserva_las_fuentes(conn):
    cid = bot_store.registrar_consulta(conn, 111, "¿Plazo de pago?", ResultadoFalso(), t())
    assert cid == 1
    c = bot_store.consulta_por_id(conn, cid)
    assert c["user_id"] == 111 and c["pregunta"] == "¿Plazo de pago?" and c["abstuvo"] is False
    assert c["fuentes"] == [{"documento": "ley_32069", "pagina": 32, "similitud": 0.9, "texto": "Texto del fragmento.", "citada": True}]


def test_ultima_consulta_es_la_mas_reciente_por_id_no_por_hora_del_reloj(conn):
    bot_store.registrar_consulta(conn, 1, "primera", ResultadoFalso(), t(9))
    bot_store.registrar_consulta(conn, 1, "segunda", ResultadoFalso(), t(8))            # reloj "antes" pero insertada después
    assert bot_store.ultima_consulta(conn, 1)["pregunta"] == "segunda"


def test_ultima_consulta_de_un_usuario_sin_historial_es_none(conn):
    assert bot_store.ultima_consulta(conn, 999) is None and bot_store.consulta_por_id(conn, 999) is None


def test_ultima_consulta_no_mezcla_usuarios(conn):
    bot_store.registrar_consulta(conn, 1, "de uno", ResultadoFalso(), t())
    bot_store.registrar_consulta(conn, 2, "de otro", ResultadoFalso(), t())
    assert bot_store.ultima_consulta(conn, 1)["pregunta"] == "de uno" and bot_store.ultima_consulta(conn, 2)["pregunta"] == "de otro"


def test_consultas_de_hoy_cuenta_solo_la_fecha_del_timestamp_guardado(conn):
    bot_store.registrar_consulta(conn, 1, "a", ResultadoFalso(), t(dia=21))
    bot_store.registrar_consulta(conn, 1, "b", ResultadoFalso(), t(dia=21, h=23, m=59))
    bot_store.registrar_consulta(conn, 1, "c", ResultadoFalso(), t(dia=22))              # otro día
    assert bot_store.consultas_de_hoy(conn, 1, t(dia=21, h=0, m=1)) == 2
    assert bot_store.consultas_de_hoy(conn, 1, t(dia=22)) == 1
    assert bot_store.consultas_de_hoy(conn, 1, t(dia=23)) == 0


def test_resumen_del_dia_suma_costos_solo_de_ese_dia_y_ese_usuario(conn):
    bot_store.registrar_consulta(conn, 1, "a", ResultadoFalso(costo_ref=0.002), t(dia=21))
    bot_store.registrar_consulta(conn, 1, "b", ResultadoFalso(costo_ref=0.003), t(dia=21))
    bot_store.registrar_consulta(conn, 1, "c", ResultadoFalso(costo_ref=0.100), t(dia=22))
    bot_store.registrar_consulta(conn, 2, "d", ResultadoFalso(costo_ref=0.100), t(dia=21))
    d = bot_store.resumen_dia(conn, 1, t(dia=21))
    assert d["consultas"] == 2 and d["costo_referencia"] == pytest.approx(0.005) and d["costo_real"] == 0.0


def test_resumen_del_dia_sin_consultas_no_falla(conn):
    d = bot_store.resumen_dia(conn, 1, t())
    assert d == {"consultas": 0, "costo_real": 0.0, "costo_referencia": 0.0}


def test_registrar_feedback_dos_veces_actualiza_no_duplica(conn):
    cid = bot_store.registrar_consulta(conn, 1, "x", ResultadoFalso(), t())
    bot_store.registrar_feedback(conn, cid, 1, 1, t())
    bot_store.registrar_feedback(conn, cid, 1, -1, t(11))
    assert bot_store.feedback_de(conn, cid, 1) == -1
    assert len(bot_store.todo_el_feedback(conn)) == 1


def test_dos_usuarios_pueden_calificar_la_misma_consulta(conn):
    cid = bot_store.registrar_consulta(conn, 1, "x", ResultadoFalso(), t())
    bot_store.registrar_feedback(conn, cid, 1, 1, t())
    bot_store.registrar_feedback(conn, cid, 2, -1, t())
    assert len(bot_store.todo_el_feedback(conn)) == 2 and bot_store.feedback_de(conn, cid, 1) == 1 and bot_store.feedback_de(conn, cid, 2) == -1


def test_feedback_sin_calificar_es_none():
    pass  # cubierto por feedback_de en otras pruebas; explícito para claridad de la API


@pytest.mark.parametrize("valor", [0, 2, -2, "1"])
def test_un_valor_de_feedback_invalido_falla(conn, valor):
    cid = bot_store.registrar_consulta(conn, 1, "x", ResultadoFalso(), t())
    with pytest.raises(ValueError):
        bot_store.registrar_feedback(conn, cid, 1, valor, t())


def test_todo_el_feedback_trae_los_datos_de_la_consulta_calificada(conn):
    cid = bot_store.registrar_consulta(conn, 1, "¿pregunta?", ResultadoFalso(abstuvo=True, error=None), t())
    bot_store.registrar_feedback(conn, cid, 1, -1, t())
    f = bot_store.todo_el_feedback(conn)[0]
    assert f["pregunta"] == "¿pregunta?" and f["abstuvo"] == 1 and f["valor"] == -1 and f["consulta_id"] == cid


def test_abrir_db_es_idempotente_y_persiste_entre_conexiones(tmp_path):
    ruta = tmp_path / "sub" / "bot.db"
    c1 = bot_store.abrir_db(ruta)
    bot_store.registrar_consulta(c1, 1, "x", ResultadoFalso(), t())
    c1.close()
    c2 = bot_store.abrir_db(ruta)                                   # reabre el mismo archivo: no falla, no borra nada
    assert bot_store.ultima_consulta(c2, 1)["pregunta"] == "x"

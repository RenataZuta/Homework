"""Interfaz Streamlit probada sin navegador (AppTest): carga el índice sin reconstruirlo, muestra respuestas, abstenciones y errores como corresponde."""
import hashlib
import re
import uuid
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
import streamlit as st  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

from rag_engine.engine import Fuente, MotorRAG, ResultadoRAG  # noqa: E402
from rag_engine.config import cargar_config  # noqa: E402
from rag_engine.retrieval.indice import IndiceNoDisponible  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
APP = RAIZ / "app.py"


class MotorFalso:
    def __init__(self, resultado=None):
        self.resultado, self.preguntas = resultado, []

    def responder(self, pregunta):
        self.preguntas.append(pregunta)
        return self.resultado


def fuente(pagina=32, citada=False, origen="recuperado", doc="ley_32069", sim=0.883):
    return Fuente(documento=doc, version="ley_vigente", pagina=pagina, similitud=sim, fragmento_id=f"{doc}:v:p{pagina:04d}:c000", texto=f"Texto del fragmento de la página {pagina}.",
                  origen=origen, citada=citada)


def respondida(**kw):
    base = dict(respuesta="El pago se realiza en diez días hábiles [Ley 32069, p. 32].", fuentes=[fuente(32, True), fuente(33)], mejor_similitud=0.9, tokens_entrada=1222, tokens_salida=121,
                costo_usd_real=0.0, costo_usd_referencia=0.000669, latencia_ms=2449.0, modelo="gemini-3.5-flash-lite", proveedor="gemini", timestamp="2026-09-21T10:00:00-05:00")
    return ResultadoRAG(**{**base, **kw})


@pytest.fixture(autouse=True)
def caches_limpias():
    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


def abrir(monkeypatch, motor=None, error=None, cfg=None):
    """Por defecto usa una config con el log de costos apuntando a un archivo QUE NO EXISTE: así el tope global de la Fase 12
    (que lee logs/llm_calls.jsonl de verdad) nunca interfiere con pruebas que no lo están probando a propósito."""
    def desde_config(cfg_):
        if error:
            raise error
        return motor
    monkeypatch.setattr(MotorRAG, "desde_config", classmethod(lambda cls, cfg_=None: desde_config(cfg_)))
    if cfg is None:
        from fakes import cfg_con
        cfg = cfg_con(cargar_config(cargar_env=False), **{"paths.llm_calls_log": f"/tmp/no-existe-{uuid.uuid4()}.jsonl"})
    monkeypatch.setattr("rag_engine.config.cargar_config", lambda: cfg)
    return AppTest.from_file(str(APP), default_timeout=60).run()


def consultar(at, texto):
    at.text_area(key="pregunta").set_value(texto)
    next(b for b in at.button if b.label == "Consultar").click()
    return at.run()


def textos(elementos):
    return " ".join(str(e.value) for e in elementos)


# ── arranque ──

def test_la_app_abre_con_las_cuatro_pestanas_y_sin_excepciones(monkeypatch):
    at = abrir(monkeypatch, MotorFalso())
    assert not at.exception and [t.label for t in at.tabs] == ["Consulta", "Calidad de extracción", "Evaluación", "Costos"]


def test_si_falta_el_indice_muestra_un_error_con_instrucciones_y_no_lo_reconstruye(monkeypatch):
    llamado = []
    import indexing.build_index as bi
    monkeypatch.setattr(bi, "construir_indice", lambda *a, **k: llamado.append(1))
    at = abrir(monkeypatch, error=IndiceNoDisponible("No se encontró el índice en data/index. Constrúyelo antes de usar la app: python scripts/build_index.py"))
    assert not at.exception and llamado == []
    assert any("python scripts/build_index.py" in e.value for e in at.error)


def test_la_app_no_importa_ni_ejecuta_nada_de_indexacion_ni_extraccion():
    fuente_app = APP.read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import)\s+(indexing|extraction)\b", fuente_app, re.M)
    assert "subprocess" not in fuente_app and "construir_indice" not in fuente_app and "build_index" not in fuente_app.replace("scripts/build_index.py", "")


def test_el_motor_se_crea_una_sola_vez_aunque_la_pagina_se_recargue(monkeypatch):
    creados = []
    monkeypatch.setattr(MotorRAG, "desde_config", classmethod(lambda cls, cfg=None: creados.append(1) or MotorFalso(respondida())))
    at = AppTest.from_file(str(APP), default_timeout=60).run()
    consultar(at, "una pregunta")
    at.run()
    at2 = AppTest.from_file(str(APP), default_timeout=60).run()                   # otra sesión del mismo proceso
    assert creados == [1] and not at2.exception


def test_al_abrir_con_el_indice_real_no_se_modifica_su_contenido(monkeypatch):
    """Sin motor simulado: carga el índice de verdad (si existe) y comprueba que ninguna colección cambió."""
    from rag_engine.config import cargar_config
    from rag_engine.retrieval.indice import abrir_cliente
    cfg = cargar_config(cargar_env=False)
    ruta = cfg.ruta("index")
    if not ruta.is_dir():
        pytest.skip("no hay índice construido en este entorno")

    def huella():
        salida = []
        for col in abrir_cliente(ruta).list_collections():
            d = col.get(include=["metadatas"])
            salida.append((col.name, col.count(), hashlib.sha1("".join(sorted(m["hash_texto"] for m in d["metadatas"])).encode()).hexdigest()))
        return sorted(salida)
    antes = huella()
    at = AppTest.from_file(str(APP), default_timeout=120).run()
    assert not at.exception and not at.error and huella() == antes


# ── consulta ──

def test_una_pregunta_vacia_no_llama_al_motor(monkeypatch):
    motor = MotorFalso(respondida())
    at = consultar(abrir(monkeypatch, motor), "   ")
    assert motor.preguntas == [] and any("Escribe una pregunta" in w.value for w in at.warning)


def test_una_respuesta_muestra_texto_fuentes_citadas_y_costo(monkeypatch):
    motor = MotorFalso(respondida())
    at = consultar(abrir(monkeypatch, motor), "¿Plazo de pago?")
    assert motor.preguntas == ["¿Plazo de pago?"] and not at.exception and not at.error
    md = textos(at.markdown)
    assert "Respondió" in md and "diez días hábiles" in md and "Fragmentos citados por el modelo" in md and "Otros fragmentos recuperados (no citados)" in md
    etiquetas = [e.label for e in at.expander]
    assert any("ley_32069 · p. 32 · similitud 0.883" in e for e in etiquetas) and any("p. 33" in e for e in etiquetas)
    m = {}
    for x in at.metric:                                                                  # la 1.ª aparición es la de la pestaña Consulta (Costos repite etiquetas)
        m.setdefault(x.label, x.value)
    assert m["Tokens de entrada"] == "1,222" and m["Tokens de salida"] == "121" and m["Costo real (USD)"] == "0.000000" and m["Costo de referencia (USD)"] == "0.000669"
    assert m["Latencia total"] == "2.45 s" and m["Modelo"] == "gemini-3.5-flash-lite"


def test_la_abstencion_se_indica_por_el_campo_no_por_el_texto(monkeypatch):
    r = respondida(respuesta="No lo sé, pero aquí va un texto cualquiera.", abstuvo=False)
    md = textos(consultar(abrir(monkeypatch, MotorFalso(r)), "x").markdown)
    assert "Respondió" in md and "Se abstuvo" not in md                                  # el texto dice «no lo sé» pero el campo abstuvo es False
    r2 = respondida(respuesta="Mensaje de abstención.", abstuvo=True, motivo_abstencion="umbral", mejor_similitud=0.79, fuentes=[fuente(9)], modelo=None, proveedor=None,
                    tokens_entrada=0, tokens_salida=0, costo_usd_referencia=0.0, latencia_ms=30.0)
    st.cache_resource.clear()                                                            # otro motor simulado para la 2.ª sesión
    at = consultar(abrir(monkeypatch, MotorFalso(r2)), "x")
    assert "Se abstuvo de responder" in textos(at.markdown) and any("Mensaje de abstención." in w.value for w in at.warning)
    assert any("por debajo del umbral" in c.value and "0.790" in c.value for c in at.caption)
    assert any("No hubo llamada al modelo" in i.value for i in at.info)
    assert any("Fragmentos más cercanos a la pregunta" in m.value for m in at.markdown)   # sin citas: se muestran como los más cercanos


def test_una_abstencion_del_llm_da_su_motivo(monkeypatch):
    r = respondida(respuesta="Mensaje.", abstuvo=True, motivo_abstencion="llm_sin_contexto")
    at = consultar(abrir(monkeypatch, MotorFalso(r)), "x")
    assert any("el modelo declaró que el contexto recuperado no alcanza" in c.value for c in at.caption)


def test_los_errores_se_muestran_con_st_error_y_nunca_como_respuesta(monkeypatch):
    r = ResultadoRAG(respuesta=None, error="La clave de API es inválida.", error_tipo="autenticacion", timestamp="t")
    at = consultar(abrir(monkeypatch, MotorFalso(r)), "x")
    assert any("La clave de API es inválida." in e.value for e in at.error) and "Respondió" not in textos(at.markdown)


def test_la_cuota_agotada_muestra_el_mensaje_de_la_config_y_el_detalle(monkeypatch):
    r = ResultadoRAG(respuesta=None, error="Se agotó la cuota DIARIA de Google (detalle)", error_tipo="cuota_agotada", timestamp="t")
    at = consultar(abrir(monkeypatch, MotorFalso(r)), "x")
    assert any("Se agotó la cuota gratuita" in e.value for e in at.error) and any("detalle" in c.value for c in at.caption)


def test_los_avisos_de_version_se_agrupan_sin_repetidos(monkeypatch):
    avisos = ["El artículo 114 fue modificado por el DS 001-2026-EF.", "El artículo 114 fue modificado por el DS 001-2026-EF.", "El artículo 149 fue modificado."]
    at = consultar(abrir(monkeypatch, MotorFalso(respondida(advertencias_version=avisos))), "x")
    w = [x.value for x in at.warning if "Aviso de versión" in x.value]
    assert len(w) == 1 and w[0].count("artículo 114") == 1 and "artículo 149" in w[0]


def test_las_fuentes_forzadas_de_version_dicen_su_origen(monkeypatch):
    r = respondida(fuentes=[fuente(32, True), fuente(14, False, "version", "ds_001_2026_ef"), fuente(29, False, "original", "ds_009_2025_ef")])
    etiquetas = [e.label for e in consultar(abrir(monkeypatch, MotorFalso(r)), "x").expander]
    assert any("modificatoria forzada" in e for e in etiquetas) and any("texto original forzado" in e for e in etiquetas)


def test_un_ejemplo_rellena_la_pregunta(monkeypatch):
    at = abrir(monkeypatch, MotorFalso(respondida()))
    ejemplo = next(b for b in at.button if b.label != "Consultar")
    ejemplo.click()
    at.run()
    assert at.text_area(key="pregunta").value


# ── pestañas de reportes ──

def test_las_pestanas_de_reportes_muestran_datos_reales(monkeypatch):
    at = abrir(monkeypatch, MotorFalso(), cfg=cargar_config(cargar_env=False))     # config real: quiere ver los reportes de verdad
    assert not at.exception
    etiquetas = {m.label for m in at.metric}
    assert {"Recall@1", "Recall@3", "Recall@5", "Llamadas", "Costo real (USD)", "Costo de referencia (USD)"} <= etiquetas
    assert any("PROVISIONAL" in w.value for w in at.warning)                             # el set aún no está validado
    assert len(at.dataframe) >= 5 and not any("Pendiente (Fase 8)" in i.value for i in at.info)       # la comparación BM25 ya existe (Fase 8): se muestra la tabla


# ── Fase 12: topes de gasto (la app pública usa la clave de la persona) ──

def test_el_tope_de_sesion_impide_llamar_al_motor_y_avisa(monkeypatch, tmp_path):
    from fakes import cfg_con
    base = cargar_config(cargar_env=False)
    cfg = cfg_con(base, **{"paths.llm_calls_log": str(tmp_path / "log.jsonl"), "deploy.topes.consultas_por_sesion": 2})
    motor = MotorFalso(respondida())
    at = abrir(monkeypatch, motor, cfg=cfg)
    consultar(at, "pregunta 1")
    consultar(at, "pregunta 2")
    assert len(motor.preguntas) == 2                                     # las dos primeras sí llaman al motor (tope = 2)
    at = consultar(at, "pregunta 3")
    assert len(motor.preguntas) == 2                                     # la 3.ª NO llama: ya se alcanzó el tope de sesión
    assert any(w.value == cfg.get("mensajes.limite_sesion") for w in at.warning)


def test_una_abstencion_por_umbral_no_gasta_cupo_de_sesion(monkeypatch, tmp_path):
    """r.modelo es None cuando la compuerta del umbral abstiene sin llamar al LLM: no debe contar para el tope."""
    from fakes import cfg_con
    base = cargar_config(cargar_env=False)
    cfg = cfg_con(base, **{"paths.llm_calls_log": str(tmp_path / "log.jsonl"), "deploy.topes.consultas_por_sesion": 1})
    abstencion_por_umbral = respondida(respuesta="Mensaje de abstención.", abstuvo=True, motivo_abstencion="umbral", modelo=None, proveedor=None,
                                       tokens_entrada=0, tokens_salida=0, costo_usd_referencia=0.0)
    motor = MotorFalso(abstencion_por_umbral)
    at = abrir(monkeypatch, motor, cfg=cfg)
    consultar(at, "pregunta fuera de dominio 1")
    at = consultar(at, "pregunta fuera de dominio 2")
    assert len(motor.preguntas) == 2                                     # ninguna de las dos gastó cupo: el tope (1) nunca se alcanzó
    assert not any(w.value == cfg.get("mensajes.limite_sesion") for w in at.warning)


def test_el_tope_global_lee_llamadas_de_hoy_del_log_de_costos(monkeypatch, tmp_path):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from fakes import cfg_con
    from rag_engine.llm.cost_log import registrar_llamada
    base = cargar_config(cargar_env=False)
    ruta_log = tmp_path / "log.jsonl"
    cfg = cfg_con(base, **{"paths.llm_calls_log": str(ruta_log), "deploy.topes.consultas_globales_por_dia": 1, "deploy.topes.consultas_por_sesion": 100})
    hoy = datetime.now(ZoneInfo(cfg.get("deploy.zona_horaria"))).strftime("%Y-%m-%dT10:00:00-05:00")
    registrar_llamada(ruta_log, timestamp=hoy, proveedor="gemini", modelo="gemini-3.5-flash-lite", nivel="gratuito", tokens_in=100, tokens_out=10,
                      latencia_ms=500.0, costo_usd_real=0.0, costo_usd_referencia=0.0001, intentos=1, exito=True)   # ya hay 1 llamada de OTRA sesión hoy
    motor = MotorFalso(respondida())
    at = abrir(monkeypatch, motor, cfg=cfg)
    at = consultar(at, "una pregunta nueva")
    assert motor.preguntas == []                                         # el tope global (1) ya estaba en 1: no se llama
    assert any(w.value == cfg.get("mensajes.limite_global") for w in at.warning)


def test_el_sidebar_muestra_el_cupo_de_hoy_y_de_la_sesion(monkeypatch, tmp_path):
    from fakes import cfg_con
    base = cargar_config(cargar_env=False)
    cfg = cfg_con(base, **{"paths.llm_calls_log": str(tmp_path / "log.jsonl"), "deploy.topes.consultas_por_sesion": 5, "deploy.topes.consultas_globales_por_dia": 50})
    at = abrir(monkeypatch, MotorFalso(), cfg=cfg)
    assert any("0/50 consultas globales" in c.value and "0/5 de esta sesión" in c.value for c in at.caption)

"""Handlers de Telegram: autorización sin gastar LLM, comandos, límite diario, feedback y que el token nunca se registra."""
from datetime import datetime, timedelta, timezone

import pytest

from fakes import cfg_con
from interfaces import bot_store, telegram_handlers
from rag_engine.config import cargar_config
from rag_engine.engine import ResultadoRAG

BASE = cargar_config(cargar_env=False)
LIMA = timezone(timedelta(hours=-5))
PERMITIDOS = {111}


class ClienteFalso:
    def __init__(self):
        self.mensajes, self.callbacks = [], []

    def enviar_mensaje(self, chat_id, texto, teclado=None):
        self.mensajes.append({"chat_id": chat_id, "texto": texto, "teclado": teclado})

    def responder_callback(self, callback_query_id, texto=None):
        self.callbacks.append({"id": callback_query_id, "texto": texto})


def fuente(pagina=32, citada=True):
    from rag_engine.engine import Fuente
    return Fuente(documento="ley_32069", version="ley_vigente", pagina=pagina, similitud=0.9, fragmento_id=f"x:v:p{pagina:04d}:c000",
                 texto="El pago se realiza en diez días hábiles.", origen="recuperado", citada=citada)


def respondida(**kw):
    base = dict(respuesta="Son diez días hábiles [Ley 32069, p. 32].", fuentes=[fuente()], mejor_similitud=0.9, tokens_entrada=1200, tokens_salida=120,
                costo_usd_real=0.0, costo_usd_referencia=0.0007, latencia_ms=2000.0, modelo="gemini-3.5-flash-lite", proveedor="gemini", timestamp="t")
    return ResultadoRAG(**{**base, **kw})


def responder_falso(resultado):
    llamadas = []

    def f(pregunta):
        llamadas.append(pregunta)
        return resultado
    f.llamadas = llamadas
    return f


def mensaje(texto, user_id=111, chat_id=555):
    return {"from": {"id": user_id}, "chat": {"id": chat_id}, "text": texto}


def reloj_fijo(dt):
    return lambda zona: dt


@pytest.fixture
def conn(tmp_path):
    return bot_store.abrir_db(tmp_path / "b.db")


def procesar(conn, cliente, texto, *, responder_fn=None, permitidos=PERMITIDOS, user_id=111, ahora=None, cfg=BASE):
    telegram_handlers.procesar_mensaje(cfg, conn, cliente, mensaje(texto, user_id=user_id), permitidos,
                                       responder_fn=responder_fn or responder_falso(respondida()), reloj=reloj_fijo(ahora or datetime(2026, 9, 21, 10, tzinfo=LIMA)))


# ── autorización: nunca llama al motor ──

def test_un_usuario_no_autorizado_recibe_el_mensaje_de_config_y_no_llama_al_motor(conn):
    cliente, rf = ClienteFalso(), responder_falso(respondida())
    procesar(conn, cliente, "¿plazo de pago?", responder_fn=rf, permitidos=set(), user_id=999)
    assert rf.llamadas == [] and cliente.mensajes == [{"chat_id": 555, "texto": BASE.get("mensajes.bot.no_autorizado"), "teclado": None}]
    assert bot_store.ultima_consulta(conn, 999) is None                             # tampoco se guarda nada


def test_un_usuario_autorizado_si_recibe_respuesta(conn):
    cliente = ClienteFalso()
    procesar(conn, cliente, "¿plazo de pago?", cfg=BASE)
    assert cliente.mensajes[0]["texto"].startswith("Son diez días") and cliente.mensajes[0]["teclado"] is not None


# ── comandos: tampoco llaman al motor ──

def test_ayuda_no_llama_al_motor_y_lleva_el_limite(conn):
    cliente, rf = ClienteFalso(), responder_falso(respondida())
    procesar(conn, cliente, "/ayuda", responder_fn=rf)
    assert rf.llamadas == [] and str(BASE.get("bot.limite_consultas_por_usuario_dia")) in cliente.mensajes[0]["texto"]


def test_fuente_sin_historial_da_el_mensaje_de_config(conn):
    cliente = ClienteFalso()
    procesar(conn, cliente, "/fuente")
    assert cliente.mensajes == [{"chat_id": 555, "texto": BASE.get("mensajes.bot.sin_fuente"), "teclado": None}]


def test_fuente_con_historial_muestra_documento_pagina_similitud_y_texto(conn):
    cliente = ClienteFalso()
    procesar(conn, cliente, "¿plazo de pago?")                                       # deja una consulta en el historial
    procesar(conn, cliente, "/fuente")
    t = cliente.mensajes[-1]["texto"]
    assert "ley_32069" in t and "p. 32" in t and "0.900" in t and "diez días hábiles" in t


def test_costo_sin_historial_da_el_mensaje_de_config(conn):
    cliente = ClienteFalso()
    procesar(conn, cliente, "/costo")
    assert cliente.mensajes == [{"chat_id": 555, "texto": BASE.get("mensajes.bot.sin_costo"), "teclado": None}]


def test_costo_con_historial_muestra_la_ultima_y_el_acumulado_del_dia(conn):
    cliente = ClienteFalso()
    procesar(conn, cliente, "¿plazo de pago?")
    procesar(conn, cliente, "/costo")
    t = cliente.mensajes[-1]["texto"]
    assert "0.000700" in t and "1200 tokens" in t and "1 consulta" in t


def test_un_comando_no_cuenta_para_el_limite_diario(conn):
    cliente, cfg = ClienteFalso(), cfg_con(BASE, **{"bot.limite_consultas_por_usuario_dia": 1})
    for _ in range(5):
        procesar(conn, cliente, "/ayuda", cfg=cfg)
    procesar(conn, cliente, "¿plazo de pago?", cfg=cfg)
    assert "Son diez días" in cliente.mensajes[-1]["texto"]                          # la 1.ª pregunta real todavía cabe en el límite


# ── límite diario ──

def test_al_superar_el_limite_avisa_y_no_llama_al_motor(conn):
    cliente, rf, cfg = ClienteFalso(), responder_falso(respondida()), cfg_con(BASE, **{"bot.limite_consultas_por_usuario_dia": 2})
    for _ in range(2):
        procesar(conn, cliente, "pregunta", responder_fn=rf, cfg=cfg)
    procesar(conn, cliente, "otra pregunta", responder_fn=rf, cfg=cfg)
    assert len(rf.llamadas) == 2 and cliente.mensajes[-1]["texto"] == cfg.get("mensajes.bot.limite_excedido").format(limite=2)


def test_el_limite_es_por_usuario_y_por_dia(conn):
    cliente, rf, cfg = ClienteFalso(), responder_falso(respondida()), cfg_con(BASE, **{"bot.limite_consultas_por_usuario_dia": 1})
    telegram_handlers.procesar_mensaje(cfg, conn, cliente, mensaje("p", user_id=111), PERMITIDOS | {222}, responder_fn=rf, reloj=reloj_fijo(datetime(2026, 9, 21, 10, tzinfo=LIMA)))
    telegram_handlers.procesar_mensaje(cfg, conn, cliente, mensaje("p", user_id=222), PERMITIDOS | {222}, responder_fn=rf, reloj=reloj_fijo(datetime(2026, 9, 21, 10, tzinfo=LIMA)))
    assert len(rf.llamadas) == 2                                                     # cada usuario tiene su propio cupo
    telegram_handlers.procesar_mensaje(cfg, conn, cliente, mensaje("p", user_id=111), PERMITIDOS | {222}, responder_fn=rf, reloj=reloj_fijo(datetime(2026, 9, 22, 10, tzinfo=LIMA)))
    assert len(rf.llamadas) == 3                                                     # al día siguiente el cupo se renueva


# ── abstención y error ──

def test_una_abstencion_no_lleva_texto_crudo_del_error_pero_si_boton_de_feedback(conn):
    cliente = ClienteFalso()
    procesar(conn, cliente, "algo", responder_fn=responder_falso(respondida(abstuvo=True, motivo_abstencion="umbral", respuesta="mensaje de abstención", fuentes=[])))
    assert cliente.mensajes[0]["texto"] == "mensaje de abstención" and cliente.mensajes[0]["teclado"] is not None


def test_un_error_muestra_el_mensaje_generico_no_el_texto_tecnico_y_sin_boton(conn):
    r = ResultadoRAG(respuesta=None, error="detalle técnico interno con una ruta /Users/x/secreto", error_tipo="red", timestamp="t")
    cliente = ClienteFalso()
    procesar(conn, cliente, "algo", responder_fn=responder_falso(r))
    assert cliente.mensajes[0]["texto"] == BASE.get("mensajes.error_generico") and cliente.mensajes[0]["teclado"] is None
    assert "/Users" not in cliente.mensajes[0]["texto"]


def test_la_cuota_agotada_muestra_su_propio_mensaje(conn):
    r = ResultadoRAG(respuesta=None, error="cuota diaria agotada, detalle", error_tipo="cuota_agotada", timestamp="t")
    cliente = ClienteFalso()
    procesar(conn, cliente, "algo", responder_fn=responder_falso(r))
    assert cliente.mensajes[0]["texto"] == BASE.get("mensajes.error_cuota")


def test_los_avisos_de_version_se_agregan_sin_repetirse(conn):
    cliente = ClienteFalso()
    avisos = ["Artículo 114 modificado.", "Artículo 114 modificado.", "Artículo 149 modificado."]
    procesar(conn, cliente, "algo", responder_fn=responder_falso(respondida(advertencias_version=avisos)))
    t = cliente.mensajes[0]["texto"]
    assert t.count("Artículo 114") == 1 and "Artículo 149" in t


def test_un_mensaje_vacio_o_sin_texto_no_hace_nada(conn):
    cliente, rf = ClienteFalso(), responder_falso(respondida())
    telegram_handlers.procesar_mensaje(BASE, conn, cliente, {"from": {"id": 111}, "chat": {"id": 5}}, PERMITIDOS, responder_fn=rf)     # sin "text" (p. ej. una foto)
    telegram_handlers.procesar_mensaje(BASE, conn, cliente, mensaje("   "), PERMITIDOS, responder_fn=rf)
    assert cliente.mensajes == [] and rf.llamadas == []


# ── feedback (callback_query) ──

def callback(data, user_id=111, cb_id="cb1"):
    return {"id": cb_id, "from": {"id": user_id}, "data": data}


def test_un_feedback_valido_se_guarda_y_agradece(conn):
    cid = bot_store.registrar_consulta(conn, 111, "x", respondida(), datetime(2026, 9, 21, 10, tzinfo=LIMA))
    cliente = ClienteFalso()
    telegram_handlers.procesar_callback(BASE, conn, cliente, callback(f"fb:{cid}:1"), PERMITIDOS, reloj=reloj_fijo(datetime(2026, 9, 21, 10, tzinfo=LIMA)))
    assert bot_store.feedback_de(conn, cid, 111) == 1
    assert cliente.callbacks == [{"id": "cb1", "texto": BASE.get("mensajes.bot.feedback_gracias")}]


def test_un_usuario_no_autorizado_no_puede_dejar_feedback(conn):
    cid = bot_store.registrar_consulta(conn, 111, "x", respondida(), datetime(2026, 9, 21, 10, tzinfo=LIMA))
    cliente = ClienteFalso()
    telegram_handlers.procesar_callback(BASE, conn, cliente, callback(f"fb:{cid}:1", user_id=999), PERMITIDOS)
    assert bot_store.feedback_de(conn, cid, 999) is None and cliente.callbacks == [{"id": "cb1", "texto": None}]


def test_no_se_puede_calificar_la_consulta_de_otro_usuario(conn):
    cid = bot_store.registrar_consulta(conn, 222, "x", respondida(), datetime(2026, 9, 21, 10, tzinfo=LIMA))
    cliente = ClienteFalso()
    telegram_handlers.procesar_callback(BASE, conn, cliente, callback(f"fb:{cid}:1", user_id=111), PERMITIDOS)
    assert bot_store.feedback_de(conn, cid, 111) is None


def test_un_callback_data_con_formato_invalido_o_una_consulta_inexistente_no_rompe(conn):
    cliente = ClienteFalso()
    for data in ("basura", "fb:abc:1", "fb:1:0", "fb:99999:1"):
        telegram_handlers.procesar_callback(BASE, conn, cliente, callback(data), PERMITIDOS)
    assert all(c["texto"] is None for c in cliente.callbacks) and len(cliente.callbacks) == 4


def test_dispatch_por_update_manda_al_handler_correcto(conn):
    cliente = ClienteFalso()
    telegram_handlers.procesar_update({"message": mensaje("/ayuda")}, BASE, conn, cliente, PERMITIDOS)
    assert cliente.mensajes and cliente.callbacks == []
    cid = bot_store.registrar_consulta(conn, 111, "x", respondida(), datetime(2026, 9, 21, tzinfo=LIMA))
    telegram_handlers.procesar_update({"callback_query": callback(f"fb:{cid}:1")}, BASE, conn, cliente, PERMITIDOS, reloj=reloj_fijo(datetime(2026, 9, 21, tzinfo=LIMA)))
    assert cliente.callbacks


def test_usuarios_permitidos_parsea_ids_separados_por_coma_e_ignora_basura(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", " 111, 222 ,abc, -5,")
    assert telegram_handlers.usuarios_permitidos(BASE) == {111, 222, -5}


def test_usuarios_permitidos_vacio_es_conjunto_vacio_no_error(monkeypatch):
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    assert telegram_handlers.usuarios_permitidos(BASE) == set()


# ── el token nunca aparece en lo que se registra o se muestra ──

def test_el_modulo_de_handlers_nunca_importa_ni_menciona_el_token_literal():
    fuente_ = Path = __import__("pathlib").Path(telegram_handlers.__file__).read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN" not in fuente_                                      # los handlers no leen el token: solo lo usa telegram_api


def test_los_handlers_no_importan_ninguna_libreria_de_interfaz_ajena():
    import re
    fuente_ = __import__("pathlib").Path(telegram_handlers.__file__).read_text(encoding="utf-8")
    assert not re.search(r"streamlit|fastapi|flask|gradio", fuente_, re.I)

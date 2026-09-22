"""Backend FastAPI (Fase 11): /health sin auth, /telegram/webhook exige la clave interna y procesa en segundo plano."""
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from fakes import cfg_con  # noqa: E402
from interfaces import api_server, bot_store, telegram_handlers  # noqa: E402
from interfaces.telegram_api import ClienteTelegram  # noqa: E402
from rag_engine.config import cargar_config  # noqa: E402

BASE = cargar_config(cargar_env=False)
CLAVE = "clave-interna-de-prueba-123"


class ClienteTelegramFalso:
    def __init__(self, *a, **k):
        self.mensajes = []

    def enviar_mensaje(self, chat_id, texto, teclado=None):
        self.mensajes.append({"chat_id": chat_id, "texto": texto})


@pytest.fixture
def cliente_api(tmp_path, monkeypatch):
    """TestClient con la app real, pero configuración, base de datos y cliente de Telegram de prueba (sin red)."""
    cfg = cfg_con(BASE, **{"paths.bot_db": str(tmp_path / "bot.db")})
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:" + "A" * 35)
    monkeypatch.setenv("BACKEND_INTERNAL_KEY", CLAVE)
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "111")
    monkeypatch.setattr(api_server, "cargar_config", lambda: cfg)
    monkeypatch.setattr(api_server, "ClienteTelegram", ClienteTelegramFalso)
    with TestClient(api_server.app) as c:
        yield c


def test_health_no_pide_autenticacion(cliente_api):
    r = cliente_api.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_webhook_sin_clave_interna_o_con_una_erronea_se_rechaza(cliente_api):
    update = {"message": {"from": {"id": 111}, "chat": {"id": 1}, "text": "/ayuda"}}
    assert cliente_api.post("/telegram/webhook", json=update).status_code == 403
    assert cliente_api.post("/telegram/webhook", json=update, headers={"X-Internal-Key": "otra"}).status_code == 403
    assert api_server.ESTADO["cliente"].mensajes == []


def _consulta_de(cid):
    conn = bot_store.abrir_db(api_server.ESTADO["ruta_db"])
    try:
        return bot_store.consulta_por_id(conn, cid)
    finally:
        conn.close()


def test_webhook_con_la_clave_correcta_procesa_el_update_en_segundo_plano(cliente_api):
    update = {"message": {"from": {"id": 111}, "chat": {"id": 555}, "text": "/ayuda"}}
    r = cliente_api.post("/telegram/webhook", json=update, headers={"X-Internal-Key": CLAVE})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert api_server.ESTADO["cliente"].mensajes[0] == {"chat_id": 555, "texto": telegram_handlers.texto_ayuda(BASE)}


def test_un_usuario_no_autorizado_no_gasta_el_motor_tampoco_desde_el_webhook(cliente_api, monkeypatch):
    llamado = []
    monkeypatch.setattr(telegram_handlers, "responder_motor", lambda p: llamado.append(p))
    update = {"message": {"from": {"id": 999}, "chat": {"id": 1}, "text": "una pregunta"}}
    cliente_api.post("/telegram/webhook", json=update, headers={"X-Internal-Key": CLAVE})
    assert llamado == [] and api_server.ESTADO["cliente"].mensajes[0]["texto"] == BASE.get("mensajes.bot.no_autorizado")


def test_un_cuerpo_que_no_es_json_o_no_es_un_objeto_da_400(cliente_api):
    r1 = cliente_api.post("/telegram/webhook", content=b"no es json", headers={"X-Internal-Key": CLAVE, "Content-Type": "application/json"})
    assert r1.status_code == 400
    r2 = cliente_api.post("/telegram/webhook", json=[1, 2, 3], headers={"X-Internal-Key": CLAVE})
    assert r2.status_code == 400


def test_un_callback_query_tambien_se_procesa_por_el_webhook(cliente_api):
    from datetime import datetime, timezone
    from rag_engine.engine import Fuente, ResultadoRAG
    conn = bot_store.abrir_db(api_server.ESTADO["ruta_db"])
    r = ResultadoRAG(respuesta="ok [Ley 32069, p. 1].", fuentes=[Fuente("ley_32069", "v", 1, 0.9, "id", "t", citada=True)], timestamp="t")
    cid = bot_store.registrar_consulta(conn, 111, "x", r, datetime(2026, 9, 21, tzinfo=timezone.utc))
    conn.close()
    update = {"callback_query": {"id": "cb1", "from": {"id": 111}, "data": f"fb:{cid}:1"}}
    cliente_api.post("/telegram/webhook", json=update, headers={"X-Internal-Key": CLAVE})
    conn2 = bot_store.abrir_db(api_server.ESTADO["ruta_db"])
    try:
        assert bot_store.feedback_de(conn2, cid, 111) == 1
    finally:
        conn2.close()


def test_la_clave_interna_nunca_se_repite_en_la_respuesta_de_error(cliente_api):
    r = cliente_api.post("/telegram/webhook", json={"message": {}}, headers={"X-Internal-Key": "no-es-la-clave-secreta-abc"})
    assert "no-es-la-clave-secreta-abc" not in r.text


def test_el_lifespan_crea_el_archivo_de_base_de_datos_y_limpia_su_estado_al_salir(tmp_path, monkeypatch):
    cfg1 = cfg_con(BASE, **{"paths.bot_db": str(tmp_path / "a.db")})
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:" + "A" * 35)
    monkeypatch.setenv("BACKEND_INTERNAL_KEY", "k1")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "111")
    monkeypatch.setattr(api_server, "cargar_config", lambda: cfg1)
    monkeypatch.setattr(api_server, "ClienteTelegram", ClienteTelegramFalso)
    with TestClient(api_server.app):
        assert (tmp_path / "a.db").is_file() and api_server.ESTADO["ruta_db"] == cfg1.ruta("bot_db")
    assert api_server.ESTADO == {}                                       # el lifespan limpia su estado al salir


def test_cada_background_task_usa_su_propia_conexion_sin_error_entre_hilos(cliente_api):
    """BackgroundTasks despacha las funciones síncronas a un hilo del pool: si _procesar_en_segundo_plano reutilizara
    una única sqlite3.Connection creada en otro hilo, esto fallaría con 'objects created in a thread...'."""
    for i in range(3):
        update = {"message": {"from": {"id": 111}, "chat": {"id": 1}, "text": f"pregunta {i}"}}
        assert cliente_api.post("/telegram/webhook", json=update, headers={"X-Internal-Key": CLAVE}).status_code == 200
    conn = bot_store.abrir_db(api_server.ESTADO["ruta_db"])
    try:
        assert bot_store.consultas_de_hoy(conn, 111, __import__("datetime").datetime.now(__import__("zoneinfo").ZoneInfo(BASE.get("bot.zona_horaria_limite")))) == 3
    finally:
        conn.close()

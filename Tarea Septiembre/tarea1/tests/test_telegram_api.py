"""Cliente de la Bot API: transporte simulado (nunca toca la red), clasificación de errores y sin filtrar el token."""
import pytest

from interfaces.telegram_api import ClienteTelegram, ErrorTelegram
from rag_engine.limites import ErrorProveedor

TOKEN = "123456789:" + "AAHsecretosecretosecretosecreto1234"          # falso: 10 dígitos + ':' + 35


class Transporte:
    def __init__(self, *respuestas):
        self.respuestas, self.llamadas = list(respuestas), []

    def __call__(self, url, cabeceras, cuerpo, timeout):
        self.llamadas.append({"url": url, "cabeceras": cabeceras, "cuerpo": cuerpo, "timeout": timeout})
        r = self.respuestas.pop(0) if len(self.respuestas) > 1 else self.respuestas[0]
        if isinstance(r, Exception):
            raise r
        return r


def ok(resultado):
    return (200, {"ok": True, "result": resultado}, {})


def error(estado, descripcion="fallo", parametros=None):
    return (estado, {"ok": False, "description": descripcion, **({"parameters": parametros} if parametros else {})}, {})


def cliente(t, **kw):
    return ClienteTelegram(TOKEN, transporte=t, **kw)


def test_la_url_lleva_el_token_pero_nunca_se_registra_en_los_mensajes_de_error():
    t = Transporte(error(400, f"tiene el token {TOKEN} adentro"))
    with pytest.raises(ErrorTelegram) as e:
        cliente(t).enviar_mensaje(1, "hola")
    assert TOKEN not in e.value.mensaje and "[CLAVE-OCULTA]" in e.value.mensaje
    assert t.llamadas[0]["url"] == f"https://api.telegram.org/bot{TOKEN}/sendMessage" and t.llamadas[0]["cabeceras"] == {}


def test_enviar_mensaje_trunca_a_4096_y_solo_lleva_teclado_si_se_da():
    t = Transporte(ok({"message_id": 1}))
    cliente(t).enviar_mensaje(5, "x" * 5000)
    c = t.llamadas[0]["cuerpo"]
    assert c["chat_id"] == 5 and len(c["text"]) == 4096 and "reply_markup" not in c
    t2 = Transporte(ok({}))
    cliente(t2).enviar_mensaje(5, "hola", teclado={"inline_keyboard": [[{"text": "👍", "callback_data": "fb:1:1"}]]})
    assert t2.llamadas[0]["cuerpo"]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "fb:1:1"


def test_responder_callback_trunca_a_200_y_es_opcional():
    t = Transporte(ok({}))
    cliente(t).responder_callback("cb1")
    assert t.llamadas[0]["cuerpo"] == {"callback_query_id": "cb1"}
    t2 = Transporte(ok({}))
    cliente(t2).responder_callback("cb2", texto="z" * 300)
    assert len(t2.llamadas[0]["cuerpo"]["text"]) == 200


def test_obtener_actualizaciones_manda_el_offset_solo_si_se_da():
    t = Transporte(ok([{"update_id": 1}]))
    assert cliente(t).obtener_actualizaciones() == [{"update_id": 1}]
    assert "offset" not in t.llamadas[0]["cuerpo"] and t.llamadas[0]["cuerpo"]["timeout"] == 25
    t2 = Transporte(ok([]))
    cliente(t2).obtener_actualizaciones(offset=42, timeout_s=10)
    assert t2.llamadas[0]["cuerpo"]["offset"] == 42 and t2.llamadas[0]["cuerpo"]["timeout"] == 10


def test_fijar_y_borrar_webhook():
    t = Transporte(ok(True))
    cliente(t).fijar_webhook("https://ejemplo.workers.dev/telegram", "secreto123")
    c = t.llamadas[0]["cuerpo"]
    assert c == {"url": "https://ejemplo.workers.dev/telegram", "secret_token": "secreto123", "allowed_updates": ["message", "callback_query"]}
    t2 = Transporte(ok(True))
    cliente(t2).borrar_webhook()
    assert t2.llamadas[0]["url"].endswith("/deleteWebhook")


@pytest.mark.parametrize("estado, tipo", [(429, "limite_de_tasa"), (401, "autenticacion"), (403, "autenticacion"), (400, "solicitud"), (500, "servidor"), (503, "servidor")])
def test_cada_error_http_se_clasifica(estado, tipo):
    with pytest.raises(ErrorTelegram) as e:
        cliente(Transporte(error(estado))).enviar_mensaje(1, "x")
    assert e.value.tipo == tipo


def test_un_429_trae_la_espera_sugerida_de_retry_after():
    with pytest.raises(ErrorTelegram) as e:
        cliente(Transporte(error(429, "too many requests", {"retry_after": 7}))).enviar_mensaje(1, "x")
    assert e.value.tipo == "limite_de_tasa" and e.value.espera_sugerida_s == 7


def test_un_ok_false_con_estado_200_tambien_es_un_error():
    with pytest.raises(ErrorTelegram):
        cliente(Transporte((200, {"ok": False, "description": "chat not found"}, {}))).enviar_mensaje(1, "x")


def test_un_fallo_de_red_del_transporte_se_reclasifica_como_errortelegram():
    with pytest.raises(ErrorTelegram) as e:
        cliente(Transporte(ErrorProveedor("red", "sin conexión"))).enviar_mensaje(1, "x")
    assert e.value.tipo == "red" and "sin conexión" in e.value.mensaje


def test_sin_token_falla_de_inmediato_sin_llamar_al_transporte():
    t = Transporte(ok({}))
    with pytest.raises(ErrorTelegram, match="TELEGRAM_BOT_TOKEN") as e:
        ClienteTelegram("", transporte=t)
    assert e.value.solicitud_enviada is False and t.llamadas == []

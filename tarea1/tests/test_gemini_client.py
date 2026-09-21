"""Cliente de Gemini con un transporte simulado (nunca toca la red): petición, respuesta estructurada y errores tipificados."""
import json

import pytest

from rag_engine.limites import ErrorProveedor, Limitador, PoliticaReintentos
from rag_engine.llm.base import ClienteConPolitica, EsquemaSalida, ErrorLLM
from rag_engine.llm.gemini_client import ClienteGemini

CLAVE = "AI" + "za" + "SyDsecretosecretosecretosecreto12345"          # falsa, partida para no disparar check_secrets
AJUSTES = {"modelo": "gemini-2.5-flash-lite", "max_tokens": 1024, "temperatura": 0.0, "timeout_segundos": 60,
           "url_base": "https://generativelanguage.googleapis.com/v1beta", "campo_esquema": "responseJsonSchema", "thinking_budget": None}
ESQUEMA = EsquemaSalida("responder_con_citas", "desc", {"respuesta": "r", "citas": "c", "contexto_suficiente": "s"})
SALIDA = {"respuesta": "Son 10 días hábiles [Ley 32069, p. 32].", "citas": [{"documento": "Ley 32069", "pagina": 32}], "contexto_suficiente": True}


def cuerpo_ok(salida=None, texto=None, uso=None, finish="STOP", partes_extra=()):
    partes = [*partes_extra, {"text": texto if texto is not None else json.dumps(salida or SALIDA)}]
    return {"candidates": [{"content": {"parts": partes, "role": "model"}, "finishReason": finish}],
            "usageMetadata": uso or {"promptTokenCount": 2100, "candidatesTokenCount": 310, "totalTokenCount": 2410}}


class Transporte:
    def __init__(self, *respuestas):
        self.respuestas, self.llamadas = list(respuestas), []

    def __call__(self, url, cabeceras, cuerpo, timeout):
        self.llamadas.append({"url": url, "cabeceras": cabeceras, "cuerpo": cuerpo, "timeout": timeout})
        r = self.respuestas.pop(0) if len(self.respuestas) > 1 else self.respuestas[0]
        if isinstance(r, Exception):
            raise r
        return r


def cliente(t, **aj):
    return ClienteGemini({**AJUSTES, **aj}, api_key=CLAVE, transporte=t)


def error_http(estado, mensaje="fallo", status="X", detalles=None, cabeceras=None):
    return (estado, {"error": {"code": estado, "message": mensaje, "status": status, "details": detalles or []}}, cabeceras or {})


# ── petición ──

def test_la_peticion_va_al_modelo_configurado_con_la_clave_en_la_cabecera_y_nunca_en_la_url():
    t = Transporte((200, cuerpo_ok(), {}))
    cliente(t).generar("SISTEMA", "USUARIO", ESQUEMA)
    c = t.llamadas[0]
    assert c["url"] == "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent"
    assert c["cabeceras"] == {"x-goog-api-key": CLAVE} and c["timeout"] == 60.0
    assert CLAVE not in c["url"] and CLAVE not in json.dumps(c["cuerpo"])


def test_el_cuerpo_lleva_sistema_usuario_esquema_y_limites_de_la_config():
    t = Transporte((200, cuerpo_ok(), {}))
    cliente(t).generar("SISTEMA", "USUARIO", ESQUEMA)
    b = t.llamadas[0]["cuerpo"]
    assert b["systemInstruction"] == {"parts": [{"text": "SISTEMA"}]}
    assert b["contents"] == [{"role": "user", "parts": [{"text": "USUARIO"}]}]
    g = b["generationConfig"]
    assert g["maxOutputTokens"] == 1024 and g["temperature"] == 0.0 and g["responseMimeType"] == "application/json"
    assert g["responseJsonSchema"] == ESQUEMA.json_schema() and g["responseJsonSchema"]["required"] == ["respuesta", "citas", "contexto_suficiente"]


def test_temperatura_y_thinking_solo_se_envian_si_estan_definidos():
    t = Transporte((200, cuerpo_ok(), {}))
    cliente(t, temperatura=None).generar("s", "u", ESQUEMA)
    cliente(t, temperatura=0.3, thinking_budget=0).generar("s", "u", ESQUEMA)
    sin, con = t.llamadas[0]["cuerpo"]["generationConfig"], t.llamadas[1]["cuerpo"]["generationConfig"]
    assert "temperature" not in sin and "thinkingConfig" not in sin
    assert con["temperature"] == 0.3 and con["thinkingConfig"] == {"thinkingBudget": 0}


def test_el_campo_del_esquema_es_configurable():
    t = Transporte((200, cuerpo_ok(), {}))
    cliente(t, campo_esquema="responseSchema").generar("s", "u", ESQUEMA)
    g = t.llamadas[0]["cuerpo"]["generationConfig"]
    assert "responseSchema" in g and "responseJsonSchema" not in g


# ── respuesta ──

def test_devuelve_respuesta_estructurada_con_tokens_modelo_y_momento():
    r = cliente(Transporte((200, cuerpo_ok(), {}))).generar("s", "u", ESQUEMA)
    assert r.respuesta.startswith("Son 10 días") and r.citas == SALIDA["citas"] and r.contexto_suficiente is True
    assert (r.tokens_in, r.tokens_out) == (2100, 310) and r.modelo == "gemini-2.5-flash-lite" and r.proveedor == "gemini"
    assert r.momento.tzinfo is not None and r.latencia_ms >= 0 and r.intentos == 1 and r.desde_cache is False


def test_los_tokens_de_razonamiento_se_suman_a_los_de_salida():
    uso = {"promptTokenCount": 100, "candidatesTokenCount": 50, "thoughtsTokenCount": 70}
    assert cliente(Transporte((200, cuerpo_ok(uso=uso), {}))).generar("s", "u", ESQUEMA).tokens_out == 120


def test_las_partes_de_razonamiento_no_se_mezclan_con_la_respuesta():
    cuerpo = cuerpo_ok(partes_extra=[{"text": "estoy pensando...", "thought": True}])
    assert cliente(Transporte((200, cuerpo, {}))).generar("s", "u", ESQUEMA).respuesta == SALIDA["respuesta"]


def test_tolera_un_cerco_de_codigo_alrededor_del_json():
    cuerpo = cuerpo_ok(texto="```json\n" + json.dumps(SALIDA) + "\n```")
    assert cliente(Transporte((200, cuerpo, {}))).generar("s", "u", ESQUEMA).contexto_suficiente is True


def test_contexto_insuficiente_es_un_campo():
    r = cliente(Transporte((200, cuerpo_ok({**SALIDA, "contexto_suficiente": False}), {}))).generar("s", "u", ESQUEMA)
    assert r.contexto_suficiente is False


@pytest.mark.parametrize("cuerpo", [
    {"candidates": []},                                                             # sin candidatos
    cuerpo_ok(texto="no es json"),
    cuerpo_ok(texto=json.dumps({"respuesta": "x"})),                                # faltan campos
    cuerpo_ok(texto=json.dumps({"respuesta": "x", "citas": [], "contexto_suficiente": "si"})),     # tipo erróneo
    cuerpo_ok(texto=json.dumps({"respuesta": 3, "citas": [], "contexto_suficiente": True})),
    cuerpo_ok(texto=json.dumps(["lista"])),
])
def test_una_respuesta_malformada_es_un_error_no_una_respuesta(cuerpo):
    with pytest.raises(ErrorLLM) as e:
        cliente(Transporte((200, cuerpo, {}))).generar("s", "u", ESQUEMA)
    assert e.value.tipo == "respuesta_malformada"


def test_una_respuesta_cortada_por_max_tokens_da_la_pista_de_la_config():
    cuerpo = cuerpo_ok(texto='{"respuesta": "se cortó a mit', finish="MAX_TOKENS")
    with pytest.raises(ErrorLLM, match="llm.max_tokens") as e:
        cliente(Transporte((200, cuerpo, {}))).generar("s", "u", ESQUEMA)
    assert e.value.tipo == "respuesta_malformada"


def test_el_bloqueo_de_google_es_un_error_tipificado():
    with pytest.raises(ErrorLLM) as e:
        cliente(Transporte((200, {"promptFeedback": {"blockReason": "SAFETY"}}, {}))).generar("s", "u", ESQUEMA)
    assert e.value.tipo == "respuesta_bloqueada" and "SAFETY" in e.value.mensaje
    with pytest.raises(ErrorLLM) as e2:
        cliente(Transporte((200, cuerpo_ok(finish="SAFETY"), {}))).generar("s", "u", ESQUEMA)
    assert e2.value.tipo == "respuesta_bloqueada"


# ── errores HTTP ──

MINUTO = error_http(429, "Resource has been exhausted (e.g. check quota).", "RESOURCE_EXHAUSTED",
                    [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "27s"},
                     {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                      "violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]}])
DIARIA = error_http(429, "Quota exceeded", "RESOURCE_EXHAUSTED",
                    [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                      "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}])


def test_429_por_minuto_es_limite_de_tasa_y_trae_la_espera_sugerida():
    with pytest.raises(ErrorLLM) as e:
        cliente(Transporte(MINUTO)).generar("s", "u", ESQUEMA)
    assert e.value.tipo == "limite_de_tasa" and e.value.espera_sugerida_s == 27.0


def test_429_por_cuota_diaria_es_cuota_agotada_y_no_es_reintentable():
    with pytest.raises(ErrorLLM) as e:
        cliente(Transporte(DIARIA)).generar("s", "u", ESQUEMA)
    assert e.value.tipo == "cuota_agotada" and "DIARIA" in e.value.mensaje and e.value.espera_sugerida_s is None


def test_retry_after_en_cabecera_tambien_sirve_de_espera_sugerida():
    with pytest.raises(ErrorLLM) as e:
        cliente(Transporte(error_http(429, "x", cabeceras={"Retry-After": "12"}))).generar("s", "u", ESQUEMA)
    assert e.value.espera_sugerida_s == 12.0


@pytest.mark.parametrize("respuesta, tipo", [
    (error_http(400, "API key not valid. Please pass a valid API key.", "INVALID_ARGUMENT"), "autenticacion"),
    (error_http(401), "autenticacion"), (error_http(403, "denied", "PERMISSION_DENIED"), "autenticacion"),
    (error_http(400, "Invalid JSON payload", "INVALID_ARGUMENT"), "solicitud"), (error_http(404, "model not found", "NOT_FOUND"), "solicitud"),
    (error_http(500, "internal", "INTERNAL"), "servidor"), (error_http(503, "overloaded", "UNAVAILABLE"), "servidor"),
    (error_http(504, "deadline", "DEADLINE_EXCEEDED"), "red"), (error_http(418), "otro"),
    ((502, None, {}), "servidor"),                                                   # cuerpo que no es JSON
])
def test_cada_error_http_se_clasifica(respuesta, tipo):
    with pytest.raises(ErrorLLM) as e:
        cliente(Transporte(respuesta)).generar("s", "u", ESQUEMA)
    assert e.value.tipo == tipo and e.value.mensaje


def test_un_fallo_de_red_del_transporte_es_un_error_de_red():
    with pytest.raises(ErrorLLM) as e:
        cliente(Transporte(ErrorProveedor("red", "sin conexión"))).generar("s", "u", ESQUEMA)
    assert e.value.tipo == "red" and "sin conexión" in e.value.mensaje


def test_los_mensajes_de_error_no_filtran_la_clave():
    with pytest.raises(ErrorLLM) as e:
        cliente(Transporte(error_http(400, f"API key not valid: {CLAVE} (x-goog-api-key: {CLAVE})", "INVALID_ARGUMENT"))).generar("s", "u", ESQUEMA)
    assert CLAVE not in e.value.mensaje and "[CLAVE-OCULTA]" in e.value.mensaje and "GEMINI_API_KEY" in e.value.mensaje


def test_sin_clave_falla_con_instrucciones_y_sin_enviar_nada():
    t = Transporte((200, cuerpo_ok(), {}))
    with pytest.raises(ErrorLLM, match="GEMINI_API_KEY") as e:
        ClienteGemini(AJUSTES, api_key=None, transporte=t)
    assert e.value.tipo == "autenticacion" and e.value.solicitud_enviada is False and t.llamadas == []


# ── con throttle y reintentos ──

def con_politica(t, reintentos=4, dormidos=None):
    lim = Limitador(None)
    pol = PoliticaReintentos(reintentos, 4, 2, 60, 0.0, dormir=(dormidos if dormidos is not None else []).append, azar=lambda: 0.0)
    return ClienteConPolitica(cliente(t), lim, pol)


def test_un_429_por_minuto_se_reintenta_y_termina_bien_registrando_los_intentos():
    dormidos, t = [], Transporte(MINUTO, (200, cuerpo_ok(), {}))
    r = con_politica(t, dormidos=dormidos).generar("s", "u", ESQUEMA)
    assert r.respuesta and r.intentos == 2 and len(t.llamadas) == 2 and dormidos == [27.0]         # respeta el retryDelay de Google


def test_un_5xx_se_reintenta_con_backoff_exponencial():
    dormidos, t = [], Transporte(error_http(503), error_http(503), (200, cuerpo_ok(), {}))
    assert con_politica(t, dormidos=dormidos).generar("s", "u", ESQUEMA).intentos == 3 and dormidos == [4, 8]


def test_si_la_cuota_por_minuto_no_se_recupera_el_error_final_es_cuota_agotada():
    t = Transporte(error_http(429, "x", "RESOURCE_EXHAUSTED"))
    with pytest.raises(ErrorLLM) as e:
        con_politica(t, reintentos=3).generar("s", "u", ESQUEMA)
    assert e.value.tipo == "cuota_agotada" and e.value.intentos == 4 and len(t.llamadas) == 4


def test_la_cuota_diaria_agotada_falla_de_inmediato_sin_reintentar():
    dormidos, t = [], Transporte(DIARIA)
    with pytest.raises(ErrorLLM) as e:
        con_politica(t, dormidos=dormidos).generar("s", "u", ESQUEMA)
    assert e.value.tipo == "cuota_agotada" and len(t.llamadas) == 1 and dormidos == []


def test_una_clave_invalida_no_se_reintenta():
    t = Transporte(error_http(403, "denied", "PERMISSION_DENIED"))
    with pytest.raises(ErrorLLM):
        con_politica(t).generar("s", "u", ESQUEMA)
    assert len(t.llamadas) == 1

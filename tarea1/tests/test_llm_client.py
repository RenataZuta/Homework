"""Cliente de Anthropic con un SDK simulado: respuesta estructurada, formato malformado y errores tipificados."""
from types import SimpleNamespace

import pytest

from rag_engine.llm.anthropic_client import ClienteAnthropic, ErrorLLM, clasificar_error

AJUSTES = {"modelo": "claude-haiku-4-5-20251001", "max_tokens": 1024, "temperatura": 0.0, "timeout_segundos": 60, "reintentos": 2}
CAMPOS = {"respuesta": "r", "citas": "c", "contexto_suficiente": "s"}
HERR = ClienteAnthropic.herramienta("responder_con_citas", "desc", CAMPOS)


def bloque(**entrada):
    return SimpleNamespace(type="tool_use", name="responder_con_citas", input=entrada)


class SDKFalso:
    def __init__(self, respuesta=None, error=None):
        self.llamadas, self._r, self._e = [], respuesta, error
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.llamadas.append(kw)
        if self._e:
            raise self._e
        return self._r


def ok(**extra):
    entrada = {"respuesta": "Son 10 días hábiles [Ley 32069, p. 32].", "citas": [{"documento": "Ley 32069", "pagina": 32}], "contexto_suficiente": True, **extra}
    return SimpleNamespace(content=[bloque(**entrada)], usage=SimpleNamespace(input_tokens=2100, output_tokens=310))


def cliente(sdk, **aj):
    return ClienteAnthropic({**AJUSTES, **aj}, cliente=sdk)


# ── camino feliz ──

def test_devuelve_respuesta_estructurada_con_tokens_y_latencia():
    r = cliente(SDKFalso(ok())).generar("sistema", "usuario", HERR)
    assert r.respuesta.startswith("Son 10 días") and r.citas == [{"documento": "Ley 32069", "pagina": 32}] and r.contexto_suficiente is True
    assert (r.tokens_in, r.tokens_out) == (2100, 310) and r.latencia_ms >= 0 and r.modelo == AJUSTES["modelo"] and r.momento.tzinfo is not None


def test_fuerza_el_uso_de_la_herramienta_y_envia_el_modelo_y_los_limites_de_la_config():
    sdk = SDKFalso(ok())
    cliente(sdk).generar("SISTEMA", "USUARIO", HERR)
    kw = sdk.llamadas[0]
    assert kw["model"] == AJUSTES["modelo"] and kw["max_tokens"] == 1024 and kw["system"] == "SISTEMA"
    assert kw["messages"] == [{"role": "user", "content": "USUARIO"}]
    assert kw["tool_choice"] == {"type": "tool", "name": "responder_con_citas"} and kw["tools"] == [HERR]


def test_la_temperatura_solo_se_envia_si_esta_definida():
    sdk = SDKFalso(ok())
    cliente(sdk, temperatura=0.0).generar("s", "u", HERR)
    cliente(sdk, temperatura=None).generar("s", "u", HERR)
    assert sdk.llamadas[0]["extra_body"] == {"temperature": 0.0} and "extra_body" not in sdk.llamadas[1]


def test_contexto_insuficiente_es_un_campo_no_un_texto():
    r = cliente(SDKFalso(ok(contexto_suficiente=False, respuesta="No lo sé"))).generar("s", "u", HERR)
    assert r.contexto_suficiente is False


def test_el_esquema_de_la_herramienta_exige_los_tres_campos():
    assert HERR["input_schema"]["required"] == ["respuesta", "citas", "contexto_suficiente"] and HERR["name"] == "responder_con_citas"


# ── formato malformado ──

@pytest.mark.parametrize("respuesta", [
    SimpleNamespace(content=[SimpleNamespace(type="text", text="hola")], usage=SimpleNamespace(input_tokens=1, output_tokens=1)),     # sin tool_use
    SimpleNamespace(content=[], usage=SimpleNamespace(input_tokens=1, output_tokens=1)),
    SimpleNamespace(content=[bloque(respuesta="x")], usage=SimpleNamespace(input_tokens=1, output_tokens=1)),                        # faltan campos
    SimpleNamespace(content=[bloque(respuesta="x", citas=[], contexto_suficiente="si")], usage=SimpleNamespace(input_tokens=1, output_tokens=1)),   # tipo erróneo
    SimpleNamespace(content=[bloque(respuesta=123, citas=[], contexto_suficiente=True)], usage=SimpleNamespace(input_tokens=1, output_tokens=1)),
])
def test_una_respuesta_malformada_es_un_error(respuesta):
    with pytest.raises(ErrorLLM) as e:
        cliente(SDKFalso(respuesta)).generar("s", "u", HERR)
    assert e.value.tipo == "respuesta_malformada"


# ── errores tipificados (clases con el nombre del SDK, sin importar el SDK) ──

def _exc(nombre, codigo=None, texto="falló"):
    e = type(nombre, (Exception,), {})(texto)
    e.status_code = codigo
    return e


@pytest.mark.parametrize("nombre, codigo, tipo", [
    ("RateLimitError", 429, "limite_de_tasa"), ("APIConnectionError", None, "red"), ("APITimeoutError", None, "red"),
    ("AuthenticationError", 401, "autenticacion"), ("PermissionDeniedError", 403, "autenticacion"), ("BadRequestError", 400, "solicitud"),
    ("InternalServerError", 500, "servidor"), ("OverloadedError", 529, "servidor"), ("ExtrañoError", None, "otro"),
])
def test_cada_error_del_proveedor_se_clasifica(nombre, codigo, tipo):
    with pytest.raises(ErrorLLM) as e:
        cliente(SDKFalso(error=_exc(nombre, codigo))).generar("s", "u", HERR)
    assert e.value.tipo == tipo and e.value.mensaje


def test_el_error_por_temperature_da_la_pista_de_la_config():
    tipo, msg = clasificar_error(_exc("BadRequestError", 400, "`temperature` may only be set to 1 for this model"))
    assert tipo == "solicitud" and "llm.temperatura: null" in msg


def test_los_mensajes_de_error_no_filtran_claves():
    clave = "sk-" + "ant-" + "SECRETOSECRETO123"
    tipo, msg = clasificar_error(_exc("Exception", None, f"fallo con {clave}"))
    assert clave not in msg
    with pytest.raises(ErrorLLM) as e:
        cliente(SDKFalso(error=_exc("APIConnectionError", None, f"x-api-key: {clave}"))).generar("s", "u", HERR)
    assert clave not in e.value.mensaje


def test_sin_clave_falla_con_instrucciones_no_con_un_traceback():
    with pytest.raises(ErrorLLM, match="ANTHROPIC_API_KEY") as e:
        ClienteAnthropic(AJUSTES, api_key=None)
    assert e.value.tipo == "autenticacion"

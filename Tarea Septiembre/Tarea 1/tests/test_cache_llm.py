"""Caché de respuestas del LLM para la evaluación: mismas entradas -> misma respuesta sin llamar; cualquier cambio -> llamada nueva."""
from datetime import datetime, timedelta, timezone

import pytest

from fakes import LLMFalso
from rag_engine.llm.base import EsquemaSalida, ErrorLLM
from rag_engine.llm.cache import ClienteConCache

ESQ = EsquemaSalida("responder_con_citas", "desc", {"respuesta": "r", "citas": "c", "contexto_suficiente": "s"})


def cache(tmp_path, llm, **kw):
    args = dict(proveedor="gemini", modelo="gemini-2.5-flash-lite", temperatura=0.0, max_tokens=1024)
    return ClienteConCache(lambda: llm, tmp_path / "c", **{**args, **kw})


def test_la_segunda_llamada_identica_sale_de_la_cache_sin_llamar_al_proveedor(tmp_path):
    llm = LLMFalso(respuesta="R1")
    c = cache(tmp_path, llm)
    a, b = c.generar("sis", "usu", ESQ), c.generar("sis", "usu", ESQ)
    assert len(llm.llamadas) == 1 and (c.aciertos, c.fallos) == (1, 1)
    assert a.desde_cache is False and b.desde_cache is True
    assert (b.respuesta, b.citas, b.contexto_suficiente, b.tokens_in, b.tokens_out, b.modelo) == (a.respuesta, a.citas, a.contexto_suficiente, a.tokens_in, a.tokens_out, a.modelo)


def test_la_cache_sobrevive_a_un_proceso_nuevo(tmp_path):
    llm1, llm2 = LLMFalso(respuesta="R1"), LLMFalso(respuesta="OTRA")
    cache(tmp_path, llm1).generar("sis", "usu", ESQ)
    r = cache(tmp_path, llm2).generar("sis", "usu", ESQ)             # instancia nueva sobre el mismo directorio
    assert r.respuesta == "R1" and r.desde_cache and llm2.llamadas == []


@pytest.mark.parametrize("cambio", [
    dict(sistema="otro sistema"), dict(usuario="otra pregunta o fragmentos"), dict(modelo="gemini-3.5-flash-lite"), dict(temperatura=0.5),
    dict(max_tokens=2048), dict(proveedor="anthropic"),
])
def test_cualquier_cambio_en_lo_que_determina_la_respuesta_invalida_la_cache(tmp_path, cambio):
    llm = LLMFalso()
    base = dict(sistema="sis", usuario="usu")
    cache(tmp_path, llm).generar(base["sistema"], base["usuario"], ESQ)
    kw_cliente = {k: v for k, v in cambio.items() if k in ("modelo", "temperatura", "max_tokens", "proveedor")}
    kw_gen = {**base, **{k: v for k, v in cambio.items() if k in ("sistema", "usuario")}}
    r = cache(tmp_path, llm, **kw_cliente).generar(kw_gen["sistema"], kw_gen["usuario"], ESQ)
    assert r.desde_cache is False and len(llm.llamadas) == 2


def test_un_esquema_distinto_invalida_la_cache(tmp_path):
    llm = LLMFalso()
    c = cache(tmp_path, llm)
    c.generar("s", "u", ESQ)
    r = c.generar("s", "u", EsquemaSalida("responder_con_citas", "desc", {"respuesta": "OTRA descripción", "citas": "c", "contexto_suficiente": "s"}))
    assert r.desde_cache is False


def test_un_error_nunca_se_cachea(tmp_path):
    fallo = LLMFalso(error=ErrorLLM("cuota_agotada", "sin cuota"))
    c = cache(tmp_path, fallo)
    with pytest.raises(ErrorLLM):
        c.generar("s", "u", ESQ)
    assert not (tmp_path / "c").exists() or list((tmp_path / "c").glob("*.json")) == []
    ok = cache(tmp_path, LLMFalso(respuesta="ya sí"))
    assert ok.generar("s", "u", ESQ).respuesta == "ya sí"            # el fallo anterior no dejó nada


def test_con_todo_en_cache_no_se_crea_el_cliente_real_asi_que_no_hace_falta_clave(tmp_path):
    cache(tmp_path, LLMFalso()).generar("s", "u", ESQ)
    creado = []

    def fabrica():
        creado.append(1)
        raise ErrorLLM("autenticacion", "falta la clave", solicitud_enviada=False)

    c = ClienteConCache(fabrica, tmp_path / "c", "gemini", "gemini-2.5-flash-lite", 0.0, 1024)
    assert c.generar("s", "u", ESQ).desde_cache and creado == []
    with pytest.raises(ErrorLLM):
        c.generar("otra", "u", ESQ)                                     # solo un fallo de caché necesita el cliente (y la clave)
    assert creado == [1]


def test_un_archivo_de_cache_danado_se_trata_como_fallo_y_se_reescribe(tmp_path):
    llm = LLMFalso(respuesta="R1")
    c = cache(tmp_path, llm)
    c.generar("s", "u", ESQ)
    archivo = next((tmp_path / "c").glob("*.json"))
    archivo.write_text("{ esto no es json", encoding="utf-8")
    r = c.generar("s", "u", ESQ)
    assert r.desde_cache is False and r.respuesta == "R1" and len(llm.llamadas) == 2
    assert cache(tmp_path, LLMFalso()).generar("s", "u", ESQ).desde_cache is True     # ya quedó reparado


def test_el_momento_conserva_su_zona_horaria(tmp_path):
    lima = timezone(timedelta(hours=-5))
    llm = LLMFalso(momento=datetime(2026, 9, 21, 3, 0, tzinfo=lima))
    c = cache(tmp_path, llm)
    c.generar("s", "u", ESQ)
    m = c.generar("s", "u", ESQ).momento
    assert m == datetime(2026, 9, 21, 3, 0, tzinfo=lima) and m.utcoffset() == timedelta(hours=-5)


def test_las_respuestas_de_cache_no_cuentan_intentos_de_red(tmp_path):
    c = cache(tmp_path, LLMFalso(intentos=3))
    c.generar("s", "u", ESQ)
    assert c.generar("s", "u", ESQ).intentos == 0

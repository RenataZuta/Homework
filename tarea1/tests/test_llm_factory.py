"""Fábrica de clientes de LLM: llm.provider en config.yaml elige el proveedor; la clave viene del entorno."""
import pytest

from fakes import cfg_con
from rag_engine.config import ConfigError, cargar_config
from rag_engine.llm.anthropic_client import ClienteAnthropic
from rag_engine.llm.base import ClienteConPolitica, EsquemaSalida, ErrorLLM
from rag_engine.llm.factory import ajustes_llm, crear_cliente_llm, esquema_salida, politica_desde_config
from rag_engine.llm.gemini_client import ClienteGemini

BASE = cargar_config(cargar_env=False)


def test_el_proveedor_por_defecto_es_gemini_gratuito_con_flash_lite():
    aj = ajustes_llm(BASE)
    assert (aj["provider"], aj["nivel"], aj["modelo"], aj["env_clave"]) == ("gemini", "gratuito", "gemini-2.5-flash-lite", "GEMINI_API_KEY")
    assert aj["max_tokens"] >= 1 and "limites" not in aj and "proveedores" not in aj


def test_con_gemini_se_crea_el_cliente_de_gemini_con_throttle_y_reintentos(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AI" + "za" + "x" * 35)
    c = crear_cliente_llm(BASE)
    assert isinstance(c, ClienteConPolitica) and isinstance(c._cliente, ClienteGemini)
    assert (c.proveedor, c.modelo) == ("gemini", "gemini-2.5-flash-lite")
    assert c.limitador.rpm == BASE.get("llm.limites.rpm") and c.politica.reintentos == BASE.get("llm.limites.reintentos")


def test_cambiar_de_proveedor_es_editar_la_config_y_conserva_el_cliente_de_anthropic(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-" + "ant-" + "x" * 30)
    cfg = cfg_con(BASE, **{"llm.provider": "anthropic", "llm.nivel": "pago"})
    c = crear_cliente_llm(cfg)
    assert isinstance(c._cliente, ClienteAnthropic) and c.proveedor == "anthropic" and c.modelo == "claude-haiku-4-5-20251001"


def test_sin_clave_da_un_error_estructurado_con_instrucciones_y_sin_llamada(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ErrorLLM) as e:
        crear_cliente_llm(BASE)
    assert e.value.tipo == "autenticacion" and e.value.solicitud_enviada is False
    assert "GEMINI_API_KEY" in e.value.mensaje and "aistudio.google.com" in e.value.mensaje and "set_env_key.py" in e.value.mensaje


def test_un_proveedor_desconocido_es_un_error_de_config(monkeypatch):
    with pytest.raises(ConfigError):
        crear_cliente_llm(cfg_con(BASE, **{"llm.provider": "otro"}))


def test_el_esquema_sale_de_los_prompts_de_la_config():
    e = esquema_salida(BASE)
    assert isinstance(e, EsquemaSalida) and e.nombre == BASE.get("prompts.herramienta_nombre")
    assert set(e.json_schema()["properties"]) == {"respuesta", "citas", "contexto_suficiente"} and "\n" not in e.descripcion


def test_la_politica_toma_sus_valores_de_llm_limites():
    lim, pol = politica_desde_config(cfg_con(BASE, **{"llm.limites": {"rpm": 7, "reintentos": 2, "espera_inicial_s": 1, "factor_espera": 3, "espera_max_s": 9, "jitter": 0.1}}))
    assert lim.rpm == 7 and (pol.reintentos, pol.espera_inicial_s, pol.factor, pol.espera_max_s, pol.jitter) == (2, 1, 3, 9, 0.1)

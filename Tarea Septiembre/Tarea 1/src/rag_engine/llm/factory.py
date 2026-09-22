"""Fábrica de clientes de LLM: ``llm.provider`` en config.yaml elige el proveedor; cambiar de proveedor es editar la config.

Toda petición pasa por ``ClienteConPolitica`` (throttle por RPM + reintentos con backoff). La clave se lee del .env por el nombre que declara
``llm.proveedores.<provider>.env_clave``.
"""
from __future__ import annotations

from rag_engine.config import Config, ConfigError
from rag_engine.limites import Limitador, PoliticaReintentos
from rag_engine.llm.base import ClienteConPolitica, ClienteLLM, EsquemaSalida, ErrorLLM

PROVEEDORES_LLM = ("gemini", "anthropic")


def ajustes_llm(cfg: Config) -> dict:
    """Ajustes comunes de ``llm`` + los del proveedor activo, en un solo diccionario plano (incluye ``provider`` y ``nivel``)."""
    proveedor = cfg.get("llm.provider")
    comunes = {k: v for k, v in cfg.get("llm").items() if k not in ("proveedores", "limites")}
    return {**comunes, **cfg.get(f"llm.proveedores.{proveedor}")}


def esquema_salida(cfg: Config) -> EsquemaSalida:
    return EsquemaSalida(cfg.get("prompts.herramienta_nombre"), " ".join(cfg.get("prompts.herramienta_descripcion").split()), dict(cfg.get("prompts.herramienta_campos")))


def politica_desde_config(cfg: Config) -> tuple[Limitador, PoliticaReintentos]:
    lim = cfg.get("llm.limites")
    return Limitador(lim["rpm"]), PoliticaReintentos(lim["reintentos"], lim["espera_inicial_s"], lim["factor_espera"], lim["espera_max_s"], lim["jitter"])


def crear_cliente_llm(cfg: Config) -> ClienteLLM:
    ajustes = ajustes_llm(cfg)
    proveedor = ajustes["provider"]
    if proveedor not in PROVEEDORES_LLM:
        raise ConfigError(f"llm.provider desconocido: '{proveedor}'. Opciones: {', '.join(PROVEEDORES_LLM)}.")
    try:
        clave = cfg.requerir_env(ajustes["env_clave"], para="generar respuestas")
    except ConfigError as exc:
        ayuda = (f" Consigue la clave GRATIS en Google AI Studio (https://aistudio.google.com/apikey) y guárdala sin mostrarla con: "
                 f"python scripts/set_env_key.py {ajustes['env_clave']}") if proveedor == "gemini" else ""
        raise ErrorLLM("autenticacion", str(exc) + ayuda, solicitud_enviada=False) from exc
    if proveedor == "gemini":
        from rag_engine.llm.gemini_client import ClienteGemini
        base: ClienteLLM = ClienteGemini(ajustes, api_key=clave)
    else:
        from rag_engine.llm.anthropic_client import ClienteAnthropic
        base = ClienteAnthropic(ajustes, api_key=clave)
    limitador, politica = politica_desde_config(cfg)
    return ClienteConPolitica(base, limitador, politica)

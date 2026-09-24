"""Generación: reutiliza ``rag_engine.llm.*`` de la Tarea 1 TAL CUAL (clientes, throttle/reintentos, log de
costos y tabla de precios). La única pieza propia de la Tarea 2 es el esquema de salida (``llm_schema.py``,
citas por ``ocid`` en vez de documento/página); todo lo demás —incluida la tabla de precios, ver
``paths.pricing`` en config.yaml, que APUNTA al ``pricing.yaml`` de la Tarea 1— es el mismo código y los
mismos datos, para que el costo de una consulta se calcule exactamente igual en ambas tareas.
"""
from __future__ import annotations

from radar_engine.bootstrap_t1 import asegurar_import_tarea1
from radar_engine.config import Config

asegurar_import_tarea1()

from rag_engine.llm.base import ClienteLLM, ErrorLLM, RespuestaLLM, validar_salida  # noqa: E402
from rag_engine.llm.cost_log import leer_registros, registrar_llamada  # noqa: E402
from rag_engine.llm.factory import ajustes_llm, crear_cliente_llm  # noqa: E402
from rag_engine.llm.pricing import ErrorPrecio, TablaPrecios, cargar_tabla  # noqa: E402

__all__ = ["ClienteLLM", "ErrorLLM", "RespuestaLLM", "validar_salida", "leer_registros", "registrar_llamada",
           "ajustes_llm", "crear_cliente_llm", "ErrorPrecio", "TablaPrecios", "cargar_tabla_precios"]


def cargar_tabla_precios(cfg: Config) -> TablaPrecios:
    return cargar_tabla(cfg.ruta("pricing"), cfg.get("llm.provider"))

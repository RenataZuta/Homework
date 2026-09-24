"""Esquema de salida del LLM para el RAG de procesos: {respuesta, citas: [{ocid}], contexto_suficiente}.

``rag_engine.llm.base.EsquemaSalida`` (Tarea 1) exige citas ``{documento, pagina}``: no sirve aquí, donde se
cita por ``ocid``. Los clientes de LLM de la Tarea 1 (``ClienteAnthropic.generar`` / ``ClienteGemini.generar``)
NO comprueban el tipo del esquema con ``isinstance``: solo llaman a ``esquema.nombre``, ``esquema.descripcion``
y ``esquema.json_schema()`` (duck typing). Por eso ``EsquemaSalidaOCID`` no hereda de ``EsquemaSalida``: le
basta con tener esos tres atributos para que los mismos clientes la acepten sin ningún cambio.
``rag_engine.llm.base.validar_salida`` (que sí se reutiliza) solo exige que "citas" sea una lista de objetos;
no valida la forma de cada cita, así que tampoco hace falta tocarlo.
"""
from __future__ import annotations

from dataclasses import dataclass

from radar_engine.config import Config


@dataclass(frozen=True)
class EsquemaSalidaOCID:
    nombre: str
    descripcion: str
    campos: dict

    def json_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "respuesta": {"type": "string", "description": self.campos["respuesta"]},
                "citas": {"type": "array", "description": self.campos["citas"],
                          "items": {"type": "object", "properties": {"ocid": {"type": "string"}}, "required": ["ocid"]}},
                "contexto_suficiente": {"type": "boolean", "description": self.campos["contexto_suficiente"]},
            },
            "required": ["respuesta", "citas", "contexto_suficiente"],
        }


def esquema_salida(cfg: Config) -> EsquemaSalidaOCID:
    return EsquemaSalidaOCID(cfg.get("prompts.herramienta_nombre"), " ".join(cfg.get("prompts.herramienta_descripcion").split()),
                             dict(cfg.get("prompts.herramienta_campos")))


def etiqueta_proceso(cfg: Config, meta: dict) -> str:
    monto = f"{meta['monto_pen']:,.0f}" if meta.get("monto_conocido") else "reservado/no publicado"
    fecha = meta.get("fecha") or "sin fecha"
    return cfg.get("prompts.etiqueta_proceso").format(ocid=meta["ocid"], comprador=meta.get("comprador") or "—",
                                                       departamento=meta.get("departamento") or "—", monto=monto,
                                                       fecha=fecha, categoria=meta.get("categoria") or "—")

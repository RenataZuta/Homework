"""Interfaz común de los clientes de LLM (uno por proveedor) y sus tipos compartidos.

Contrato: ``generar(sistema, usuario, esquema)`` devuelve una ``RespuestaLLM`` ESTRUCTURADA {respuesta, citas[], contexto_suficiente} o
lanza ``ErrorLLM``; jamás devuelve un error disfrazado de respuesta. La abstención por falta de contexto es un CAMPO, no algo que se
deduzca leyendo el texto. Cada proveedor traduce ``EsquemaSalida`` a su mecanismo (Anthropic: tool use forzado; Gemini: JSON con esquema).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from rag_engine.limites import ErrorProveedor, Limitador, PoliticaReintentos


class ErrorLLM(ErrorProveedor):
    """Fallo al generar. `tipo` clasifica la causa (autenticacion, limite_de_tasa, cuota_agotada, red, servidor, solicitud, respuesta_malformada,
    respuesta_bloqueada, otro) para que la interfaz pueda mostrar un mensaje adecuado."""


@dataclass
class RespuestaLLM:
    respuesta: str
    citas: list[dict]
    contexto_suficiente: bool
    tokens_in: int
    tokens_out: int
    latencia_ms: float
    modelo: str
    momento: datetime = field(default_factory=lambda: datetime.now().astimezone())     # cuándo se hizo la llamada (para el precio por hora)
    proveedor: str = ""
    intentos: int = 1                    # peticiones enviadas (1 = a la primera; más = hubo reintentos por 429/5xx)
    desde_cache: bool = False            # True = respuesta reutilizada de la caché de evaluación: NO fue una llamada al proveedor


@dataclass(frozen=True)
class EsquemaSalida:
    """Forma de la respuesta que se le exige al modelo. Los textos vienen de config.yaml (prompts.herramienta_*)."""
    nombre: str
    descripcion: str
    campos: dict

    def json_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "respuesta": {"type": "string", "description": self.campos["respuesta"]},
                "citas": {"type": "array", "description": self.campos["citas"], "items": {
                    "type": "object", "properties": {"documento": {"type": "string"}, "pagina": {"type": "integer"}}, "required": ["documento", "pagina"]}},
                "contexto_suficiente": {"type": "boolean", "description": self.campos["contexto_suficiente"]},
            },
            "required": ["respuesta", "citas", "contexto_suficiente"],
        }


def validar_salida(datos) -> dict:
    """Comprueba que la salida del modelo cumple el formato; si no, ErrorLLM('respuesta_malformada')."""
    if not isinstance(datos, dict) or not isinstance(datos.get("respuesta"), str) or not isinstance(datos.get("contexto_suficiente"), bool) \
            or not isinstance(datos.get("citas", []), list):
        raise ErrorLLM("respuesta_malformada", "El modelo devolvió una respuesta que no cumple el formato esperado (respuesta, citas, contexto_suficiente).")
    return datos


class ClienteLLM(ABC):
    proveedor: str
    modelo: str

    @abstractmethod
    def generar(self, sistema: str, usuario: str, esquema: EsquemaSalida) -> RespuestaLLM: ...


class ClienteConPolitica(ClienteLLM):
    """Envuelve a cualquier cliente con el throttle por RPM y los reintentos con backoff (ver limites.py)."""

    def __init__(self, cliente: ClienteLLM, limitador: Limitador, politica: PoliticaReintentos):
        self._cliente, self.limitador, self.politica = cliente, limitador, politica
        self.proveedor, self.modelo = cliente.proveedor, cliente.modelo

    def generar(self, sistema: str, usuario: str, esquema: EsquemaSalida) -> RespuestaLLM:
        intentos = 0

        def una_vez() -> RespuestaLLM:
            nonlocal intentos
            intentos += 1
            return self._cliente.generar(sistema, usuario, esquema)

        r = self.politica.ejecutar(una_vez, self.limitador)
        r.intentos = intentos
        return r

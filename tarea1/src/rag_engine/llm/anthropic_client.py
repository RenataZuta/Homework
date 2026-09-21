"""Cliente de Anthropic. Devuelve una respuesta ESTRUCTURADA (tool use forzado) o lanza ErrorLLM; nunca devuelve un error disfrazado de respuesta.

La salida estructurada es {respuesta, citas[], contexto_suficiente}: la abstención por falta de contexto es un CAMPO, no algo que se
deduzca leyendo el texto de la respuesta.
Nota de compatibilidad: según la referencia oficial de la API, los modelos posteriores a Claude Opus 4.6 no admiten ``temperature``
(rechazan con 400 todo valor distinto de 1.0). Por eso solo se envía si ``llm.temperatura`` no es null.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime

from rag_engine.llm.cost_log import sanear


class ErrorLLM(Exception):
    """Fallo al generar. `tipo` clasifica la causa para que la interfaz pueda mostrar un mensaje adecuado."""

    def __init__(self, tipo: str, mensaje: str, solicitud_enviada: bool = True):
        super().__init__(mensaje)
        self.tipo = tipo
        self.mensaje = mensaje
        self.solicitud_enviada = solicitud_enviada      # False si falló ANTES de llamar al proveedor (p. ej. falta la clave): no cuenta como llamada


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


def clasificar_error(exc: Exception) -> tuple[str, str]:
    """(tipo, mensaje seguro) a partir de una excepción del SDK, sin importar el SDK (se reconoce por nombre y código)."""
    nombre, codigo = type(exc).__name__, getattr(exc, "status_code", None)
    texto = sanear(str(exc)) or nombre
    if nombre == "RateLimitError" or codigo == 429:
        return "limite_de_tasa", f"Se alcanzó el límite de peticiones del proveedor. Intenta de nuevo en un momento. ({texto})"
    if nombre in ("APIConnectionError", "APITimeoutError", "DeadlineExceededError") or isinstance(exc, (ConnectionError, TimeoutError)):
        return "red", f"No se pudo conectar con el proveedor del modelo (red o tiempo de espera). ({texto})"
    if nombre in ("AuthenticationError", "PermissionDeniedError") or codigo in (401, 403):
        return "autenticacion", "La clave de API es inválida o no tiene permisos. Revisa ANTHROPIC_API_KEY en tu .env."
    if nombre == "BadRequestError" or codigo == 400:
        pista = " El modelo elegido puede no admitir 'temperature': pon llm.temperatura: null en config.yaml." if "temperature" in texto.lower() else ""
        return "solicitud", f"El proveedor rechazó la solicitud.{pista} ({texto})"
    if nombre in ("OverloadedError", "ServiceUnavailableError", "InternalServerError") or (isinstance(codigo, int) and codigo >= 500):
        return "servidor", f"El proveedor del modelo tiene un problema temporal. ({texto})"
    return "otro", f"Error inesperado al llamar al modelo: {texto}"


class ClienteAnthropic:
    def __init__(self, ajustes: dict, api_key: str | None = None, cliente=None):
        self.ajustes = ajustes
        self.modelo = ajustes["modelo"]
        if cliente is None:
            if not api_key:
                raise ErrorLLM("autenticacion", "Falta ANTHROPIC_API_KEY. Cópiala a tu archivo .env (nunca al repositorio).", solicitud_enviada=False)
            import anthropic
            cliente = anthropic.Anthropic(api_key=api_key, max_retries=ajustes["reintentos"], timeout=float(ajustes["timeout_segundos"]))
        self._c = cliente

    @staticmethod
    def herramienta(nombre: str, descripcion: str, campos: dict[str, str]) -> dict:
        return {"name": nombre, "description": descripcion, "input_schema": {
            "type": "object",
            "properties": {
                "respuesta": {"type": "string", "description": campos["respuesta"]},
                "citas": {"type": "array", "description": campos["citas"], "items": {
                    "type": "object", "properties": {"documento": {"type": "string"}, "pagina": {"type": "integer"}}, "required": ["documento", "pagina"]}},
                "contexto_suficiente": {"type": "boolean", "description": campos["contexto_suficiente"]},
            },
            "required": ["respuesta", "citas", "contexto_suficiente"]}}

    def generar(self, sistema: str, usuario: str, herramienta: dict) -> RespuestaLLM:
        args = {"model": self.modelo, "max_tokens": self.ajustes["max_tokens"], "system": sistema,
                "messages": [{"role": "user", "content": usuario}], "tools": [herramienta],
                "tool_choice": {"type": "tool", "name": herramienta["name"]}}
        if self.ajustes.get("temperatura") is not None:
            args["extra_body"] = {"temperature": self.ajustes["temperatura"]}
        momento = datetime.now().astimezone()
        t0 = time.perf_counter()
        try:
            r = self._c.messages.create(**args)
        except Exception as exc:
            tipo, mensaje = clasificar_error(exc)
            raise ErrorLLM(tipo, mensaje) from exc
        latencia = (time.perf_counter() - t0) * 1000
        bloque = next((b for b in (getattr(r, "content", None) or []) if getattr(b, "type", "") == "tool_use" and getattr(b, "name", "") == herramienta["name"]), None)
        datos = getattr(bloque, "input", None)
        if not isinstance(datos, dict) or not isinstance(datos.get("respuesta"), str) or not isinstance(datos.get("contexto_suficiente"), bool) \
                or not isinstance(datos.get("citas", []), list):
            raise ErrorLLM("respuesta_malformada", "El modelo devolvió una respuesta que no cumple el formato esperado (respuesta, citas, contexto_suficiente).")
        uso = getattr(r, "usage", None)
        return RespuestaLLM(respuesta=datos["respuesta"], citas=[c for c in datos.get("citas", []) if isinstance(c, dict)],
                            contexto_suficiente=datos["contexto_suficiente"], tokens_in=int(getattr(uso, "input_tokens", 0) or 0),
                            tokens_out=int(getattr(uso, "output_tokens", 0) or 0), latencia_ms=latencia, modelo=self.modelo, momento=momento)

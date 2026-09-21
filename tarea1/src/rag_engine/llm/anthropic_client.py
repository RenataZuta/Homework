"""Cliente de Anthropic. Devuelve una respuesta ESTRUCTURADA (tool use forzado) o lanza ErrorLLM; nunca devuelve un error disfrazado de respuesta.

La salida estructurada es {respuesta, citas[], contexto_suficiente}: la abstención por falta de contexto es un CAMPO, no algo que se
deduzca leyendo el texto de la respuesta.
Nota de compatibilidad: según la referencia oficial de la API, los modelos posteriores a Claude Opus 4.6 no admiten ``temperature``
(rechazan con 400 todo valor distinto de 1.0). Por eso solo se envía si ``llm.temperatura`` no es null.
"""
from __future__ import annotations

import time
from datetime import datetime

from rag_engine.llm.base import ClienteLLM, EsquemaSalida, ErrorLLM, RespuestaLLM, validar_salida     # ErrorLLM/RespuestaLLM se reexportan aquí
from rag_engine.llm.cost_log import sanear

__all__ = ["ClienteAnthropic", "ErrorLLM", "RespuestaLLM", "clasificar_error"]

ENV_CLAVE = "ANTHROPIC_API_KEY"


def clasificar_error(exc: Exception) -> tuple[str, str]:
    """(tipo, mensaje seguro) a partir de una excepción del SDK, sin importar el SDK (se reconoce por nombre y código)."""
    nombre, codigo = type(exc).__name__, getattr(exc, "status_code", None)
    texto = sanear(str(exc)) or nombre
    if nombre == "RateLimitError" or codigo == 429:
        return "limite_de_tasa", f"Se alcanzó el límite de peticiones del proveedor. Intenta de nuevo en un momento. ({texto})"
    if nombre in ("APIConnectionError", "APITimeoutError", "DeadlineExceededError") or isinstance(exc, (ConnectionError, TimeoutError)):
        return "red", f"No se pudo conectar con el proveedor del modelo (red o tiempo de espera). ({texto})"
    if nombre in ("AuthenticationError", "PermissionDeniedError") or codigo in (401, 403):
        return "autenticacion", f"La clave de API es inválida o no tiene permisos. Revisa {ENV_CLAVE} en tu .env."
    if nombre == "BadRequestError" or codigo == 400:
        pista = " El modelo elegido puede no admitir 'temperature': pon llm.temperatura: null en config.yaml." if "temperature" in texto.lower() else ""
        return "solicitud", f"El proveedor rechazó la solicitud.{pista} ({texto})"
    if nombre in ("OverloadedError", "ServiceUnavailableError", "InternalServerError") or (isinstance(codigo, int) and codigo >= 500):
        return "servidor", f"El proveedor del modelo tiene un problema temporal. ({texto})"
    return "otro", f"Error inesperado al llamar al modelo: {texto}"


class ClienteAnthropic(ClienteLLM):
    """Cliente de Claude (conservado, NO es el proveedor activo: ver llm.provider). Los reintentos y el throttle los aplica ClienteConPolitica,
    por eso el SDK se crea con ``max_retries=0`` (así no se reintenta dos veces)."""

    proveedor = "anthropic"

    def __init__(self, ajustes: dict, api_key: str | None = None, cliente=None):
        self.ajustes = ajustes
        self.modelo = ajustes["modelo"]
        if cliente is None:
            if not api_key:
                raise ErrorLLM("autenticacion", f"Falta {ENV_CLAVE}. Cópiala a tu archivo .env (nunca al repositorio).", solicitud_enviada=False)
            import anthropic
            cliente = anthropic.Anthropic(api_key=api_key, max_retries=0, timeout=float(ajustes["timeout_segundos"]))
        self._c = cliente

    @staticmethod
    def herramienta(esquema: EsquemaSalida) -> dict:
        return {"name": esquema.nombre, "description": esquema.descripcion, "input_schema": esquema.json_schema()}

    def generar(self, sistema: str, usuario: str, esquema: EsquemaSalida) -> RespuestaLLM:
        herramienta = self.herramienta(esquema)
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
        datos = validar_salida(getattr(bloque, "input", None))
        uso = getattr(r, "usage", None)
        return RespuestaLLM(respuesta=datos["respuesta"], citas=[c for c in datos.get("citas", []) if isinstance(c, dict)],
                            contexto_suficiente=datos["contexto_suficiente"], tokens_in=int(getattr(uso, "input_tokens", 0) or 0),
                            tokens_out=int(getattr(uso, "output_tokens", 0) or 0), latencia_ms=latencia, modelo=self.modelo, momento=momento,
                            proveedor=self.proveedor)

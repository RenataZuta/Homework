"""Utilidades comunes de la API REST de Google Gemini (LLM y embeddings): URL base y clasificación de errores HTTP.

Formato de error de Google (según la documentación de la API): cuerpo ``{"error": {"code", "message", "status", "details": [...]}}``.
Los detalles pueden incluir ``retryDelay`` (p. ej. ``"27s"``); se aprovecha si aparece, y si no, se usa el backoff propio. La cuota
DIARIA agotada no se reintenta (esperar segundos no sirve): se reconoce por ``PerDay`` / «per day» / «daily» en el propio aviso de Google.
"""
from __future__ import annotations

import json
import re

from rag_engine.llm.cost_log import sanear

URL_BASE_POR_DEFECTO = "https://generativelanguage.googleapis.com/v1beta"


def _espera_sugerida(cuerpo: dict | None, cabeceras: dict) -> float | None:
    texto = json.dumps((cuerpo or {}).get("error", {}).get("details", []))
    m = re.search(r'"retryDelay"\s*:\s*"([0-9.]+)s"', texto)
    if m:
        return float(m.group(1))
    valor = {k.lower(): v for k, v in (cabeceras or {}).items()}.get("retry-after", "")
    return float(valor) if str(valor).replace(".", "", 1).isdigit() else None


def clasificar_http_google(estado: int, cuerpo: dict | None, cabeceras: dict, env_clave: str = "GEMINI_API_KEY") -> tuple[str, str, float | None]:
    """(tipo, mensaje seguro en español, espera sugerida en segundos) para una respuesta HTTP NO exitosa de Google."""
    error = (cuerpo or {}).get("error") if isinstance(cuerpo, dict) else None
    error = error if isinstance(error, dict) else {}
    aviso = sanear(error.get("message")) or f"HTTP {estado}"
    plano = json.dumps(error).lower().replace(" ", "").replace("_", "")
    espera = _espera_sugerida(cuerpo, cabeceras)
    if estado == 429:
        if "perday" in plano or "daily" in plano:
            return "cuota_agotada", f"Se agotó la cuota DIARIA de la capa gratuita de Google. Vuelve a intentarlo mañana o cambia de modelo. ({aviso})", None
        return "limite_de_tasa", f"Se alcanzó el límite de peticiones por minuto del proveedor. ({aviso})", espera
    if estado in (401, 403) or (estado == 400 and ("apikeynotvalid" in plano or "api_key_invalid" in json.dumps(error).lower())):
        return "autenticacion", f"La clave de API es inválida o no tiene permisos. Revisa {env_clave} en tu .env. ({aviso})", None
    if estado in (400, 404):
        return "solicitud", f"El proveedor rechazó la solicitud (¿modelo o parámetros inválidos?). ({aviso})", None
    if estado in (408, 504):
        return "red", f"El proveedor tardó demasiado en responder. ({aviso})", espera
    if estado >= 500:
        return "servidor", f"El proveedor del modelo tiene un problema temporal. ({aviso})", espera
    return "otro", f"Error inesperado del proveedor (HTTP {estado}). ({aviso})", None

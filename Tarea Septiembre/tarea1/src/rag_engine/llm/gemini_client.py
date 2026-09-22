"""Cliente de Google Gemini (API REST ``generateContent``). Salida estructurada por JSON con esquema; devuelve ``RespuestaLLM`` o lanza ``ErrorLLM``.

Campos usados (documentación oficial de la API, verificada el 2026-09-21): ``systemInstruction``, ``contents``, ``generationConfig``
(``temperature``, ``maxOutputTokens``, ``responseMimeType``, ``responseJsonSchema``/``responseSchema``, ``thinkingConfig.thinkingLevel``/``thinkingBudget``),
respuesta ``candidates[].content.parts[].text`` y ``finishReason``, ``promptFeedback.blockReason``, ``usageMetadata`` (``promptTokenCount``,
``candidatesTokenCount``, ``thoughtsTokenCount``). Los tokens de razonamiento se suman a los de salida (se facturan como salida).
La clave viaja en la cabecera ``x-goog-api-key``, nunca en la URL.
IMPORTANTE: el contrato se implementó contra la documentación; la primera llamada real con tu clave es la que lo confirma.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime

from rag_engine.limites import ErrorProveedor
from rag_engine.llm.base import ClienteLLM, EsquemaSalida, ErrorLLM, RespuestaLLM, validar_salida
from rag_engine.llm.cost_log import sanear
from rag_engine.llm.google import URL_BASE_POR_DEFECTO, clasificar_http_google
from rag_engine.llm.transporte import Transporte, post_json

ENV_CLAVE = "GEMINI_API_KEY"


class ClienteGemini(ClienteLLM):
    proveedor = "gemini"

    def __init__(self, ajustes: dict, api_key: str | None = None, transporte: Transporte = post_json):
        self.ajustes = ajustes
        self.modelo = ajustes["modelo"]
        if not api_key:
            raise ErrorLLM("autenticacion", f"Falta {ENV_CLAVE}. Consíguela gratis en Google AI Studio y guárdala en tu .env "
                           f"(python scripts/set_env_key.py {ENV_CLAVE}); nunca en el repositorio.", solicitud_enviada=False)
        self._clave, self._transporte = api_key, transporte
        self._url = f"{ajustes.get('url_base', URL_BASE_POR_DEFECTO).rstrip('/')}/models/{self.modelo}:generateContent"

    def _cuerpo(self, sistema: str, usuario: str, esquema: EsquemaSalida) -> dict:
        generacion = {"maxOutputTokens": self.ajustes["max_tokens"], "responseMimeType": "application/json",
                      self.ajustes.get("campo_esquema", "responseJsonSchema"): esquema.json_schema()}
        if self.ajustes.get("temperatura") is not None:
            generacion["temperature"] = self.ajustes["temperatura"]
        pensar = {k: v for k, v in (("thinkingLevel", self.ajustes.get("thinking_level")), ("thinkingBudget", self.ajustes.get("thinking_budget"))) if v is not None}
        if pensar:                                         # 3.x usa thinkingLevel; 2.5 usa thinkingBudget
            generacion["thinkingConfig"] = pensar
        return {"systemInstruction": {"parts": [{"text": sistema}]}, "contents": [{"role": "user", "parts": [{"text": usuario}]}],
                "generationConfig": generacion}

    def generar(self, sistema: str, usuario: str, esquema: EsquemaSalida) -> RespuestaLLM:
        momento, t0 = datetime.now().astimezone(), time.perf_counter()
        try:
            estado, datos, cabeceras = self._transporte(self._url, {"x-goog-api-key": self._clave}, self._cuerpo(sistema, usuario, esquema),
                                                        float(self.ajustes["timeout_segundos"]))
        except ErrorProveedor as exc:
            raise ErrorLLM(exc.tipo, exc.mensaje) from exc
        latencia = (time.perf_counter() - t0) * 1000
        if estado != 200:
            tipo, mensaje, espera = clasificar_http_google(estado, datos, cabeceras, ENV_CLAVE)
            raise ErrorLLM(tipo, mensaje, espera_sugerida_s=espera)
        return self._interpretar(datos or {}, latencia, momento)

    def _interpretar(self, datos: dict, latencia: float, momento: datetime) -> RespuestaLLM:
        bloqueo = (datos.get("promptFeedback") or {}).get("blockReason")
        if bloqueo:
            raise ErrorLLM("respuesta_bloqueada", f"Google bloqueó la consulta ({bloqueo}). Reformula la pregunta.")
        candidatos = datos.get("candidates") or []
        candidato = candidatos[0] if candidatos and isinstance(candidatos[0], dict) else {}
        motivo = candidato.get("finishReason")
        if motivo in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII"):
            raise ErrorLLM("respuesta_bloqueada", f"Google detuvo la respuesta por sus filtros ({motivo}). Reformula la pregunta.")
        partes = (candidato.get("content") or {}).get("parts") or []
        texto = "".join(p.get("text", "") for p in partes if isinstance(p, dict) and not p.get("thought"))
        texto = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", texto)                    # tolera un cerco de código si el modelo lo añade
        try:
            salida = validar_salida(json.loads(texto))
        except (ValueError, ErrorLLM) as exc:
            pista = " La respuesta se cortó por llm.max_tokens: súbelo en config.yaml." if motivo == "MAX_TOKENS" else ""
            raise ErrorLLM("respuesta_malformada", "El modelo devolvió una respuesta que no cumple el formato esperado (respuesta, citas, "
                           f"contexto_suficiente).{pista} ({sanear(str(exc), 120)})") from exc
        uso = datos.get("usageMetadata") or {}
        return RespuestaLLM(respuesta=salida["respuesta"], citas=[c for c in salida.get("citas", []) if isinstance(c, dict)],
                            contexto_suficiente=salida["contexto_suficiente"], tokens_in=int(uso.get("promptTokenCount") or 0),
                            tokens_out=int(uso.get("candidatesTokenCount") or 0) + int(uso.get("thoughtsTokenCount") or 0),
                            latencia_ms=latencia, modelo=self.modelo, momento=momento, proveedor=self.proveedor)

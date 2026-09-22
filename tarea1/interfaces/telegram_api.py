"""Cliente mínimo de la Bot API de Telegram: llamadas REST directas (sin ``python-telegram-bot``), reutilizando el transporte ya probado
de ``rag_engine.llm.transporte``. Usan este cliente tanto el polling de desarrollo (Fase 10) como el webhook de producción (Fase 11): así
los mismos ``telegram_handlers`` sirven en los dos modos.

IMPORTANTE: el token NUNCA se registra en ningún log. Vive solo dentro de la URL base de esta clase; los mensajes de error se sanean con
la misma expresión que ya oculta tokens de Telegram en ``llm/cost_log.sanear`` antes de mostrarse o propagarse.
Límites de la Bot API (verificados el 2026-09-21 en la referencia oficial): ``sendMessage`` 1-4096 caracteres, ``callback_data`` 1-64 bytes,
``answerCallbackQuery.text`` 0-200 caracteres, ``secret_token`` 1-256 caracteres de ``[A-Za-z0-9_-]`` en la cabecera
``X-Telegram-Bot-Api-Secret-Token``.
"""
from __future__ import annotations

from rag_engine.limites import ErrorProveedor
from rag_engine.llm.cost_log import sanear
from rag_engine.llm.transporte import Transporte, post_json

URL_BASE = "https://api.telegram.org"
MAX_TEXTO_ENVIADO = 4096
MAX_TEXTO_CALLBACK = 200


class ErrorTelegram(ErrorProveedor):
    """Fallo al llamar a la Bot API. ``tipo``: autenticacion | limite_de_tasa | solicitud | red | servidor | otro."""


def _clasificar(estado: int, datos: dict | None) -> tuple[str, str]:
    descripcion = sanear((datos or {}).get("description")) or f"HTTP {estado}"
    if estado == 429:
        return "limite_de_tasa", descripcion
    if estado in (401, 403):
        return "autenticacion", descripcion
    if estado >= 500:
        return "servidor", descripcion
    return "solicitud", descripcion


class ClienteTelegram:
    def __init__(self, token: str, transporte: Transporte = post_json, timeout_s: float = 25.0, url_base: str = URL_BASE):
        if not token:
            raise ErrorTelegram("autenticacion", "Falta TELEGRAM_BOT_TOKEN.", solicitud_enviada=False)
        self._url = f"{url_base.rstrip('/')}/bot{token}"
        self._transporte, self._timeout = transporte, timeout_s

    def _llamar(self, metodo: str, payload: dict) -> dict:
        try:
            estado, datos, _ = self._transporte(f"{self._url}/{metodo}", {}, payload, self._timeout)
        except ErrorProveedor as exc:
            raise ErrorTelegram(exc.tipo, exc.mensaje, espera_sugerida_s=exc.espera_sugerida_s) from exc
        if estado != 200 or not (datos or {}).get("ok"):
            tipo, mensaje = _clasificar(estado, datos)
            espera = ((datos or {}).get("parameters") or {}).get("retry_after") if isinstance(datos, dict) else None
            raise ErrorTelegram(tipo, mensaje, espera_sugerida_s=espera)
        return datos["result"]

    def enviar_mensaje(self, chat_id: int, texto: str, teclado: dict | None = None) -> dict:
        payload = {"chat_id": chat_id, "text": texto[:MAX_TEXTO_ENVIADO]}
        if teclado is not None:
            payload["reply_markup"] = teclado
        return self._llamar("sendMessage", payload)

    def responder_callback(self, callback_query_id: str, texto: str | None = None) -> dict:
        payload = {"callback_query_id": callback_query_id}
        if texto:
            payload["text"] = texto[:MAX_TEXTO_CALLBACK]
        return self._llamar("answerCallbackQuery", payload)

    def obtener_actualizaciones(self, offset: int | None = None, timeout_s: int = 25) -> list[dict]:
        payload = {"timeout": timeout_s, "allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            payload["offset"] = offset
        return self._llamar("getUpdates", payload)

    def fijar_webhook(self, url: str, secret_token: str, allowed_updates: tuple[str, ...] = ("message", "callback_query")) -> dict:
        return self._llamar("setWebhook", {"url": url, "secret_token": secret_token, "allowed_updates": list(allowed_updates)})

    def borrar_webhook(self) -> dict:
        return self._llamar("deleteWebhook", {})

"""Handlers del bot de Telegram: la ÚNICA lógica del asistente que usan es ``rag_engine.engine.responder`` (el motor no importa Telegram).

Los mismos handlers sirven en los dos modos que pide la Fase 10/11: el polling de desarrollo (``scripts/run_telegram_bot.py``) y el
webhook de producción (``interfaces/api_server.py``, Fase 11) les pasan cada ``update`` de Telegram tal cual llega.
Orden de cada mensaje de texto: (1) lista de autorizados — si no está, mensaje de config y CERO llamadas al motor; (2) comandos
/ayuda, /fuente, /costo — tampoco llaman al motor; (3) límite diario — si se excedió, aviso y CERO llamadas al motor; (4) recién ahí
``responder(pregunta)``. El feedback (👍/👎) llega como ``callback_query`` con el ID de la consulta en ``callback_data``.
"""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from interfaces import bot_store
from interfaces.telegram_api import ClienteTelegram
from rag_engine.config import Config
from rag_engine.engine import ResultadoRAG
from rag_engine.engine import responder as responder_motor

RE_CALLBACK_FEEDBACK = re.compile(r"^fb:(\d+):(1|-1)$")


def reloj_zona(zona: str) -> datetime:
    return datetime.now(ZoneInfo(zona))


def usuarios_permitidos(cfg: Config) -> set[int]:
    """{TELEGRAM_ALLOWED_USER_IDS del .env}, como enteros. Vacío o ausente = nadie autorizado (denegar por defecto). IDs no numéricos se ignoran."""
    bruto = cfg.env("TELEGRAM_ALLOWED_USER_IDS") or ""
    salida = set()
    for pedazo in bruto.split(","):
        pedazo = pedazo.strip()
        if pedazo.lstrip("-").isdigit():
            salida.add(int(pedazo))
    return salida


def texto_ayuda(cfg: Config) -> str:
    return cfg.get("mensajes.bot.ayuda").format(limite=cfg.get("bot.limite_consultas_por_usuario_dia"))


def _fuente_linea(f: dict) -> str:
    marca = "★ " if f.get("citada") else "• "
    texto = " ".join(f["texto"].split())
    if len(texto) > 300:
        texto = texto[:297] + "…"
    return f"{marca}{f['documento']} · p. {f['pagina']} · similitud {f['similitud']:.3f}\n{texto}"


def texto_fuentes(cfg: Config, consulta: dict | None) -> str:
    if consulta is None:
        return cfg.get("mensajes.bot.sin_fuente")
    if not consulta["fuentes"]:
        return "Esa consulta no tuvo fragmentos recuperados."
    cabecera = f"Fuentes de tu última consulta («{consulta['pregunta'][:80]}»):\n\n"
    return cabecera + "\n\n".join(_fuente_linea(f) for f in consulta["fuentes"])


def texto_costo(cfg: Config, ultima: dict | None, dia: dict) -> str:
    if ultima is None:
        return cfg.get("mensajes.bot.sin_costo")
    return (f"Última consulta: USD {ultima['costo_usd_real']:.6f} real / {ultima['costo_usd_referencia']:.6f} de referencia "
            f"({ultima['tokens_in']} tokens de entrada, {ultima['tokens_out']} de salida).\n"
            f"Hoy: {dia['consultas']} consulta(s), USD {dia['costo_real']:.6f} real / {dia['costo_referencia']:.6f} de referencia en total.")


def formatear_respuesta(cfg: Config, r: ResultadoRAG) -> str:
    """Nunca el texto crudo de ``r.error``: los mensajes al usuario final vienen de config.yaml (información normativa, no un panel de depuración)."""
    if r.error:
        return cfg.get("mensajes.error_cuota") if r.error_tipo == "cuota_agotada" else cfg.get("mensajes.error_generico")
    texto = r.respuesta
    if r.advertencias_version:
        texto += "\n\n⚠ " + "\n⚠ ".join(dict.fromkeys(r.advertencias_version))
    return texto


def teclado_feedback(consulta_id: int) -> dict:
    return {"inline_keyboard": [[{"text": "👍", "callback_data": f"fb:{consulta_id}:1"}, {"text": "👎", "callback_data": f"fb:{consulta_id}:-1"}]]}


def _responder_pregunta(cfg, conn, cliente: ClienteTelegram, chat_id: int, user_id: int, pregunta: str, responder_fn, ahora: datetime) -> None:
    limite = cfg.get("bot.limite_consultas_por_usuario_dia")
    if bot_store.consultas_de_hoy(conn, user_id, ahora) >= limite:
        cliente.enviar_mensaje(chat_id, cfg.get("mensajes.bot.limite_excedido").format(limite=limite))
        return
    r = responder_fn(pregunta)
    consulta_id = bot_store.registrar_consulta(conn, user_id, pregunta, r, ahora)
    teclado = teclado_feedback(consulta_id) if r.error is None else None            # no se pide opinión sobre un error del servicio
    cliente.enviar_mensaje(chat_id, formatear_respuesta(cfg, r), teclado=teclado)


def _procesar_comando(cfg, conn, cliente: ClienteTelegram, chat_id: int, user_id: int, comando: str, ahora: datetime) -> bool:
    """True si `comando` era uno reconocido (y ya se atendió); False si el texto debe tratarse como una pregunta."""
    if comando == "/ayuda":
        cliente.enviar_mensaje(chat_id, texto_ayuda(cfg))
    elif comando == "/fuente":
        cliente.enviar_mensaje(chat_id, texto_fuentes(cfg, bot_store.ultima_consulta(conn, user_id)))
    elif comando == "/costo":
        cliente.enviar_mensaje(chat_id, texto_costo(cfg, bot_store.ultima_consulta(conn, user_id), bot_store.resumen_dia(conn, user_id, ahora)))
    else:
        return False
    return True


def procesar_mensaje(cfg: Config, conn, cliente: ClienteTelegram, mensaje: dict, permitidos: set[int], *, responder_fn=responder_motor,
                     reloj=reloj_zona) -> None:
    user_id, chat_id, texto = mensaje.get("from", {}).get("id"), mensaje.get("chat", {}).get("id"), (mensaje.get("text") or "").strip()
    if user_id is None or chat_id is None or not texto:
        return                                                                       # nada que responder (foto, sticker, mensaje vacío…)
    if user_id not in permitidos:
        cliente.enviar_mensaje(chat_id, cfg.get("mensajes.bot.no_autorizado"))
        return
    ahora = reloj(cfg.get("bot.zona_horaria_limite"))
    comando = texto.split()[0].lower()
    if _procesar_comando(cfg, conn, cliente, chat_id, user_id, comando, ahora):
        return
    _responder_pregunta(cfg, conn, cliente, chat_id, user_id, texto, responder_fn, ahora)


def procesar_callback(cfg: Config, conn, cliente: ClienteTelegram, callback_query: dict, permitidos: set[int], *, reloj=reloj_zona) -> None:
    callback_id, user_id = callback_query.get("id"), callback_query.get("from", {}).get("id")
    coincide = RE_CALLBACK_FEEDBACK.match(callback_query.get("data") or "")
    if callback_id is None:
        return
    if user_id not in permitidos or not coincide:
        cliente.responder_callback(callback_id)                                      # se reconoce el toque, sin dar detalles
        return
    consulta_id, valor = int(coincide.group(1)), int(coincide.group(2))
    consulta = bot_store.consulta_por_id(conn, consulta_id)
    if consulta is None or consulta["user_id"] != user_id:                           # no se registra feedback ajeno o inexistente
        cliente.responder_callback(callback_id)
        return
    bot_store.registrar_feedback(conn, consulta_id, user_id, valor, reloj(cfg.get("bot.zona_horaria_limite")))
    cliente.responder_callback(callback_id, texto=cfg.get("mensajes.bot.feedback_gracias"))


def procesar_update(update: dict, cfg: Config, conn, cliente: ClienteTelegram, permitidos: set[int], *, responder_fn=responder_motor,
                    reloj=reloj_zona) -> None:
    """Punto de entrada único: lo llaman tanto el polling (Fase 10) como el webhook (Fase 11) con el mismo ``update`` de Telegram."""
    if "callback_query" in update:
        procesar_callback(cfg, conn, cliente, update["callback_query"], permitidos, reloj=reloj)
    elif "message" in update:
        procesar_mensaje(cfg, conn, cliente, update["message"], permitidos, responder_fn=responder_fn, reloj=reloj)

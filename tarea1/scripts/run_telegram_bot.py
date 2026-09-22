#!/usr/bin/env python3
"""run_telegram_bot.py — bot de Telegram en modo POLLING, para desarrollo local (Fase 10).

Usa los mismos handlers que el webhook de producción (Fase 11, interfaces/api_server.py): ``interfaces.telegram_handlers.procesar_update``.
Requiere TELEGRAM_BOT_TOKEN y TELEGRAM_ALLOWED_USER_IDS en tu .env (nunca se muestran ni se registran en ningún log).
Uso (desde tarea1/):  python scripts/run_telegram_bot.py
Ctrl+C para detenerlo. El offset de ``getUpdates`` se guarda en memoria: al reiniciar puede reprocesar el último update si el proceso
murió justo después de recibirlo y antes de contestarlo (en la práctica, uno o dos mensajes duplicados como mucho).
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from interfaces import bot_store, telegram_handlers  # noqa: E402
from interfaces.telegram_api import ClienteTelegram, ErrorTelegram  # noqa: E402
from rag_engine.config import cargar_config  # noqa: E402
from rag_engine.limites import PoliticaReintentos  # noqa: E402


def main() -> int:
    cfg = cargar_config()
    token = cfg.requerir_env("TELEGRAM_BOT_TOKEN", para="el bot de Telegram")
    permitidos = telegram_handlers.usuarios_permitidos(cfg)
    if not permitidos:
        print("AVISO: TELEGRAM_ALLOWED_USER_IDS está vacío: nadie podrá usar el bot. Complétalo en tu .env.", file=sys.stderr)
    cliente = ClienteTelegram(token)
    conn = bot_store.abrir_db(cfg.ruta("bot_db"))
    politica = PoliticaReintentos(reintentos=5, espera_inicial_s=2, factor=2, espera_max_s=30, jitter=0.25)
    print(f"Bot en modo polling. Usuarios autorizados: {len(permitidos)}. Ctrl+C para detener.")
    offset = None
    while True:
        try:
            actualizaciones = politica.ejecutar(lambda: cliente.obtener_actualizaciones(offset, timeout_s=25))
        except ErrorTelegram as exc:
            print(f"Error de Telegram ({exc.tipo}), reintentando: {exc.mensaje}", file=sys.stderr)
            time.sleep(5)
            continue
        except KeyboardInterrupt:
            print("\nDetenido.")
            return 0
        for update in actualizaciones:
            offset = update["update_id"] + 1
            try:
                telegram_handlers.procesar_update(update, cfg, conn, cliente, permitidos)
            except ErrorTelegram as exc:
                print(f"No se pudo responder un mensaje ({exc.tipo}): {exc.mensaje}", file=sys.stderr)
            except Exception as exc:                     # un update raro no debe tumbar el bot
                print(f"Error inesperado procesando un update: {type(exc).__name__}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())

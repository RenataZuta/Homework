#!/usr/bin/env python3
"""set_webhook.py — registra (o borra) el webhook de Telegram, apuntando al Worker de Cloudflare (Fase 11).

Uso (desde tarea1/):
    python scripts/set_webhook.py https://tu-worker.tu-usuario.workers.dev
    python scripts/set_webhook.py --borrar          # vuelve a poder usarse por polling (scripts/run_telegram_bot.py)

Requiere TELEGRAM_BOT_TOKEN y TELEGRAM_WEBHOOK_SECRET en tu .env (nunca se muestran). Telegram enviará ese secreto en la
cabecera ``X-Telegram-Bot-Api-Secret-Token`` de cada petición al Worker; el Worker lo valida antes de reenviar nada al backend.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from interfaces.telegram_api import ClienteTelegram, ErrorTelegram  # noqa: E402
from rag_engine.config import cargar_config  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("url", nargs="?", help="URL pública del Worker de Cloudflare (p. ej. https://xxx.workers.dev)")
    ap.add_argument("--borrar", action="store_true", help="elimina el webhook")
    args = ap.parse_args(argv)
    if not args.borrar and not args.url:
        print("Falta la URL del Worker. Uso: python scripts/set_webhook.py https://tu-worker.workers.dev", file=sys.stderr)
        return 2
    cfg = cargar_config()
    cliente = ClienteTelegram(cfg.requerir_env("TELEGRAM_BOT_TOKEN", para="registrar el webhook"))
    try:
        if args.borrar:
            cliente.borrar_webhook()
            print("Webhook eliminado; el bot vuelve a poder usarse por polling (scripts/run_telegram_bot.py).")
            return 0
        secreto = cfg.requerir_env("TELEGRAM_WEBHOOK_SECRET", para="proteger el webhook")
        cliente.fijar_webhook(args.url, secreto)
        print(f"Webhook registrado: {args.url}")
        return 0
    except ErrorTelegram as exc:
        print(f"ERROR ({exc.tipo}): {exc.mensaje}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""
Lichess API - Parte B: Automatización de torneos
====================================================
Se conecta a la API de torneos de Lichess (autenticada), define un
calendario semanal de torneos tipo Arena, calcula automáticamente
la fecha/hora de inicio de cada uno según el día de la semana actual,
omite los que ya hayan pasado, y los crea a través de la API.

Incluye un modo `dry-run` (simulación, activado por defecto) que no
realiza ninguna petición real: solo muestra qué se crearía.

Uso:
    # Simulación (no crea nada, solo imprime lo que haría):
    python part_b_tournament_automation.py

    # Ejecución real (crea los torneos en Lichess):
    python part_b_tournament_automation.py --live
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# --------------------------------------------------------------------------
# Configuración general
# --------------------------------------------------------------------------

LICHESS_API_BASE = "https://lichess.org/api"
REQUEST_TIMEOUT = 15
SCHEDULE_FILE = "schedule.json"  # archivo externo opcional para editar el calendario sin tocar el código

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# weekday: 0 = lunes ... 6 = domingo (igual que datetime.weekday())
DEFAULT_SCHEDULE = [
    {
        "name": "Blitz de los Lunes",
        "weekday": 0,
        "time": "18:00",
        "clock_time": 3,
        "clock_increment": 2,
        "minutes": 60,
        "variant": "standard",
        "rated": True,
    },
    {
        "name": "Rapid de los Miércoles",
        "weekday": 2,
        "time": "19:00",
        "clock_time": 10,
        "clock_increment": 0,
        "minutes": 90,
        "variant": "standard",
        "rated": True,
    },
    {
        "name": "Chess960 de los Viernes",
        "weekday": 4,
        "time": "20:00",
        "clock_time": 5,
        "clock_increment": 3,
        "minutes": 60,
        "variant": "chess960",
        "rated": True,
    },
]


# --------------------------------------------------------------------------
# 1. Carga del calendario semanal (configurable)
# --------------------------------------------------------------------------

def load_schedule(path: str = SCHEDULE_FILE) -> list[dict]:
    """
    Carga el calendario semanal desde un archivo JSON externo si existe
    (permite editar los torneos sin modificar el código). Si no existe,
    usa el calendario por defecto definido en DEFAULT_SCHEDULE.
    """
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                schedule = json.load(f)
            logger.info("Calendario cargado desde '%s' (%s torneos).", path, len(schedule))
            return schedule
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("No se pudo leer '%s' (%s). Se usará el calendario por defecto.", path, exc)

    logger.info("Usando calendario por defecto (%s torneos).", len(DEFAULT_SCHEDULE))
    return DEFAULT_SCHEDULE


# --------------------------------------------------------------------------
# 2. Cálculo de fecha/hora de inicio para cada torneo
# --------------------------------------------------------------------------

def compute_start_datetime(weekday: int, time_str: str, reference: Optional[datetime] = None) -> datetime:
    """
    Calcula la fecha/hora (UTC) correspondiente al `weekday` (0=lunes..6=domingo)
    y `time_str` ("HH:MM") dentro de la semana actual, tomando como referencia
    `reference` (por defecto, el momento actual).
    """
    reference = reference or datetime.now(timezone.utc)
    hour, minute = map(int, time_str.split(":"))

    monday = (reference - timedelta(days=reference.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return monday + timedelta(days=weekday, hours=hour, minutes=minute)


# --------------------------------------------------------------------------
# 3. Creación de un torneo vía API (con soporte dry-run)
# --------------------------------------------------------------------------

def create_tournament(entry: dict, start_time: datetime, token: Optional[str], dry_run: bool = True) -> Optional[dict]:
    """
    Crea un torneo Arena en Lichess a partir de un `entry` del calendario.
    Si `dry_run` es True, no se envía ninguna petición: solo se registra
    en el log el payload que se habría enviado.
    """
    payload = {
        "name": entry["name"],
        "clockTime": entry["clock_time"],
        "clockIncrement": entry["clock_increment"],
        "minutes": entry["minutes"],
        "startDate": int(start_time.timestamp() * 1000),  # epoch en milisegundos
        "variant": entry.get("variant", "standard"),
        "rated": str(entry.get("rated", True)).lower(),
    }

    if dry_run:
        logger.info("[DRY-RUN] Se crearía '%s' el %s (UTC) | payload=%s",
                    entry["name"], start_time.isoformat(), payload)
        return {"dry_run": True, "name": entry["name"], "start": start_time.isoformat()}

    if not token:
        logger.error("Falta LICHESS_TOKEN: no se puede crear '%s' sin autenticación.", entry["name"])
        return None

    headers = {"Authorization": f"Bearer {token}"}
    url = f"{LICHESS_API_BASE}/tournament"

    try:
        response = requests.post(url, data=payload, headers=headers, timeout=REQUEST_TIMEOUT)

        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 60))
            logger.warning("Límite de la API alcanzado (429). Esperando %s segundos y reintentando...", retry_after)
            time.sleep(retry_after)
            response = requests.post(url, data=payload, headers=headers, timeout=REQUEST_TIMEOUT)

        response.raise_for_status()
        result = response.json()
        logger.info("Torneo creado: '%s' (id=%s)", entry["name"], result.get("id"))
        return result

    except requests.exceptions.HTTPError as exc:
        logger.error("Error HTTP al crear '%s': %s | respuesta: %s", entry["name"], exc, response.text[:300])
        return None
    except requests.exceptions.RequestException as exc:
        # Se captura el error puntual de ESTE torneo sin detener la ejecución de los demás
        logger.error("Error de conexión al crear '%s': %s", entry["name"], exc)
        return None


# --------------------------------------------------------------------------
# 4. Orquestación: recorre el calendario, omite lo que ya pasó, crea el resto
# --------------------------------------------------------------------------

def run_weekly_schedule(schedule: list[dict], token: Optional[str], dry_run: bool = True) -> list[dict]:
    """
    Recorre el calendario semanal completo. Para cada torneo:
      - calcula su fecha/hora de inicio en la semana actual,
      - lo omite si esa fecha/hora ya pasó,
      - intenta crearlo (o simularlo, en dry-run),
      - continúa con el resto aunque uno falle (no detiene la ejecución).
    """
    now = datetime.now(timezone.utc)
    created, skipped, failed = [], [], []

    for entry in schedule:
        try:
            start_time = compute_start_datetime(entry["weekday"], entry["time"], reference=now)
        except (KeyError, ValueError) as exc:
            logger.error("Entrada de calendario inválida (%s): %s", entry, exc)
            failed.append(entry)
            continue

        if start_time < now:
            logger.info("Se omite '%s': su horario (%s UTC) ya pasó.", entry["name"], start_time.isoformat())
            skipped.append(entry)
            continue

        result = create_tournament(entry, start_time, token, dry_run=dry_run)
        if result:
            created.append(result)
        else:
            failed.append(entry)

        time.sleep(1)  # pequeña pausa para no saturar la API

    logger.info("Resumen: %s creados, %s omitidos (ya pasaron), %s fallidos.",
                len(created), len(skipped), len(failed))
    return created


# --------------------------------------------------------------------------
# 5. Punto de entrada
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Lichess API - Automatización de torneos")
    parser.add_argument("--live", action="store_true",
                         help="Desactiva el modo simulación y crea los torneos de verdad (por defecto: dry-run)")
    parser.add_argument("--schedule-file", default=SCHEDULE_FILE,
                         help="Ruta a un archivo JSON externo con el calendario semanal")
    args = parser.parse_args()

    dry_run = not args.live
    token = os.getenv("LICHESS_TOKEN")

    if not dry_run and not token:
        logger.error("La variable de entorno LICHESS_TOKEN es obligatoria para crear torneos reales (--live).")
        sys.exit(1)

    schedule = load_schedule(args.schedule_file)
    run_weekly_schedule(schedule, token, dry_run=dry_run)


if __name__ == "__main__":
    main()

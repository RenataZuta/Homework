"""Utilidades compartidas por todos los scripts de la Tarea 2.

- load_config(): lee config.yaml (la ÚNICA fuente de parámetros).
- path(): convierte una ruta relativa del config en absoluta respecto a la carpeta Tarea 2/.
- log_event(): añade una línea JSON a un archivo de log (formato JSONL: fácil de leer con pandas).
- get_logger(): logger de texto que escribe a consola y a logs/<nombre>.log.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent  # carpeta "Tarea 2/"

# La consola de Windows usa cp1252 por defecto y muestra "JUN�N" aunque el dato esté bien en UTF-8.
# Forzamos UTF-8 en la salida para no confundir un problema de pantalla con un problema de datos.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def path(relative: str) -> Path:
    p = ROOT / relative
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def log_event(log_file: str, **fields) -> None:
    """Añade una línea JSON (con marca de tiempo) al log indicado."""
    record = {"timestamp": now_iso(), **fields}
    with open(path(log_file), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def get_logger(name: str) -> logging.Logger:
    cfg = load_config()
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    file = logging.FileHandler(path(f"{cfg['paths']['logs']}/{name}.log"), encoding="utf-8")
    file.setFormatter(fmt)
    logger.addHandler(console)
    logger.addHandler(file)
    return logger

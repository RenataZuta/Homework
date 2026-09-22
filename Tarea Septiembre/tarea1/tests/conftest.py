"""Carga tarea1/.env (si existe) para que las pruebas que usan Tesseract lo encuentren en local.
En CI no hay .env y esas pruebas se omiten."""
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

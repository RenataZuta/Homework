"""Configuración centralizada del bot. Todo lo que puede cambiar entre
ejecuciones (URLs, rutas, tiempos de espera) se lee de variables de entorno
o de un archivo .env, nunca queda escrito a fuego en el código."""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_DIR = Path(__file__).resolve().parent.parent

FORM_URL = os.getenv("FORM_URL", "https://the-paul2002.github.io/Proyecto-IA-/Homework1/")

SHEET_ID = os.getenv("SHEET_ID", "1EjaoSJKdzdUBNF3XJZuTlxA21D-0vy0wkGaMR8wHVgs")
SHEET_CSV_URL = os.getenv(
    "SHEET_CSV_URL",
    f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=0",
)

# Por defecto se lee directamente de Google Sheets (siempre actualizado).
# Para trabajar sin internet, apuntar DATA_SOURCE a data/empleados.csv (copia local).
LOCAL_DATA_PATH = BASE_DIR / "data" / "empleados.csv"
DATA_SOURCE = os.getenv("DATA_SOURCE", SHEET_CSV_URL)

MAX_REGISTROS = int(os.getenv("MAX_REGISTROS", "50"))
HEADLESS = os.getenv("HEADLESS", "false").strip().lower() in ("1", "true", "yes", "si")
TIMEOUT_SEGUNDOS = int(os.getenv("TIMEOUT_SEGUNDOS", "10"))

LOG_DIR = BASE_DIR / "logs"
OUTPUT_DIR = BASE_DIR / "output"
SCREENSHOT_DIR = BASE_DIR / "screenshots"

for _dir in (LOG_DIR, OUTPUT_DIR, SCREENSHOT_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

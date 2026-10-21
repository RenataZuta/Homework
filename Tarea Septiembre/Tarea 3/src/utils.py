"""Constantes, rutas y utilidades compartidas por todo el pipeline (Persona 1, 2 y 3).

Importar siempre desde aquí: ``from src.utils import RANDOM_SEED, OCR_DIR, set_all_seeds``.
"""
from __future__ import annotations

import json
import os
import random
import re
import string
from pathlib import Path

# ── Reproducibilidad y muestreo ──────────────────────────────────────────────
RANDOM_SEED = 42
SAMPLE_PER_OCCUPATION = 800  # bajar a 400 si el cómputo (OCR en CPU) no alcanza
SHUFFLE_BUFFER_SIZE = 5000
TARGET_CAP = 20  # PopResume topa exp_year en 20 años

HF_DATASET = "sumin-yu/PopResume"

# Nombres EXACTOS de las ocupaciones tal como aparecen en los archivos del dataset
# (data/images/{occupation}-*.parquet y data/text/{occupation}.parquet).
OCCUPATIONS = [
    "accountants_auditors",
    "construction_laborers",
    "elementary_middle_school_teachers",
    "registered_nurses",
    "software_developers",
]

# Bandas de experiencia para estratificar (límites superiores inclusivos).
EXP_BAND_EDGES = [-1, 2, 5, 10, float("inf")]
EXP_BAND_LABELS = ["0-2", "3-5", "6-10", f"11-{TARGET_CAP}"]

# ── Rutas ────────────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
RAW_IMAGES_DIR = RAW_DIR / "images"
OCR_DIR = DATA_DIR / "ocr"
PROCESSED_DIR = DATA_DIR / "processed"
SPLITS_DIR = DATA_DIR / "splits"
MODELS_DIR = ROOT_DIR / "models"
OUTPUT_DIR = ROOT_DIR / "output"
FIGURES_DIR = OUTPUT_DIR / "figures"
TABLES_DIR = OUTPUT_DIR / "tables"
METRICS_DIR = OUTPUT_DIR / "metrics"

METADATA_CSV = RAW_DIR / "metadata.csv"
REFERENCE_TEXTS_CSV = RAW_DIR / "reference_texts.csv"
OCR_QUALITY_CSV = PROCESSED_DIR / "ocr_quality.csv"
CLEAN_TEXTS_CSV = PROCESSED_DIR / "clean_texts.csv"


def ensure_dirs() -> None:
    """Crea (si faltan) todas las carpetas de datos y salidas."""
    for d in (RAW_IMAGES_DIR, OCR_DIR, PROCESSED_DIR, SPLITS_DIR, FIGURES_DIR, TABLES_DIR, METRICS_DIR,
              MODELS_DIR / "baselines", MODELS_DIR / "bert"):
        d.mkdir(parents=True, exist_ok=True)


def set_all_seeds(seed: int = RANDOM_SEED) -> None:
    """Fija las semillas de random, numpy y torch (si están instalados)."""
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    try:
        import numpy as np
        np.random.seed(seed)
    except ImportError:
        pass
    try:
        import torch
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
    except ImportError:
        pass


def get_hf_token() -> str | None:
    """Token de Hugging Face: variable HF_TOKEN, luego ``.env`` (ignorado por git), luego caché de huggingface_hub."""
    token = os.environ.get("HF_TOKEN")
    if token:
        return token.strip()
    env_file = ROOT_DIR / ".env"
    if env_file.exists():
        m = re.search(r"^HF_TOKEN=(.*)$", env_file.read_text(encoding="utf-8"), flags=re.M)
        if m and m.group(1).strip():
            return m.group(1).strip()
    try:
        from huggingface_hub import get_token
        return get_token()
    except ImportError:
        return None


def assign_band(exp_year: float) -> str:
    """Banda de experiencia ('0-2', '3-5', '6-10', '11-20') para un valor de exp_year."""
    if exp_year <= 2:
        return EXP_BAND_LABELS[0]
    if exp_year <= 5:
        return EXP_BAND_LABELS[1]
    if exp_year <= 10:
        return EXP_BAND_LABELS[2]
    return EXP_BAND_LABELS[3]


_PUNCT_TABLE = {ord(c): " " for c in string.punctuation + "•·●▪–—‘’“”…|"}


def normalize_text(text: str) -> str:
    """Normalización común para comparar OCR vs. referencia: minúsculas, sin puntuación, espacios colapsados.

    La puntuación se reemplaza por espacio (no se borra) para no pegar tokens como ``2014-2019``.
    """
    if not isinstance(text, str):
        return ""
    return " ".join(text.lower().translate(_PUNCT_TABLE).split())


def read_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json_atomic(path: Path, obj: dict) -> None:
    """Escritura atómica: evita JSON truncados si el OCR se interrumpe a la mitad."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)

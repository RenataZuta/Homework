"""Descarga SOLO id + sexo + raza de los CVs muestreados (para la Pregunta 4, equidad).

``src.download_data`` guardó id, occupation y exp_year, pero no los atributos demográficos. Este script lee el config
"text" de PopResume (sin imágenes), detecta las columnas de sexo y raza y guarda data/raw/demographics.csv
(id, sex, race; no se versiona). Sexo y raza NUNCA se usan como features: solo para auditar errores después de predecir.

Requiere el token de Hugging Face (``python scripts/set_hf_token.py``).
Uso (desde Tarea 3/):  python scripts/fetch_demographics.py   y luego   python -m src.visualization
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import utils as U  # noqa: E402

SEX_NAMES = ("sex", "gender")
RACE_NAMES = ("race", "ethnicity", "race_ethnicity")


def main() -> int:
    from datasets import load_dataset

    token = U.get_hf_token()
    if not token:
        print("ERROR: falta el token de Hugging Face (python scripts/set_hf_token.py).", file=sys.stderr)
        return 2
    ids = set()
    for s in ("train", "val", "test"):
        ids |= set(pd.read_csv(U.SPLITS_DIR / f"{s}.csv", dtype={"id": str})["id"])

    dd = load_dataset(U.HF_DATASET, "text", token=token)
    df = pd.concat([dd[s].to_pandas() for s in dd], ignore_index=True)
    cols = {c.lower(): c for c in df.columns}
    sex = next((cols[n] for n in SEX_NAMES if n in cols), None)
    race = next((cols[n] for n in RACE_NAMES if n in cols), None)
    if not sex and not race:
        print(f"ERROR: el config 'text' no trae sexo ni raza. Columnas: {list(df.columns)}", file=sys.stderr)
        return 1
    df["id"] = df["id"].astype(str)
    keep = ["id"] + [c for c in (sex, race) if c]
    out = df.loc[df["id"].isin(ids), keep].drop_duplicates("id")
    out = out.rename(columns={sex: "sex", race: "race"} if race else {sex: "sex"})
    U.RAW_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(U.RAW_DIR / "demographics.csv", index=False)
    print(f"data/raw/demographics.csv: {len(out)} de {len(ids)} CVs, columnas {list(out.columns)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Descarga SOLO id + sexo + raza de los CVs muestreados (para la Pregunta 4, equidad).

``src.download_data`` guardó id, occupation y exp_year, pero no los atributos demográficos. Este script lee de los
parquet de texto de PopResume (``data/text/{ocupación}.parquet``) únicamente las columnas id, sex, race y exp_year
(sin el texto ni las imágenes), comprueba que exp_year coincida con data/splits y guarda data/raw/demographics.csv
(id, sex, race; no se versiona). Sexo y raza NUNCA se usan como features: solo para auditar errores después de predecir.

Requiere el token de Hugging Face (``python scripts/set_hf_token.py``).
Uso (desde Tarea 3/):  python scripts/fetch_demographics.py   y luego   python -m src.visualization
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import utils as U  # noqa: E402

COLUMNS = ["id", "sex", "race", "exp_year"]


def main() -> int:
    import pyarrow.parquet as pq
    from huggingface_hub import HfFileSystem

    token = U.get_hf_token()
    if not token:
        print("ERROR: falta el token de Hugging Face (python scripts/set_hf_token.py).", file=sys.stderr)
        return 2
    splits = pd.concat([pd.read_csv(U.SPLITS_DIR / f"{s}.csv", dtype={"id": str}) for s in ("train", "val", "test")])

    fs = HfFileSystem(token=token)
    parts = []
    for occ in U.OCCUPATIONS:
        with fs.open(f"datasets/{U.HF_DATASET}/data/text/{occ}.parquet") as fh:
            parts.append(pq.read_table(fh, columns=COLUMNS).to_pandas())
        print(f"  {occ}: {len(parts[-1])} filas")
    df = pd.concat(parts, ignore_index=True)
    df["id"] = df["id"].astype(str)
    df = df[df["id"].isin(set(splits["id"]))].drop_duplicates("id")

    check = splits.merge(df, on="id", how="left", suffixes=("", "_hf"))
    missing = int(check["sex"].isna().sum())
    mismatch = int((~np.isclose(check["exp_year"], check["exp_year_hf"])).sum() - missing)
    print(f"Unidos {len(df)} de {len(splits)} CVs; sin datos: {missing}; exp_year distinto: {mismatch}")
    if mismatch:
        print("AVISO: exp_year no coincide en algunos ids; revisar antes de usar.", file=sys.stderr)

    U.RAW_DIR.mkdir(parents=True, exist_ok=True)
    df[["id", "sex", "race"]].to_csv(U.RAW_DIR / "demographics.csv", index=False)
    print("data/raw/demographics.csv guardado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

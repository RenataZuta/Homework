"""Paso 3 — Descarga por streaming de PopResume, una ocupación a la vez, solo CVs sin foto.

Salidas:
    data/raw/images/{id}.png        imagen de cada CV muestreado
    data/raw/metadata.csv           id, occupation, exp_year
    data/raw/reference_texts.csv    id, text   (config "text" filtrado a los ids muestreados)
    output/metrics/sampling_report.json, output/tables/exp_year_distribution.csv,
    output/figures/exp_year_distribution.png

Requiere token de Hugging Face (dataset restringido): ``python scripts/set_hf_token.py``.

Uso (desde Tarea 3/):
    python -m src.download_data                 # 800 por ocupación
    python -m src.download_data --n 400         # si el cómputo es limitado
    python -m src.download_data --source-dir D  # parquet locales con la misma estructura (pruebas)
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

import pandas as pd
from datasets import Image as HFImage
from datasets import load_dataset
from PIL import Image

from src import utils as U

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
SAFE_ID = re.compile(r"^[A-Za-z0-9_.\-]+$")


def _no_photo(value) -> bool:
    """True si has_photo == False (acepta bool, 0/1 o cadenas)."""
    if isinstance(value, str):
        return value.strip().lower() in ("false", "0", "no")
    return not bool(value)


def _image_column(ds) -> str:
    feats = getattr(ds, "features", None)
    if feats:
        for name, feat in feats.items():
            if isinstance(feat, HFImage):
                return name
    return "image"


def _save_png(raw: dict, dest) -> None:
    """Guarda la imagen como PNG (copia los bytes si ya son PNG; si no, convierte con PIL)."""
    data = raw.get("bytes")
    if data is None and raw.get("path"):
        with open(raw["path"], "rb") as f:
            data = f.read()
    if data is None:
        raise ValueError("el registro de imagen no trae bytes ni ruta")
    if data.startswith(PNG_MAGIC):
        dest.write_bytes(data)
        return
    with Image.open(io.BytesIO(data)) as im:
        im.convert("RGB").save(dest, format="PNG")


def sample_occupation(occupation: str, n: int, token: str | None, source_dir: str | None,
                      buffer_size: int) -> list[dict]:
    """Muestrea n CVs sin foto de una ocupación y guarda sus imágenes. Devuelve filas de metadata."""
    if source_dir:
        data_files = f"{source_dir}/images/{occupation}-*.parquet"
    else:
        data_files = f"hf://datasets/{U.HF_DATASET}/data/images/{occupation}-*.parquet"

    ds = load_dataset("parquet", data_files=data_files, split="train", streaming=True, token=token)
    img_col = _image_column(ds)
    ds = ds.cast_column(img_col, HFImage(decode=False))  # bytes crudos: menos RAM en el buffer de shuffle
    ds = ds.filter(lambda ex: _no_photo(ex["has_photo"]))
    ds = ds.shuffle(seed=U.RANDOM_SEED, buffer_size=buffer_size).take(n)

    rows: list[dict] = []
    warned = False
    for ex in ds:
        cv_id = str(ex["id"])
        if not SAFE_ID.match(cv_id):
            raise ValueError(f"id con caracteres no seguros para nombre de archivo: {cv_id!r}")
        if not warned and str(ex.get("occupation", occupation)) != occupation:
            print(f"  AVISO: columna occupation={ex['occupation']!r} difiere del nombre de archivo {occupation!r}; "
                  f"se usa el de archivo.")
            warned = True
        _save_png(ex[img_col], U.RAW_IMAGES_DIR / f"{cv_id}.png")
        rows.append({"id": cv_id, "occupation": occupation, "exp_year": ex["exp_year"]})
        if len(rows) % 100 == 0:
            print(f"  {occupation}: {len(rows)}/{n}", flush=True)
    return rows


def sample_all(n: int, token: str | None, source_dir: str | None, buffer_size: int, force: bool) -> pd.DataFrame:
    previous = pd.DataFrame(columns=["id", "occupation", "exp_year"])
    if U.METADATA_CSV.exists() and not force:
        previous = pd.read_csv(U.METADATA_CSV, dtype={"id": str})

    parts = []
    for occ in U.OCCUPATIONS:
        done = previous[previous["occupation"] == occ]
        complete = len(done) >= n and all((U.RAW_IMAGES_DIR / f"{i}.png").exists() for i in done["id"])
        if complete:
            print(f"[{occ}] ya muestreada ({len(done)} CVs); se omite (usa --force para rehacer).")
            parts.append(done.head(n))
            continue
        print(f"[{occ}] muestreando {n} CVs sin foto por streaming...", flush=True)
        rows = sample_occupation(occ, n, token, source_dir, buffer_size)
        if len(rows) < n:
            print(f"  AVISO: solo hay {len(rows)} CVs sin foto disponibles en la ventana de shuffle (pedidos {n}).")
        parts.append(pd.DataFrame(rows))
        # guardado incremental: si se corta la red, lo ya descargado se conserva
        pd.concat(parts, ignore_index=True).to_csv(U.METADATA_CSV, index=False)

    meta = pd.concat(parts, ignore_index=True)
    dup = meta["id"].duplicated().sum()
    if dup:
        print(f"AVISO: {dup} ids duplicados entre ocupaciones; se conserva la primera aparición.")
        meta = meta.drop_duplicates("id")
    meta.to_csv(U.METADATA_CSV, index=False)
    return meta


def save_reference_texts(meta: pd.DataFrame, source_dir: str | None, token: str | None) -> pd.DataFrame:
    if source_dir:
        text_ds = load_dataset("parquet", data_files=f"{source_dir}/text/*.parquet", split="train")
        text_df = text_ds.to_pandas()
    else:
        dd = load_dataset(U.HF_DATASET, "text", token=token)
        text_df = pd.concat([dd[s].to_pandas() for s in dd], ignore_index=True)

    missing_cols = {"id", "text"} - set(text_df.columns)
    if missing_cols:
        raise KeyError(f"El config 'text' no trae las columnas {sorted(missing_cols)}; columnas reales: "
                       f"{list(text_df.columns)}")
    text_df["id"] = text_df["id"].astype(str)
    ref = text_df[text_df["id"].isin(set(meta["id"]))][["id", "text"]].drop_duplicates("id")
    absent = len(meta) - len(ref)
    if absent:
        print(f"AVISO: {absent} CVs muestreados no tienen texto de referencia.")
    ref.to_csv(U.REFERENCE_TEXTS_CSV, index=False)
    return ref


def report(meta: pd.DataFrame, n: int) -> dict:
    """Resumen del muestreo y análisis del tope (cap) de exp_year."""
    exp = pd.to_numeric(meta["exp_year"])
    at_cap = int((exp >= U.TARGET_CAP).sum())
    share_cap = at_cap / len(meta)
    summary = {
        "total_cvs": int(len(meta)),
        "n_per_occupation_requested": n,
        "per_occupation": meta["occupation"].value_counts().to_dict(),
        "exp_year_min": float(exp.min()),
        "exp_year_max": float(exp.max()),
        "exp_year_mean": round(float(exp.mean()), 3),
        "exp_year_median": float(exp.median()),
        "target_cap": U.TARGET_CAP,
        "n_at_or_above_cap": at_cap,
        "share_at_or_above_cap": round(share_cap, 4),
        "share_at_or_above_25": round(float((exp >= 25).mean()), 4),
        "share_at_or_above_30": round(float((exp >= 30).mean()), 4),
        "share_at_cap_by_occupation": (exp >= U.TARGET_CAP).groupby(meta["occupation"]).mean().round(4).to_dict(),
    }

    dist = (meta.assign(exp_year=exp).groupby(["occupation", "exp_year"]).size()
            .rename("n").reset_index())
    dist.to_csv(U.TABLES_DIR / "exp_year_distribution.csv", index=False)
    with open(U.METRICS_DIR / "sampling_report.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(9, 4))
        exp.plot.hist(bins=range(int(exp.min()), int(exp.max()) + 2), ax=ax, color="#4c72b0", edgecolor="white")
        ax.axvline(U.TARGET_CAP, color="crimson", ls="--", label=f"cap = {U.TARGET_CAP}")
        ax.set(title="Distribución de años de experiencia (muestra)", xlabel="exp_year", ylabel="CVs")
        ax.legend()
        fig.tight_layout()
        fig.savefig(U.FIGURES_DIR / "exp_year_distribution.png", dpi=150)
        plt.close(fig)
    except ImportError:
        pass

    print("\n══ REPORTE DE MUESTREO ══")
    print(f"Total de CVs: {summary['total_cvs']}  |  por ocupación: {summary['per_occupation']}")
    print(f"exp_year: min={summary['exp_year_min']}  mediana={summary['exp_year_median']}  "
          f"media={summary['exp_year_mean']}  max={summary['exp_year_max']}")
    print(f"En el cap (exp_year >= {U.TARGET_CAP}): {at_cap} ({share_cap:.1%})")
    print(f"Por ocupación: { {k: f'{v:.1%}' for k, v in summary['share_at_cap_by_occupation'].items()} }")
    if share_cap > 0.15:
        print(f"⚠ Más del 15% está en el cap. Con cap=25 quedaría {summary['share_at_or_above_25']:.1%} y con cap=30 "
              f"{summary['share_at_or_above_30']:.1%} en el tope. Hay que justificar (en el README) si se sube.")
        if summary["exp_year_max"] <= U.TARGET_CAP:
            print("  Nota: el máximo observado es igual al cap, es decir, la variable ya viene censurada en el dataset; "
                  "subir TARGET_CAP no recupera información.")
    else:
        print("Menos del 15% en el cap: se mantiene TARGET_CAP = 20.")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=U.SAMPLE_PER_OCCUPATION, help="CVs por ocupación (800 o 400)")
    ap.add_argument("--buffer-size", type=int, default=U.SHUFFLE_BUFFER_SIZE)
    ap.add_argument("--source-dir", default=None, help="carpeta local con images/ y text/ en parquet (pruebas)")
    ap.add_argument("--force", action="store_true", help="rehacer el muestreo aunque ya exista")
    args = ap.parse_args(argv)

    U.ensure_dirs()
    U.set_all_seeds()
    token = None if args.source_dir else U.get_hf_token()
    if not args.source_dir:
        if not token:
            print("ERROR: falta el token de Hugging Face (PopResume es un dataset restringido).\n"
                  "  1) Acepta las condiciones en https://huggingface.co/datasets/sumin-yu/PopResume\n"
                  "  2) Crea un token de lectura y guárdalo con: python scripts/set_hf_token.py", file=sys.stderr)
            return 2
        os.environ["HF_TOKEN"] = token

    meta = sample_all(args.n, token, args.source_dir, args.buffer_size, args.force)
    save_reference_texts(meta, args.source_dir, token)
    report(meta, args.n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

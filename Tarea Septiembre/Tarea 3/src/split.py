"""Paso 7 — Split train/val/test 70/15/15 estratificado por ocupación Y banda de experiencia (seed=42).

Bandas: 0-2, 3-5, 6-10, 11-20 (``utils.assign_band``).
Salidas: data/splits/{train,val,test}.csv (id, occupation, exp_year, band)
         output/tables/split_balance.csv, output/metrics/split_report.json

Uso (desde Tarea 3/):  python -m src.split
"""
from __future__ import annotations

import json
import sys

import pandas as pd
from sklearn.model_selection import train_test_split

from src import utils as U

TRAIN_FRAC, VAL_FRAC, TEST_FRAC = 0.70, 0.15, 0.15
MIN_STRATUM = 10  # estratos más chicos se agrupan solo para estratificar (la banda real no cambia)


def stratify_key(df: pd.DataFrame) -> pd.Series:
    key = df["occupation"] + "|" + df["band"]
    counts = key.value_counts()
    rare = counts[counts < MIN_STRATUM].index
    if len(rare):
        print(f"AVISO: {len(rare)} estratos con <{MIN_STRATUM} CVs se agrupan por ocupación para estratificar: "
              f"{counts[rare].to_dict()}")
        key = key.where(~key.isin(rare), df["occupation"] + "|otras")
        counts = key.value_counts()
        still = counts[counts < MIN_STRATUM].index
        key = key.where(~key.isin(still), "otras")
    return key


def make_splits(meta: pd.DataFrame) -> dict[str, pd.DataFrame]:
    meta = meta.copy()
    meta["band"] = meta["exp_year"].map(U.assign_band)
    key = stratify_key(meta)
    train, rest = train_test_split(meta, test_size=VAL_FRAC + TEST_FRAC, stratify=key, random_state=U.RANDOM_SEED)
    val, test = train_test_split(rest, test_size=TEST_FRAC / (VAL_FRAC + TEST_FRAC), stratify=key.loc[rest.index],
                                 random_state=U.RANDOM_SEED)
    return {"train": train, "val": val, "test": test}


def balance_table(splits: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Proporción de cada ocupación, banda y celda ocupación×banda dentro de cada conjunto."""
    out: dict[tuple[str, str], dict[str, float]] = {}
    for name, df in splits.items():
        for level, cols in (("occupation", ["occupation"]), ("band", ["band"]), ("occupation x band", ["occupation", "band"])):
            share = df.groupby(cols).size() / len(df)
            for idx, val in share.items():
                label = " | ".join(map(str, idx)) if isinstance(idx, tuple) else str(idx)
                out.setdefault((level, label), {})[name] = val
    tab = pd.DataFrame(out).T.fillna(0.0)
    tab.index.names = ["level", "group"]
    tab["max_abs_diff"] = tab[["train", "val", "test"]].max(axis=1) - tab[["train", "val", "test"]].min(axis=1)
    return tab.round(4)


def main() -> int:
    U.ensure_dirs()
    meta = pd.read_csv(U.METADATA_CSV, dtype={"id": str})
    splits = make_splits(meta)

    ids = [set(df["id"]) for df in splits.values()]
    assert not (ids[0] & ids[1] or ids[0] & ids[2] or ids[1] & ids[2]), "hay ids repetidos entre splits"
    assert sum(len(i) for i in ids) == len(meta), "el split perdió o duplicó CVs"

    for name, df in splits.items():
        df[["id", "occupation", "exp_year", "band"]].to_csv(U.SPLITS_DIR / f"{name}.csv", index=False)

    tab = balance_table(splits)
    tab.to_csv(U.TABLES_DIR / "split_balance.csv")
    worst = tab.groupby(level="level")["max_abs_diff"].max().to_dict()
    report = {
        "sizes": {k: int(len(v)) for k, v in splits.items()},
        "fractions": {k: round(len(v) / len(meta), 4) for k, v in splits.items()},
        "max_share_difference_across_splits": worst,
        "exp_year_mean": {k: round(float(v["exp_year"].mean()), 3) for k, v in splits.items()},
    }
    with open(U.METRICS_DIR / "split_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("══ SPLIT 70/15/15 (seed=42) ══")
    print(json.dumps(report, indent=2))
    print("\nProporciones por ocupación y banda en cada split:")
    print(tab[tab.index.get_level_values("level") != "occupation x band"].to_string())
    print("\nSin ids repetidos entre splits ✔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Paso 5 — Calidad del OCR frente al texto de referencia (CER, WER y exactitud de años).

Entradas : data/raw/reference_texts.csv, data/raw/metadata.csv, data/ocr/{id}.json
Salidas  : data/processed/ocr_quality.csv  (id, cer, wer, years_accuracy)
           output/tables/ocr_quality_summary.csv, ocr_quality_by_occupation.csv
           output/metrics/ocr_quality.json, output/figures/ocr_cer_wer_hist.png

Ambos textos se normalizan igual (minúsculas, sin puntuación, espacios colapsados) antes de comparar.
Limitación a tener en cuenta: CER/WER dependen del ORDEN de lectura; en layouts de dos columnas un orden distinto
al de la referencia infla el error aunque cada palabra esté bien leída.

Uso (desde Tarea 3/):  python -m src.ocr_quality
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter

import jiwer
import pandas as pd

from src import utils as U

YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")


def years_in(text: str) -> list[str]:
    return YEAR_RE.findall(text) if isinstance(text, str) else []


def years_accuracy(reference: str, hypothesis: str) -> float | None:
    """Fracción de años (con multiplicidad) del texto de referencia que aparecen en el OCR. None si no hay años."""
    ref = Counter(years_in(reference))
    total = sum(ref.values())
    if total == 0:
        return None
    hyp = Counter(years_in(hypothesis))
    return sum(min(c, hyp[y]) for y, c in ref.items()) / total


def error_rates(reference: str, hypothesis: str) -> tuple[float, float]:
    """(CER, WER) tras normalizar ambos textos. Referencia vacía → NaN."""
    ref, hyp = U.normalize_text(reference), U.normalize_text(hypothesis)
    if not ref:
        return float("nan"), float("nan")
    if not hyp:  # OCR vacío: todo son omisiones
        return 1.0, 1.0
    return jiwer.cer(ref, hyp), jiwer.wer(ref, hyp)


def compute_quality(reference_csv=U.REFERENCE_TEXTS_CSV, ocr_dir=U.OCR_DIR) -> pd.DataFrame:
    ref = pd.read_csv(reference_csv, dtype={"id": str})
    rows = []
    for cv_id, ref_text in zip(ref["id"], ref["text"]):
        p = ocr_dir / f"{cv_id}.json"
        if not p.exists():
            continue
        ocr_text = U.read_json(p)["full_text"]
        cer, wer = error_rates(ref_text, ocr_text)
        rows.append({"id": cv_id, "cer": cer, "wer": wer, "years_accuracy": years_accuracy(ref_text, ocr_text)})
    return pd.DataFrame(rows)


def describe(series: pd.Series) -> dict:
    s = series.dropna()
    return {"n": int(s.size), "mean": round(float(s.mean()), 4), "median": round(float(s.median()), 4),
            "p90": round(float(s.quantile(0.9)), 4), "max": round(float(s.max()), 4)}


def main() -> int:
    U.ensure_dirs()
    q = compute_quality()
    if q.empty:
        print("ERROR: no hay JSON de OCR que coincidan con reference_texts.csv", file=sys.stderr)
        return 2
    q.to_csv(U.OCR_QUALITY_CSV, index=False)

    meta = pd.read_csv(U.METADATA_CSV, dtype={"id": str})
    qm = q.merge(meta[["id", "occupation"]], on="id", how="left")
    summary = pd.DataFrame({"cer": describe(q["cer"]), "wer": describe(q["wer"])}).T
    summary.to_csv(U.TABLES_DIR / "ocr_quality_summary.csv")
    by_occ = qm.groupby("occupation")[["cer", "wer", "years_accuracy"]].mean().round(4)
    by_occ["n"] = qm.groupby("occupation").size()
    by_occ.to_csv(U.TABLES_DIR / "ocr_quality_by_occupation.csv")

    # exactitud de años: global (años leídos / años totales) y media por CV
    ref = pd.read_csv(U.REFERENCE_TEXTS_CSV, dtype={"id": str}).set_index("id")["text"]
    tot = hit = 0
    for cv_id in q["id"]:
        r = Counter(years_in(ref[cv_id]))
        h = Counter(years_in(U.read_json(U.OCR_DIR / f"{cv_id}.json")["full_text"]))
        tot += sum(r.values())
        hit += sum(min(c, h[y]) for y, c in r.items())
    years_global = hit / tot if tot else None

    result = {
        "n_cvs": int(len(q)),
        "cer": describe(q["cer"]),
        "wer": describe(q["wer"]),
        "years_accuracy_mean_per_cv": round(float(q["years_accuracy"].mean()), 4),
        "years_accuracy_global": round(years_global, 4) if years_global is not None else None,
        "years_total_in_reference": tot,
        "by_occupation": by_occ.to_dict(orient="index"),
    }
    with open(U.METRICS_DIR / "ocr_quality.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
        for ax, col, color in zip(axes, ["cer", "wer"], ["#4c72b0", "#dd8452"]):
            q[col].plot.hist(bins=40, ax=ax, color=color, edgecolor="white")
            ax.axvline(q[col].median(), color="black", ls="--", label=f"mediana {q[col].median():.3f}")
            ax.set(title=col.upper(), xlabel=col.upper(), ylabel="CVs")
            ax.legend()
        fig.tight_layout()
        fig.savefig(U.FIGURES_DIR / "ocr_cer_wer_hist.png", dpi=150)
        plt.close(fig)
    except ImportError:
        pass

    print("══ CALIDAD DEL OCR ══")
    print(summary.to_string())
    print("\nMedia por ocupación:")
    print(by_occ.to_string())
    print(f"\nAños leídos correctamente: {result['years_accuracy_global']:.1%} (global, {tot} años en la referencia) | "
          f"{result['years_accuracy_mean_per_cv']:.1%} (media por CV)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

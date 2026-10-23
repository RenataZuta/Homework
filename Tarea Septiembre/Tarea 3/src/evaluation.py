"""Paso 9 — Evaluación en TEST (Persona 2): tabla comparativa, bootstrap pareado, gráficos y análisis de errores.

Lee las predicciones guardadas por ``src.baselines`` y ``src.train_bert`` (texto OCR limpio) y produce:
  output/tables/model_comparison.csv          MAE (principal), RMSE, ±1/±2/±3, accuracy y macro-F1 por bandas, R², sesgo
  output/tables/mae_by_band.csv, mae_by_occupation.csv, confusion_{modelo}.csv
  output/tables/bootstrap_bert_vs_baselines.csv   ΔMAE = MAE(baseline) − MAE(BERT) con IC 95 % (bootstrap pareado)
  output/tables/bert_top10_errors.csv         10 mayores errores de BERT con la causa asignada
  output/figures/pred_vs_real.png, mae_by_band.png, mae_by_occupation.png

Uso (desde Tarea 3/):  python -m src.evaluation --bert-tag distilbert-base-uncased_mse
"""
from __future__ import annotations

import argparse
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src import model_common as M
from src import utils as U
from src.preprocessing import TRUNCATED_RANGE_RE

N_BOOT = 2000
BASELINES = ["median", "tfidf_ridge", "emb_minilm_ridge", "rule_dates"]
LABELS = {"median": "Mediana", "tfidf_ridge": "TF-IDF + Ridge", "emb_minilm_ridge": "MiniLM congelado + Ridge",
          "rule_dates": "Regla de fechas (bonus)"}


def load_preds(name: str, source: str = "ocr", split: str = "test") -> pd.DataFrame:
    df = pd.read_csv(U.PREDICTIONS_DIR / f"{name}__{source}.csv", dtype={"id": str})
    return df[df["split"] == split].reset_index(drop=True)


def paired_bootstrap(err_base: np.ndarray, err_bert: np.ndarray, n_boot: int = N_BOOT, seed: int = U.RANDOM_SEED) -> dict:
    """ΔMAE = MAE(baseline) − MAE(BERT) remuestreando los MISMOS CVs para ambos modelos. Δ>0 → BERT mejor."""
    rng = np.random.default_rng(seed)
    n = len(err_base)
    idx = rng.integers(0, n, size=(n_boot, n))
    deltas = err_base[idx].mean(axis=1) - err_bert[idx].mean(axis=1)
    lo, hi = np.percentile(deltas, [2.5, 97.5])
    return {"delta_MAE": float(err_base.mean() - err_bert.mean()), "ci95_low": float(lo), "ci95_high": float(hi),
            "p_bert_better": float((deltas > 0).mean()), "n_boot": n_boot}


def classify_error(row: pd.Series, ocr_text: str, ref_text: str, rule_pred: float) -> str:
    """Asigna la causa más probable de un error grande mirando el CV (heurística transparente, en este orden)."""
    r_ocr, r_ref = M.job_ranges(ocr_text), M.job_ranges(ref_text)
    if r_ocr != r_ref:
        return "fecha mal leída por el OCR"
    if not r_ocr:
        return "fechas faltantes"
    if TRUNCATED_RANGE_RE.search(ocr_text):
        return "fecha truncada por el OCR"
    r = sorted(r_ocr)
    if any(r[i + 1][0] < r[i][1] - 1e-9 for i in range(len(r) - 1)):
        return "trabajos solapados"
    if any(r[i + 1][0] - r[i][1] > 0.25 for i in range(len(r) - 1)):
        return "huecos de carrera"
    if row["tokens"] > 256:
        return "truncamiento"
    n_jobs = len(r)
    return f"aritmética de fechas con {n_jobs} empleos (sin causa de OCR)"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bert-tag", default="distilbert-base-uncased_mse")
    args = ap.parse_args(argv)
    U.ensure_dirs()
    bert = f"bert_{args.bert_tag}"
    models = BASELINES + [bert]
    LABELS[bert] = f"BERT ({args.bert_tag.rsplit('_', 1)[0]})"

    preds = {m: load_preds(m) for m in models}
    ref = preds[bert]
    for m, p in preds.items():
        assert (p["id"] == ref["id"]).all(), f"{m}: el orden de IDs difiere → no es el mismo split"

    # ── Tabla de comparación ──────────────────────────────────────────────────
    rows = []
    for m in models:
        met = M.regression_metrics(preds[m]["y_true"], preds[m]["y_pred"])
        val = load_preds(m, split="val")
        rows.append({"model": m, "label": LABELS[m], "n_test": len(preds[m]), **met,
                     "val_MAE": float(np.abs(val["y_pred"] - val["y_true"]).mean())})
    comp = pd.DataFrame(rows).round(4)
    comp.to_csv(U.TABLES_DIR / "model_comparison.csv", index=False)
    print(comp[["label", "MAE", "RMSE", "acc_pm1", "acc_pm2", "acc_pm3", "band_accuracy", "band_macro_f1", "R2"]]
          .to_string(index=False))

    # ── Por banda y por ocupación + matrices de confusión ────────────────────
    by_band, by_occ = {}, {}
    for m in models:
        p = preds[m].assign(band=M.to_band(preds[m]["y_true"]))
        by_band[LABELS[m]] = M.mae_by(p, "band").reindex(M.BANDS)
        by_occ[LABELS[m]] = M.mae_by(p, "occupation")
        M.confusion_matrix_bands(p["y_true"], p["y_pred"]).to_csv(U.TABLES_DIR / f"confusion_{m}.csv")
    band_df, occ_df = pd.DataFrame(by_band).T.round(3), pd.DataFrame(by_occ).T.round(3)
    band_df.to_csv(U.TABLES_DIR / "mae_by_band.csv"); occ_df.to_csv(U.TABLES_DIR / "mae_by_occupation.csv")

    # ── Bootstrap pareado: BERT frente a cada baseline ───────────────────────
    err_bert = (preds[bert]["y_pred"] - preds[bert]["y_true"]).abs().values
    boot = []
    for m in BASELINES:
        err = (preds[m]["y_pred"] - preds[m]["y_true"]).abs().values
        boot.append({"baseline": LABELS[m], "MAE_baseline": err.mean(), "MAE_bert": err_bert.mean(),
                     **paired_bootstrap(err, err_bert)})
    boot_df = pd.DataFrame(boot).round(4)
    boot_df.to_csv(U.TABLES_DIR / "bootstrap_bert_vs_baselines.csv", index=False)
    print("\nBootstrap pareado (ΔMAE>0 = BERT mejor):\n", boot_df.to_string(index=False))

    # ── Gráficos ──────────────────────────────────────────────────────────────
    fig, axes = plt.subplots(1, len(models), figsize=(4 * len(models), 4), sharex=True, sharey=True)
    for ax, m in zip(axes, models):
        p = preds[m]
        ax.scatter(p["y_true"], p["y_pred"], s=8, alpha=0.5)
        ax.plot([0, U.TARGET_CAP], [0, U.TARGET_CAP], "r--", lw=1, label="y = x")
        ax.set_title(f"{LABELS[m]}\nMAE={np.abs(p['y_pred'] - p['y_true']).mean():.2f}", fontsize=9)
        ax.set_xlabel("años reales")
    axes[0].set_ylabel("años predichos")
    fig.tight_layout(); fig.savefig(U.FIGURES_DIR / "pred_vs_real.png", dpi=130); plt.close(fig)

    for df, name, xlabel in ((band_df, "mae_by_band", "banda de experiencia (años)"),
                             (occ_df, "mae_by_occupation", "ocupación")):
        ax = df.T.plot(kind="bar", figsize=(9, 4), width=0.85)
        ax.set_ylabel("MAE (años)"); ax.set_xlabel(xlabel); ax.set_yscale("symlog", linthresh=0.1)
        ax.legend(fontsize=7); plt.xticks(rotation=20, ha="right"); plt.tight_layout()
        plt.savefig(U.FIGURES_DIR / f"{name}.png", dpi=130); plt.close()

    # ── 10 mayores errores de BERT ────────────────────────────────────────────
    ocr_txt = M.load_split("test", "ocr").set_index("id")["text"]
    ref_txt = M.load_split("test", "reference").set_index("id")["text"]
    top = preds[bert].assign(error=lambda d: d["y_pred"] - d["y_true"])
    top["abs_error"] = top["error"].abs()
    top = top.sort_values("abs_error", ascending=False).head(10).copy()
    top["rule_pred"] = top["id"].map(preds["rule_dates"].set_index("id")["y_pred"])
    top["n_jobs"] = top["id"].map(lambda i: len(M.job_ranges(ocr_txt[i])))
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(U.BERT_DIR / args.bert_tag)
    top["tokens"] = top["id"].map(lambda i: len(tok(ocr_txt[i])["input_ids"]))
    top["cause"] = [classify_error(r, ocr_txt[r["id"]], ref_txt[r["id"]], r["rule_pred"]) for _, r in top.iterrows()]
    top.drop(columns="tokens").round(3).to_csv(U.TABLES_DIR / "bert_top10_errors.csv", index=False)
    print("\nTop-10 errores de BERT:\n", top[["id", "y_true", "y_pred", "error", "rule_pred", "n_jobs", "cause"]]
          .round(2).to_string(index=False))
    print("\nCausas:", top["cause"].value_counts().to_dict())

    (U.METRICS_DIR / "evaluation_summary.json").write_text(
        json.dumps({"bert_tag": args.bert_tag, "n_test": int(len(ref)),
                    "n_boot": N_BOOT, "causes_top10": top["cause"].value_counts().to_dict()}, indent=2,
                   ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

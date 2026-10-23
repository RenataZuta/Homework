"""Paso 7 — Baselines (Persona 2): mediana, TF-IDF + Ridge, embeddings congelados + Ridge y regla de fechas (bonus).

Todos se entrenan SOLO con el split train (texto OCR limpio) y los hiperparámetros se eligen con val; el test no se toca
hasta ``src.evaluation``. Cada modelo guarda:
  models/baselines/{nombre}.joblib                     (predictor con interfaz ``predict(list[str])``)
  output/predictions/{nombre}__{fuente}.csv            (id, split, y_true, y_pred) para fuente ∈ {ocr, reference}
  output/tables/baselines_val_search.csv               (búsqueda de hiperparámetros sobre val)

Modelos:
  median           mediana del train
  tfidf_ridge      TF-IDF palabras 1-2gramas CON números/años (decisión justificada en el README con val)
  tfidf_ridge_nonum  igual pero borrando todos los dígitos (sensibilidad, Pregunta 3)
  emb_minilm_ridge all-MiniLM-L6-v2 congelado (mean-pooling por trozos de líneas) + Ridge
  rule_dates       suma de duraciones de los rangos «AAAA.MM–AAAA.MM» (bonus, sin aprendizaje)

Uso (desde Tarea 3/):  python -m src.baselines [--skip-embeddings]
"""
from __future__ import annotations

import argparse
import time

import joblib
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline

from src import model_common as M
from src import utils as U

ALPHAS = [0.01, 0.03, 0.1, 0.3, 1, 3, 10, 30]


def make_tfidf(alpha: float, numbers: bool) -> object:
    vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=2, lowercase=True,
                          preprocessor=None if numbers else M.strip_digits_lower)
    return make_pipeline(vec, Ridge(alpha=alpha, random_state=U.RANDOM_SEED))


def save_predictions(name: str, model, data: dict[str, dict]) -> None:
    """Guarda predicciones de val y test para las fuentes disponibles en ``data[fuente][split]``."""
    for source, splits in data.items():
        rows = []
        for split in ("val", "test"):
            df = splits[split]
            rows.append(pd.DataFrame({"id": df["id"], "split": split, "occupation": df["occupation"],
                                      "y_true": df["exp_year"], "y_pred": model.predict(df["text"].tolist())}))
        pd.concat(rows).to_csv(U.PREDICTIONS_DIR / f"{name}__{source}.csv", index=False)


def search_ridge(name, build, train, val, search_rows):
    """Elige alpha por MAE en val; reentrena con ese alpha sobre train."""
    best = (None, np.inf)
    for a in ALPHAS:
        m = build(a)
        m.fit(train["text"].tolist(), train["exp_year"])
        mae = float(np.abs(M.clip_target(m.predict(val["text"].tolist())) - val["exp_year"]).mean())
        search_rows.append({"model": name, "alpha": a, "val_MAE": round(mae, 4)})
        if mae < best[1]:
            best = (a, mae)
    return best


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-embeddings", action="store_true", help="omite el baseline de embeddings (necesita HF)")
    args = ap.parse_args(argv)
    U.ensure_dirs()
    U.PREDICTIONS_DIR.mkdir(parents=True, exist_ok=True)
    U.set_all_seeds()

    ocr, ref = M.load_all("ocr"), M.load_all("reference")
    data = {"ocr": ocr, "reference": ref}
    train, val = ocr["train"], ocr["val"]
    search_rows, info = [], {}

    # 1) Mediana
    med = M.MedianModel().fit(train["text"], train["exp_year"])
    joblib.dump(med, U.BASELINES_DIR / "median.joblib")
    save_predictions("median", med, data)
    info["median"] = {"median_train": med.median_}

    # 2) Regla de fechas — se elige la variante por MAE en train+val (no tiene parámetros que aprender)
    rule_scores = {}
    for mode in ("sum", "union", "span"):
        r = M.RuleModel(mode)
        rule_scores[mode] = float(np.abs(r.predict(val["text"].tolist()) - val["exp_year"]).mean())
    best_mode = min(rule_scores, key=rule_scores.get)
    rule = M.RuleModel(best_mode)
    joblib.dump(rule, U.BASELINES_DIR / "rule_dates.joblib")
    save_predictions("rule_dates", rule, data)
    info["rule_dates"] = {"val_MAE_by_mode": rule_scores, "chosen": best_mode}

    # 3) TF-IDF + Ridge, con y sin números
    for name, numbers in (("tfidf_ridge", True), ("tfidf_ridge_nonum", False)):
        t0 = time.perf_counter()
        a, mae = search_ridge(name, lambda al, n=numbers: M.SklearnTextModel(make_tfidf(al, n)).pipeline,
                              train, val, search_rows)
        pipe = make_tfidf(a, numbers).fit(train["text"].tolist(), train["exp_year"])
        model = M.SklearnTextModel(pipe)
        joblib.dump(model, U.BASELINES_DIR / f"{name}.joblib")
        save_predictions(name, model, data)
        info[name] = {"alpha": a, "val_MAE": mae, "fit_seconds": round(time.perf_counter() - t0, 1)}
        print(f"{name}: alpha={a} val_MAE={mae:.3f}")

    # 4) Embeddings congelados + Ridge
    if not args.skip_embeddings:
        t0 = time.perf_counter()
        emb = M.EmbeddingRidgeModel()
        x_tr, x_va = emb.embed(train["text"].tolist()), emb.embed(val["text"].tolist())
        best = (None, np.inf)
        for a in ALPHAS:
            mae = float(np.abs(M.clip_target(Ridge(alpha=a).fit(x_tr, train["exp_year"]).predict(x_va)) - val["exp_year"]).mean())
            search_rows.append({"model": "emb_minilm_ridge", "alpha": a, "val_MAE": round(mae, 4)})
            if mae < best[1]:
                best = (a, mae)
        emb.ridge = Ridge(alpha=best[0]).fit(x_tr, train["exp_year"])
        joblib.dump(emb, U.BASELINES_DIR / "emb_minilm_ridge.joblib")
        save_predictions("emb_minilm_ridge", emb, data)
        info["emb_minilm_ridge"] = {"encoder": emb.encoder_name, "chunk_max_tokens": emb.max_tokens,
                                    "alpha": best[0], "val_MAE": best[1],
                                    "seconds": round(time.perf_counter() - t0, 1)}
        print(f"emb_minilm_ridge: alpha={best[0]} val_MAE={best[1]:.3f}")

    pd.DataFrame(search_rows).to_csv(U.TABLES_DIR / "baselines_val_search.csv", index=False)
    (U.METRICS_DIR / "baselines_report.json").write_text(
        __import__("json").dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    print("rule_dates:", info["rule_dates"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

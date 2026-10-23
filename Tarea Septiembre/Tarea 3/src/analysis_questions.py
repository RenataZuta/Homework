"""Paso 10 — Preguntas analíticas 1, 2 y 3 (Persona 2). La Pregunta 4 (equidad y ética) es de Persona 3.

  Q1  ¿Qué aprende BERT que los baselines no?  Prueba de perturbación en CVs de TEST: (a) todas las fechas +5 años
      (la duración real NO cambia) y (b) borrar un empleo (la experiencia real baja justo lo que duraba ese empleo).
      Un modelo que lee fechas debe seguir esos cambios; uno que solo usa vocabulario/años absolutos, no.
  Q2  ¿Cuánto cuesta el ruido del OCR?  Cada modelo evaluado en texto OCR limpio vs. texto de referencia limpiado igual.
  Q3  Sensibilidad metodológica: números en TF-IDF, limpieza del OCR (crudo / limpio / sin líneas de baja confianza),
      MSE vs. Huber (si existe esa corrida de BERT) y estrategia de texto largo (cabeza vs. cabeza+cola con tope bajo).

Salidas en output/tables/: q1_perturbation.csv, q1_perturbation_examples.csv, q2_ocr_noise.csv, q3_*.csv
Uso (desde Tarea 3/):  python -m src.analysis_questions --bert-tag distilbert-base-uncased_mse [--q 1 2 3]
"""
from __future__ import annotations

import argparse

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from src import baselines as B
from src import evaluation as E
from src import model_common as M
from src import preprocessing as P
from src import utils as U

N_PERTURB = 20        # CVs pedidos por el enunciado
N_PERTURB_EXTRA = 200  # muestra ampliada, para que la conclusión no dependa de 20 CVs


def load_predictors(bert_tag: str) -> dict:
    preds = {n: joblib.load(U.BASELINES_DIR / f"{n}.joblib") for n in E.BASELINES}
    from src.train_bert import BertRegressor
    preds[f"bert_{bert_tag}"] = BertRegressor(U.BERT_DIR / bert_tag)
    return preds


# ── Q1 ───────────────────────────────────────────────────────────────────────
def question1(bert_tag: str) -> None:
    models = load_predictors(bert_tag)
    test = M.load_split("test", "ocr")
    multi = test[test["text"].map(lambda t: len(M.job_ranges(t)) >= 2)]
    rows, examples = [], []
    for n, label in ((N_PERTURB, "20 CVs"), (min(N_PERTURB_EXTRA, len(multi)), f"{min(N_PERTURB_EXTRA, len(multi))} CVs")):
        sub = multi.sample(n, random_state=U.RANDOM_SEED)
        shifted = [M.shift_dates(t, 5) for t in sub["text"]]
        dropped, removed = zip(*[M.drop_job(t, 0) for t in sub["text"]])
        removed = np.array([r if r is not None else np.nan for r in removed])
        ok = ~np.isnan(removed)
        y = sub["exp_year"].values
        y_drop = np.clip(y - removed, 0, U.TARGET_CAP)
        for name, mdl in models.items():
            p0 = mdl.predict(sub["text"].tolist())
            p_shift = mdl.predict(shifted)
            p_drop = mdl.predict(list(dropped))
            d_pred = (p_drop - p0)[ok]
            d_exp = -removed[ok]
            slope = float(np.polyfit(d_exp, d_pred, 1)[0]) if d_pred.std() > 1e-9 else 0.0
            rows.append({"muestra": label, "model": name,
                         "MAE_original": np.abs(p0 - y).mean(),
                         "shift+5_mean_|Δpred|": np.abs(p_shift - p0).mean(),
                         "shift+5_MAE_vs_real": np.abs(p_shift - y).mean(),
                         "drop_job_MAE_vs_new_real": np.abs(p_drop[ok] - y_drop[ok]).mean(),
                         "drop_job_Δpred_medio": d_pred.mean(), "drop_job_Δreal_medio": d_exp.mean(),
                         "drop_job_pendiente(Δpred/Δreal)": slope,
                         "drop_job_corr": float(np.corrcoef(d_exp, d_pred)[0, 1]) if d_pred.std() > 1e-9 else 0.0})
            if label == "20 CVs":
                for i in range(len(sub)):
                    examples.append({"id": sub["id"].iloc[i], "model": name, "y_real": y[i], "pred_original": p0[i],
                                     "pred_fechas+5": p_shift[i], "años_empleo_borrado": removed[i],
                                     "pred_sin_empleo": p_drop[i]})
    pd.DataFrame(rows).round(3).to_csv(U.TABLES_DIR / "q1_perturbation.csv", index=False)
    pd.DataFrame(examples).round(3).to_csv(U.TABLES_DIR / "q1_perturbation_examples.csv", index=False)
    print(pd.DataFrame(rows).round(3).to_string(index=False))


# ── Q2 ───────────────────────────────────────────────────────────────────────
def harmonize_format(text: str) -> str:
    """Lleva el texto OCR a las convenciones de formato del texto de referencia (fin de línea y viñetas), SIN corregir
    ningún carácter mal leído. Aísla el efecto del formato del efecto del ruido real de caracteres."""
    return text.replace(chr(13), "").replace("•", "-").replace("·", "-")


def question2(bert_tag: str) -> None:
    """Brecha OCR vs. referencia descompuesta: MAE(ocr) − MAE(ref) = [formato] + [ruido real de caracteres]."""
    models = load_predictors(bert_tag)
    test_ocr, test_ref = M.load_split("test", "ocr"), M.load_split("test", "reference")
    harm = [harmonize_format(t) for t in test_ocr["text"]]
    q = pd.read_csv(U.PROCESSED_DIR / "ocr_quality.csv", dtype={"id": str}).set_index("id")
    cer = test_ocr["id"].map(q["cer"]).values
    y = test_ocr["exp_year"].values
    rows = []
    for name, mdl in models.items():
        e_o = np.abs(mdl.predict(test_ocr["text"].tolist()) - y)
        p_h = mdl.predict(harm)
        e_h = np.abs(p_h - y)
        p_r = mdl.predict(test_ref["text"].tolist())
        e_r = np.abs(p_r - y)
        tot, fmt, noise = E.paired_bootstrap(e_o, e_r), E.paired_bootstrap(e_o, e_h), E.paired_bootstrap(e_h, e_r)
        rows.append({"model": name, "MAE_ocr": e_o.mean(), "MAE_ocr_formato_armonizado": e_h.mean(),
                     "MAE_reference": e_r.mean(),
                     "gap_total(ocr-ref)": tot["delta_MAE"], "gap_total_ci95_low": tot["ci95_low"],
                     "gap_total_ci95_high": tot["ci95_high"],
                     "gap_formato(ocr-armonizado)": fmt["delta_MAE"],
                     "gap_ruido_real(armonizado-ref)": noise["delta_MAE"],
                     "gap_ruido_ci95_low": noise["ci95_low"], "gap_ruido_ci95_high": noise["ci95_high"],
                     "gap_ruido_relativo_%": 100 * noise["delta_MAE"] / e_r.mean(),
                     "pct_CVs_pred_distinta_por_ruido(>0.01a)": 100 * float((np.abs(p_h - p_r) > 0.01).mean()),
                     "MAE_armonizado_CVs_CER>0": e_h[cer > 0].mean(), "MAE_ref_CVs_CER>0": e_r[cer > 0].mean(),
                     "n_CVs_CER>0": int((cer > 0).sum())})
    df = pd.DataFrame(rows).round(4)
    df.to_csv(U.TABLES_DIR / "q2_ocr_noise.csv", index=False)
    print(df.T.to_string(header=False))


# ── Q3 ───────────────────────────────────────────────────────────────────────
def conf_filtered_texts(ids, threshold: float) -> pd.Series:
    out = {}
    for i in ids:
        lines = U.read_json(U.OCR_DIR / f"{i}.json")["lines"]
        out[i] = P.clean_one(lines, threshold)[0]
    return pd.Series(out)


def question3(bert_tag: str) -> None:
    U.set_all_seeds()
    # (a) números en TF-IDF y limpieza del OCR: TF-IDF se REENTRENA con cada variante de texto
    variants = {"limpio (conf≥0.5, por defecto)": "ocr", "crudo (sin limpiar ni quitar PII)": "ocr_raw"}
    texts = {k: M.load_all(v) for k, v in variants.items()}
    lowconf = "sin líneas de baja confianza (conf≥0.99)"
    base = M.load_all("ocr")
    texts[lowconf] = {s: base[s].assign(text=base[s]["id"].map(conf_filtered_texts(base[s]["id"], 0.99))) for s in M.SPLITS}
    rows = []
    for vname, data in texts.items():
        tr, va, te = data["train"], data["val"], data["test"]
        for numbers in (True, False):
            best = (None, np.inf)
            for a in B.ALPHAS:
                m = B.make_tfidf(a, numbers).fit(tr["text"].tolist(), tr["exp_year"])
                mae = np.abs(M.clip_target(m.predict(va["text"].tolist())) - va["exp_year"]).mean()
                if mae < best[1]:
                    best = (a, mae)
            m = B.make_tfidf(best[0], numbers).fit(tr["text"].tolist(), tr["exp_year"])
            rows.append({"decisión": "texto", "variante": vname, "modelo": f"TF-IDF {'con' if numbers else 'sin'} números",
                         "val_MAE": best[1], "test_MAE": np.abs(M.clip_target(m.predict(te["text"].tolist())) - te["exp_year"]).mean()})
        rule = M.RuleModel("sum")
        rows.append({"decisión": "texto", "variante": vname, "modelo": "Regla de fechas",
                     "val_MAE": np.abs(rule.predict(data["val"]["text"].tolist()) - data["val"]["exp_year"]).mean(),
                     "test_MAE": np.abs(rule.predict(data["test"]["text"].tolist()) - data["test"]["exp_year"]).mean()})
    # BERT entrenado con texto limpio, evaluado (sin reentrenar) sobre cada variante de texto
    from src.train_bert import BertRegressor
    bert = BertRegressor(U.BERT_DIR / bert_tag)
    for vname, data in texts.items():
        rows.append({"decisión": "texto", "variante": vname, "modelo": "BERT (entrenado en limpio, sin reentrenar)",
                     "val_MAE": np.abs(bert.predict(data["val"]["text"].tolist()) - data["val"]["exp_year"]).mean(),
                     "test_MAE": np.abs(bert.predict(data["test"]["text"].tolist()) - data["test"]["exp_year"]).mean()})
    # (b) texto largo: cabeza vs. cabeza+cola con un tope artificialmente bajo (prueba de estrés, solo inferencia)
    te = base["test"]
    for max_len in (256, 96, 64):
        for trunc in ("head", "head_tail"):
            b = BertRegressor(U.BERT_DIR / bert_tag, max_len=max_len, truncation=trunc)
            rows.append({"decisión": "texto largo (inferencia)", "variante": f"max_len={max_len}", "modelo": f"BERT {trunc}",
                         "val_MAE": np.nan, "test_MAE": np.abs(b.predict(te["text"].tolist()) - te["exp_year"]).mean()})
    # (c) MSE vs Huber (solo si existe la corrida de Huber)
    for tag in sorted(p.stem.split("__")[0] for p in U.PREDICTIONS_DIR.glob("bert_*__ocr.csv")):
        o = E.load_preds(tag, "ocr"); v = E.load_preds(tag, "ocr", "val")
        rows.append({"decisión": "pérdida", "variante": tag.replace("bert_", ""), "modelo": "BERT",
                     "val_MAE": np.abs(v["y_pred"] - v["y_true"]).mean(), "test_MAE": np.abs(o["y_pred"] - o["y_true"]).mean()})
    df = pd.DataFrame(rows).round(4)
    df.to_csv(U.TABLES_DIR / "q3_sensitivity.csv", index=False)
    print(df.to_string(index=False))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bert-tag", default="distilbert-base-uncased_mse")
    ap.add_argument("--q", nargs="+", type=int, default=[1, 2, 3], choices=[1, 2, 3])
    args = ap.parse_args(argv)
    U.ensure_dirs()
    for q in args.q:
        print(f"\n══ Pregunta {q} ══")
        {1: question1, 2: question2, 3: question3}[q](args.bert_tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

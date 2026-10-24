"""Paso 10 — Figuras del informe y del dashboard (Persona 3) + tablas de equidad (Pregunta 4).

Todas las funciones leen los resultados YA calculados por los pasos anteriores (output/tables, output/predictions,
data/splits, data/processed) y devuelven una figura de matplotlib (o ``None`` si falta el archivo de entrada), para que
``app.py`` las reutilice sin romperse. ``main`` las guarda como PNG en output/figures/.

Pregunta 4 (equidad): MAE y error medio (predicho − real) de BERT en test por sexo y por raza, unidos por ``id``.
Sexo y raza NUNCA son features de ningún modelo; solo se usan aquí, después de predecir. Se leen de
``data/raw/demographics.csv`` (lo genera ``python scripts/fetch_demographics.py``) o de ``data/raw/metadata.csv`` si
trae esas columnas. Si no existen, las tablas de equidad quedan pendientes y el resto funciona igual.

Uso (desde Tarea 3/):  python -m src.visualization
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src import utils as U

BERT_TAG = "minilm-l6_mse"
BERT_KEY = f"bert_{BERT_TAG}"

# Orden fijo de modelos y su color (paleta categórica validada; el color sigue al modelo, nunca al ranking).
MODELS = {
    BERT_KEY: "BERT (MiniLM-L6 ajustado)",
    "tfidf_ridge": "TF-IDF + Ridge",
    "emb_minilm_ridge": "MiniLM congelado + Ridge",
    "median": "Mediana",
    "rule_dates": "Regla de fechas (bonus)",
}
COLORS = {
    BERT_KEY: "#2a78d6",
    "tfidf_ridge": "#eb6834",
    "emb_minilm_ridge": "#1baf7a",
    "median": "#eda100",
    "rule_dates": "#6250d6",
}
# Las tablas de Persona 2 usan estas etiquetas en el índice / columna «baseline».
TABLE_LABELS = {
    "Mediana": "median", "TF-IDF + Ridge": "tfidf_ridge", "MiniLM congelado + Ridge": "emb_minilm_ridge",
    "Regla de fechas (bonus)": "rule_dates", "Regla de fechas": "rule_dates", "BERT": BERT_KEY,
    "BERT (minilm-l6)": BERT_KEY,
}
OCC_SHORT = {
    "accountants_auditors": "Contadores",
    "construction_laborers": "Obreros constr.",
    "elementary_middle_school_teachers": "Docentes",
    "registered_nurses": "Enfermeros",
    "software_developers": "Desarrolladores",
}
BANDS = U.EXP_BAND_LABELS
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"

DEMOGRAPHICS_CSV = U.RAW_DIR / "demographics.csv"
FAIRNESS_SEX_CSV = U.TABLES_DIR / "fairness_by_sex.csv"
FAIRNESS_RACE_CSV = U.TABLES_DIR / "fairness_by_race.csv"


def _style() -> None:
    plt.rcParams.update({
        "figure.dpi": 110, "savefig.dpi": 150, "font.size": 10, "axes.titlesize": 11,
        "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED,
        "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
        "grid.linewidth": 0.8, "axes.axisbelow": True, "legend.frameon": False,
    })


_style()


# ── Lectura segura ───────────────────────────────────────────────────────────
def read_csv(path: Path, **kw) -> pd.DataFrame | None:
    """Lee un CSV o devuelve None si no existe / está vacío (la app no debe romperse)."""
    try:
        df = pd.read_csv(path, **kw)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return None
    return df if len(df) else None


def read_json(path: Path) -> dict | None:
    try:
        return U.read_json(path)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def load_meta() -> pd.DataFrame | None:
    """id, occupation, exp_year (sin recortar), band y split de los 4000 CVs, a partir de data/splits."""
    parts = []
    for s in ("train", "val", "test"):
        df = read_csv(U.SPLITS_DIR / f"{s}.csv", dtype={"id": str})
        if df is not None:
            parts.append(df.assign(split=s))
    return pd.concat(parts, ignore_index=True) if parts else None


def load_predictions(split: str = "test", source: str = "ocr") -> dict[str, pd.DataFrame]:
    """Predicciones guardadas de cada modelo disponible: {clave: df(id, occupation, y_true, y_pred, error)}."""
    out = {}
    for key in MODELS:
        df = read_csv(U.PREDICTIONS_DIR / f"{key}__{source}.csv", dtype={"id": str})
        if df is not None:
            df = df[df["split"] == split].reset_index(drop=True)
            out[key] = df.assign(error=df["y_pred"] - df["y_true"])
    return out


def _by_model_table(path: Path) -> pd.DataFrame | None:
    """Tablas «modelo × columna» de Persona 2 (mae_by_band.csv, mae_by_occupation.csv) indexadas por clave."""
    df = read_csv(path, index_col=0)
    if df is None:
        return None
    df.index = [TABLE_LABELS.get(i, i) for i in df.index]
    return df.loc[[k for k in MODELS if k in df.index]]


# ── 1. Distribución de exp_year ──────────────────────────────────────────────
def fig_exp_distribution() -> plt.Figure | None:
    meta = load_meta()
    if meta is None:
        return None
    exp = meta["exp_year"].astype(float)
    n_cap = int((exp >= U.TARGET_CAP).sum())
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), gridspec_kw={"width_ratios": [1.2, 1]})
    ax = axes[0]
    ax.hist(exp, bins=np.arange(0, np.ceil(exp.max()) + 1), color=COLORS[BERT_KEY], edgecolor="white", linewidth=1)
    ax.axvline(U.TARGET_CAP, color="#e34948", ls="--", lw=1.5)
    ax.annotate(f"tope = {U.TARGET_CAP}\n{n_cap} CVs ≥ {U.TARGET_CAP} ({n_cap / len(exp):.1%})",
                xy=(U.TARGET_CAP, ax.get_ylim()[1] * 0.75), xytext=(8, 0), textcoords="offset points",
                color=INK, fontsize=9)
    ax.set(title=f"Años de experiencia en los {len(exp)} CVs muestreados", xlabel="años de experiencia",
           ylabel="CVs")
    ax = axes[1]
    occs = [o for o in U.OCCUPATIONS if o in set(meta["occupation"])]
    data = [meta.loc[meta["occupation"] == o, "exp_year"].astype(float) for o in occs]
    bp = ax.boxplot(data, orientation="horizontal", patch_artist=True, widths=0.55,
                    medianprops={"color": INK, "lw": 1.5}, flierprops={"markersize": 3, "markeredgecolor": MUTED})
    for p in bp["boxes"]:
        p.set(facecolor="#cfe0f5", edgecolor=MUTED)
    ax.set_yticks(range(1, len(occs) + 1), [f"{OCC_SHORT[o]} ({int((d >= U.TARGET_CAP).sum())} en tope)"
                                            for o, d in zip(occs, data)])
    ax.axvline(U.TARGET_CAP, color="#e34948", ls="--", lw=1.2)
    ax.set(title="Por ocupación (800 CVs cada una)", xlabel="años de experiencia")
    fig.tight_layout()
    return fig


# ── 2. Calidad del OCR por ocupación ─────────────────────────────────────────
def ocr_quality_by_occupation() -> pd.DataFrame | None:
    """CER, WER (en %) y exactitud de años por ocupación, recalculados sin redondear desde ocr_quality.csv."""
    q, meta = read_csv(U.OCR_QUALITY_CSV, dtype={"id": str}), load_meta()
    if q is None or meta is None:
        return None
    q = q.merge(meta[["id", "occupation"]], on="id", how="inner")
    g = q.groupby("occupation").agg(n=("id", "size"), cer=("cer", "mean"), wer=("wer", "mean"),
                                    cvs_con_error=("cer", lambda s: int((s > 0).sum())),
                                    years_accuracy=("years_accuracy", "mean"))
    g["cer_%"], g["wer_%"] = g["cer"] * 100, g["wer"] * 100
    return g.reindex([o for o in U.OCCUPATIONS if o in g.index])


def fig_ocr_quality() -> plt.Figure | None:
    g = ocr_quality_by_occupation()
    if g is None:
        return None
    fig, axes = plt.subplots(1, 2, figsize=(12, 3.8))
    labels = [OCC_SHORT[o] for o in g.index]
    y = np.arange(len(g))
    ax = axes[0]
    ax.barh(y - 0.2, g["cer_%"], height=0.38, color=COLORS[BERT_KEY], label="CER")
    ax.barh(y + 0.2, g["wer_%"], height=0.38, color=COLORS["tfidf_ridge"], label="WER")
    for i, (c, w) in enumerate(zip(g["cer_%"], g["wer_%"])):
        ax.text(c, i - 0.2, f" {c:.3f}%", va="center", fontsize=8, color=INK)
        ax.text(w, i + 0.2, f" {w:.3f}%", va="center", fontsize=8, color=INK)
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set(title="Error de caracteres (CER) y de palabras (WER) medios", xlabel="% (vs. texto de referencia)")
    ax.set_xlim(0, max(g["wer_%"].max(), 0.01) * 1.35)
    ax.legend(loc="upper right")
    ax = axes[1]
    ax.barh(y, g["years_accuracy"] * 100, height=0.55, color=COLORS["emb_minilm_ridge"])
    for i, (v, n_err, n) in enumerate(zip(g["years_accuracy"], g["cvs_con_error"], g["n"])):
        ax.text(1, i, f"{v:.1%} años leídos bien · {n_err}/{n} CVs con algún error de carácter",
                va="center", fontsize=8, color="white")
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set(title="Años (AAAA) del CV leídos correctamente", xlabel="%", xlim=(0, 100))
    fig.tight_layout()
    return fig


# ── 3. Predicho vs. real ─────────────────────────────────────────────────────
def fig_pred_vs_real(models: list[str] | None = None) -> plt.Figure | None:
    preds = load_predictions()
    models = [m for m in (models or list(MODELS)) if m in preds]
    if not models:
        return None
    n = len(models)
    cols = min(n, 3)
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(4.3 * cols, 4.1 * rows), squeeze=False)
    for ax, key in zip(axes.flat, models):
        df = preds[key]
        mae = df["error"].abs().mean()
        ax.scatter(df["y_true"], df["y_pred"], s=12, alpha=0.55, color=COLORS[key], edgecolors="none")
        ax.plot([0, U.TARGET_CAP], [0, U.TARGET_CAP], color=MUTED, ls="--", lw=1.2, label="45° (predicción perfecta)")
        ax.set(xlim=(0, U.TARGET_CAP + 0.5), ylim=(0, U.TARGET_CAP + 0.5), xlabel="años reales",
               ylabel="años predichos", title=f"{MODELS[key]}\nMAE = {mae:.3f} años")
        ax.set_aspect("equal")
    axes.flat[0].legend(loc="upper left", fontsize=8)
    for ax in list(axes.flat)[n:]:
        ax.set_visible(False)
    fig.suptitle(f"Predicho vs. real en test (n = {len(preds[models[0]])})", y=1.0)
    fig.tight_layout()
    return fig


# ── 4. MAE por banda y por ocupación ─────────────────────────────────────────
def _grouped_bars(ax, table: pd.DataFrame, xlabels: list[str], title: str) -> None:
    k = len(table)
    width = 0.8 / k
    x = np.arange(table.shape[1])
    for i, key in enumerate(table.index):
        ax.bar(x + (i - (k - 1) / 2) * width, table.loc[key].values, width=width * 0.92, color=COLORS[key],
               label=MODELS[key])
    ax.set_xticks(x, xlabels)
    ax.set(title=title, ylabel="MAE (años)")


def fig_mae_band_occupation(include_median: bool = True) -> plt.Figure | None:
    band = _by_model_table(U.TABLES_DIR / "mae_by_band.csv")
    occ = _by_model_table(U.TABLES_DIR / "mae_by_occupation.csv")
    if band is None and occ is None:
        return None
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.4))
    drop = [] if include_median else ["median"]
    if band is not None:
        b = band.drop(index=drop, errors="ignore")[[c for c in BANDS if c in band.columns]]
        _grouped_bars(axes[0], b, [f"{c} años" for c in b.columns], "MAE por banda de experiencia real")
    if occ is not None:
        o = occ.drop(index=drop, errors="ignore")
        _grouped_bars(axes[1], o, [OCC_SHORT.get(c, c) for c in o.columns], "MAE por ocupación")
        axes[1].tick_params(axis="x", labelsize=8.5)
    handles, labels = axes[0 if band is not None else 1].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=len(labels), bbox_to_anchor=(0.5, -0.02))
    fig.tight_layout(rect=(0, 0.07, 1, 1))
    return fig


# ── 5. Matriz de confusión de bandas ─────────────────────────────────────────
def confusion_table(key: str) -> pd.DataFrame | None:
    df = read_csv(U.TABLES_DIR / f"confusion_{key}.csv", index_col=0)
    if df is None:  # se reconstruye desde las predicciones si la tabla no existe
        preds = load_predictions().get(key)
        if preds is None:
            return None
        from src.model_common import confusion_matrix_bands
        df = confusion_matrix_bands(preds["y_true"], preds["y_pred"])
    df.index, df.columns = df.index.astype(str), df.columns.astype(str)
    return df


def fig_confusion(models: list[str] | None = None) -> plt.Figure | None:
    tables = {k: confusion_table(k) for k in (models or list(MODELS))}
    tables = {k: v for k, v in tables.items() if v is not None}
    if not tables:
        return None
    n = len(tables)
    cols = min(n, 3)
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(4.2 * cols, 3.9 * rows), squeeze=False)
    for ax, (key, cm) in zip(axes.flat, tables.items()):
        m = cm.values.astype(float)
        share = m / np.maximum(m.sum(axis=1, keepdims=True), 1)
        ax.imshow(share, cmap="Blues", vmin=0, vmax=1)
        for i in range(m.shape[0]):
            for j in range(m.shape[1]):
                ax.text(j, i, f"{int(m[i, j])}", ha="center", va="center", fontsize=9,
                        color="white" if share[i, j] > 0.55 else INK)
        ax.set_xticks(range(len(cm.columns)), cm.columns)
        ax.set_yticks(range(len(cm.index)), cm.index)
        ax.grid(False)
        acc = np.trace(m) / m.sum()
        ax.set(title=f"{MODELS[key]}\nexactitud de banda = {acc:.1%}", xlabel="banda predicha", ylabel="banda real")
    for ax in list(axes.flat)[n:]:
        ax.set_visible(False)
    fig.tight_layout()
    return fig


# ── 6. Ganancia de BERT con IC 95 % ──────────────────────────────────────────
def bert_gain_table() -> pd.DataFrame | None:
    df = read_csv(U.TABLES_DIR / "bootstrap_bert_vs_baselines.csv")
    if df is None:
        return None
    df["key"] = df["baseline"].map(lambda b: TABLE_LABELS.get(b, b))
    return df


def fig_bert_gain() -> plt.Figure | None:
    df = bert_gain_table()
    if df is None:
        return None
    fig, ax = plt.subplots(figsize=(8.5, 3.4))
    y = np.arange(len(df))
    for i, r in df.iterrows():
        c = COLORS.get(r["key"], MUTED)
        ax.plot([r["ci95_low"], r["ci95_high"]], [i, i], color=c, lw=2.5, solid_capstyle="round")
        ax.plot(r["delta_MAE"], i, "o", color=c, markersize=9, markeredgecolor="white", markeredgewidth=2)
        ax.text(r["ci95_high"], i, f"  {r['delta_MAE']:+.3f}  [{r['ci95_low']:.3f}; {r['ci95_high']:.3f}]",
                va="center", fontsize=9, color=INK)
    ax.axvline(0, color=MUTED, lw=1)
    ax.set_yticks(y, [f"vs. {b}" for b in df["baseline"]])
    ax.invert_yaxis()
    lo, hi = df["ci95_low"].min(), df["ci95_high"].max()
    ax.set_xlim(min(lo, 0) - 0.3, hi + 1.6)
    ax.set(title="Ganancia de BERT: ΔMAE = MAE(baseline) − MAE(BERT), IC 95 % bootstrap pareado (2000)",
           xlabel="ΔMAE (años)  ·  > 0 = BERT mejor")
    ax.title.set_fontsize(10)
    fig.tight_layout()
    return fig


# ── 7. CV de ejemplo con cajas de PaddleOCR ──────────────────────────────────
def find_example_cv() -> str | None:
    """Primer id de test con JSON de OCR o imagen local (None si no hay ninguno)."""
    meta = load_meta()
    ids = meta.loc[meta["split"] == "test", "id"].tolist() if meta is not None else []
    for cv_id in ids:
        if (U.OCR_DIR / f"{cv_id}.json").exists() or (U.RAW_IMAGES_DIR / f"{cv_id}.png").exists():
            return cv_id
    return None


def draw_ocr_boxes(lines: list[dict], image=None, image_size=None, title: str = "") -> plt.Figure:
    """Dibuja las cajas de PaddleOCR (``lines`` con text/confidence/box/row) sobre la imagen o, sin imagen, sobre un
    lienzo en blanco con el texto reconocido dentro de cada caja. El número es el orden de lectura."""
    if image is not None:
        w, h = image.size
    elif image_size:
        w, h = image_size
    else:
        w = max((ln["box"][2] for ln in lines), default=800) + 20
        h = max((ln["box"][3] for ln in lines), default=1000) + 20
    fig, ax = plt.subplots(figsize=(7, 7 * h / max(w, 1)))
    if image is not None:
        ax.imshow(image)
    else:
        ax.add_patch(plt.Rectangle((0, 0), w, h, facecolor="white", edgecolor=GRID))
    for i, ln in enumerate(lines):
        x1, y1, x2, y2 = ln["box"]
        ax.add_patch(plt.Rectangle((x1, y1), x2 - x1, y2 - y1, fill=False, edgecolor=COLORS[BERT_KEY], lw=1))
        ax.text(x1 - 4, y1 + (y2 - y1) / 2, str(i + 1), ha="right", va="center", fontsize=5, color="#e34948")
        if image is None:
            ax.text(x1 + 2, y1 + (y2 - y1) / 2, ln["text"], va="center", fontsize=4.5, color=INK, clip_on=True)
    ax.set_xlim(0, w)
    ax.set_ylim(h, 0)
    ax.axis("off")
    ax.set_title(title, fontsize=9)
    fig.tight_layout()
    return fig


def fig_example_cv(cv_id: str | None = None) -> plt.Figure | None:
    cv_id = cv_id or find_example_cv()
    if cv_id is None:
        return None
    js = read_json(U.OCR_DIR / f"{cv_id}.json")
    img_path = U.RAW_IMAGES_DIR / f"{cv_id}.png"
    image = None
    if img_path.exists():
        from PIL import Image
        image = Image.open(img_path).convert("RGB")
    if js is None:
        if image is None:
            return None
        fig, ax = plt.subplots(figsize=(7, 9))
        ax.imshow(image)
        ax.axis("off")
        ax.set_title(f"CV {cv_id} (sin JSON de OCR: solo la imagen)", fontsize=9)
        return fig
    src = "imagen original" if image is not None else "reconstruido desde el JSON de OCR (sin imagen local)"
    return draw_ocr_boxes(js["lines"], image, js.get("image_size"),
                          f"CV {cv_id} — {len(js['lines'])} cajas de PaddleOCR, {src}")


# ── 8. Pregunta 4: equidad de BERT por sexo y raza ───────────────────────────
def load_demographics() -> pd.DataFrame | None:
    """id + columnas sex/race (o equivalentes gender/ethnicity) si existen localmente."""
    for path in (DEMOGRAPHICS_CSV, U.METADATA_CSV):
        df = read_csv(path, dtype={"id": str})
        if df is None:
            continue
        ren = {}
        for c in df.columns:
            lc = c.lower()
            if lc in ("sex", "gender") and "sex" not in ren.values():
                ren[c] = "sex"
            elif lc in ("race", "ethnicity", "race_ethnicity") and "race" not in ren.values():
                ren[c] = "race"
        if ren:
            return df.rename(columns=ren)[["id", *ren.values()]]
    return None


def fairness_group_table(df: pd.DataFrame, col: str) -> pd.DataFrame:
    g = df.groupby(col).agg(n=("error", "size"), MAE=("error", lambda e: e.abs().mean()),
                            error_medio=("error", "mean"), y_real_medio=("y_true", "mean"))
    g.loc["TOTAL"] = [len(df), df["error"].abs().mean(), df["error"].mean(), df["y_true"].mean()]
    g["n"] = g["n"].astype(int)
    g.index.name = col
    return g.round(4).reset_index()


def compute_fairness(save: bool = True) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    """Reutiliza las tablas guardadas; si no existen y hay datos demográficos, las calcula y guarda."""
    sex, race = read_csv(FAIRNESS_SEX_CSV), read_csv(FAIRNESS_RACE_CSV)
    if sex is not None and race is not None:
        return sex, race
    demo, bert = load_demographics(), load_predictions().get(BERT_KEY)
    if demo is None or bert is None:
        return sex, race
    df = bert.merge(demo, on="id", how="inner")
    out = []
    for col, path in (("sex", FAIRNESS_SEX_CSV), ("race", FAIRNESS_RACE_CSV)):
        if col not in df.columns:
            out.append(None)
            continue
        t = fairness_group_table(df, col)
        if save:
            t.to_csv(path, index=False)
        out.append(t)
    return out[0], out[1]


def fig_fairness() -> plt.Figure | None:
    sex, race = compute_fairness(save=False)
    tables = [(t, c) for t, c in ((sex, "sex"), (race, "race")) if t is not None]
    if not tables:
        return None
    fig, axes = plt.subplots(1, len(tables), figsize=(6.2 * len(tables), 3.8), squeeze=False)
    for ax, (t, col) in zip(axes.flat, tables):
        t = t[t[col] != "TOTAL"]
        y = np.arange(len(t))
        ax.barh(y - 0.2, t["MAE"], height=0.38, color=COLORS[BERT_KEY], label="MAE")
        ax.barh(y + 0.2, t["error_medio"], height=0.38, color=COLORS["tfidf_ridge"], label="error medio (pred − real)")
        ax.set_yticks(y, [f"{g} (n={n})" for g, n in zip(t[col], t["n"])])
        ax.invert_yaxis()
        ax.axvline(0, color=MUTED, lw=1)
        ax.set(title=f"BERT en test por {'sexo' if col == 'sex' else 'raza'}", xlabel="años")
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2, fontsize=8)
    fig.tight_layout()
    return fig


# ── main ─────────────────────────────────────────────────────────────────────
FIGURES = {
    "exp_year_distribution.png": fig_exp_distribution,
    "ocr_quality_by_occupation.png": fig_ocr_quality,
    "pred_vs_real.png": fig_pred_vs_real,
    "mae_by_band_occupation.png": fig_mae_band_occupation,
    "confusion_bands.png": fig_confusion,
    "bert_gain_ci.png": fig_bert_gain,
    "example_cv_ocr_boxes.png": fig_example_cv,
    "fairness_bert.png": fig_fairness,
}


def main() -> int:
    U.FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    sex, race = compute_fairness(save=True)
    print("Equidad (Pregunta 4):", "fairness_by_sex.csv / fairness_by_race.csv guardados" if sex is not None
          else "PENDIENTE: faltan sex/race (python scripts/fetch_demographics.py)")
    for name, fn in FIGURES.items():
        fig = fn()
        if fig is None:
            print(f"  omitida {name}: faltan sus datos de entrada")
            continue
        fig.savefig(U.FIGURES_DIR / name, bbox_inches="tight")
        plt.close(fig)
        print(f"  guardada output/figures/{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

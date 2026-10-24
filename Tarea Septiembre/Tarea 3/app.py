"""App de Streamlit (Persona 3): problema, OCR y EDA, resultados de los modelos y estimador interactivo.

Ejecutar desde Tarea 3/:   streamlit run app.py

Todo lo que se muestra sale de los archivos reales de output/ y data/; si falta alguno, la sección muestra un aviso y
el resto de la app sigue funcionando. El estimador reutiliza el OCR (src.ocr_extraction) y la limpieza
(src.preprocessing) del pipeline. Los pesos de BERT se leen de models/bert/ (no están en git).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from src import utils as U
from src import visualization as V

st.set_page_config(page_title="Años de experiencia desde CVs", page_icon="📄", layout="wide")

BERT_KEY, MODELS = V.BERT_KEY, V.MODELS


# ── Utilidades de la app ─────────────────────────────────────────────────────
def show_fig(fig, caption: str | None = None, missing: str = "Faltan los datos de entrada de este gráfico.") -> None:
    if fig is None:
        st.warning(missing)
        return
    st.pyplot(fig, clear_figure=True, width="stretch")
    V.plt.close(fig)
    if caption:
        st.caption(caption)


def show_table(df: pd.DataFrame | None, caption: str | None = None, missing: str = "Falta el archivo de esta tabla.",
               **kw) -> None:
    if df is None:
        st.warning(missing)
        return
    st.dataframe(df, width="stretch", **kw)
    if caption:
        st.caption(caption)


@st.cache_data
def metrics(name: str) -> dict:
    return V.read_json(U.METRICS_DIR / name) or {}


@st.cache_data
def table(name: str, **kw) -> pd.DataFrame | None:
    return V.read_csv(U.TABLES_DIR / name, **kw)


@st.cache_data
def test_predictions() -> dict[str, pd.DataFrame]:
    return V.load_predictions("test")


@st.cache_data
def clean_texts() -> pd.Series:
    df = V.read_csv(U.CLEAN_TEXTS_CSV, dtype={"id": str})
    return df.set_index("id")["clean_text"] if df is not None else pd.Series(dtype=str)


@st.cache_data
def error_profile(err: pd.DataFrame) -> pd.DataFrame | None:
    """MAE de BERT según el n.º de rangos de fechas de empleo del CV y si tiene huecos (> 3 meses) entre empleos."""
    from src.model_common import job_ranges
    texts = clean_texts()
    if texts.empty:
        return None
    rows = []
    for cv_id, e in zip(err["id"], err["error BERT"]):
        r = sorted(job_ranges(texts.get(cv_id, "")))
        gap = any(r[k + 1][0] - r[k][1] > 0.25 for k in range(len(r) - 1))
        rows.append({"empleos": len(r), "huecos": "con huecos" if gap else "sin huecos", "ae": abs(e)})
    df = pd.DataFrame(rows)
    return (df.groupby(["empleos", "huecos"]).agg(n=("ae", "size"), MAE_BERT=("ae", "mean"))
            .round(3).reset_index())


def fmt(x, nd=3) -> str:
    return "—" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:.{nd}f}"


comparison = table("model_comparison.csv")
cmp_by_key = comparison.set_index("model") if comparison is not None else None


def mae_of(key: str) -> float | None:
    if cmp_by_key is None or key not in cmp_by_key.index:
        return None
    return float(cmp_by_key.loc[key, "MAE"])


# ── Modelos para el estimador ────────────────────────────────────────────────
def bert_path() -> Path | None:
    for p in (U.BERT_DIR / V.BERT_TAG, U.BERT_DIR):
        if (p / "config.json").exists() and any((p / w).exists() for w in ("model.safetensors", "pytorch_model.bin")):
            return p
    return None


@st.cache_resource(show_spinner="Cargando modelos…")
def load_models(with_embeddings: bool) -> tuple[dict, dict]:
    """Carga cada modelo disponible. Los baselines se leen de models/baselines/*.joblib; si no están, se reentrenan
    con train exactamente como en src.baselines (mismo α elegido en val, guardado en baselines_report.json)."""
    import joblib
    from src import model_common as M

    models, notes = {}, {}
    report = metrics("baselines_report.json")
    train = None

    def get_train():
        nonlocal train
        if train is None:
            train = M.load_split("train")
        return train

    def joblib_or(name, build):
        path = U.BASELINES_DIR / f"{name}.joblib"
        if path.exists():
            return joblib.load(path), "cargado de models/baselines/"
        model = build()
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, path)
        return model, "reentrenado con train (no había .joblib) y guardado en models/baselines/"

    try:
        models["median"], notes["median"] = joblib_or(
            "median", lambda: M.MedianModel().fit(None, get_train()["exp_year"]))
    except Exception as e:  # noqa: BLE001
        notes["median"] = f"no disponible: {e}"
    models["rule_dates"], notes["rule_dates"] = M.RuleModel(report.get("rule_dates", {}).get("chosen", "sum")), \
        "regla sin entrenamiento"
    try:
        from src.baselines import make_tfidf
        alpha = report.get("tfidf_ridge", {}).get("alpha", 0.1)
        models["tfidf_ridge"], notes["tfidf_ridge"] = joblib_or("tfidf_ridge", lambda: M.SklearnTextModel(
            make_tfidf(alpha, True).fit(get_train()["text"].tolist(), get_train()["exp_year"])))
    except Exception as e:  # noqa: BLE001
        notes["tfidf_ridge"] = f"no disponible: {e}"
    emb_path = U.BASELINES_DIR / "emb_minilm_ridge.joblib"
    if emb_path.exists() or with_embeddings:
        try:
            from sklearn.linear_model import Ridge

            def build_emb():
                emb = M.EmbeddingRidgeModel()
                tr = get_train()
                emb.ridge = Ridge(alpha=report.get("emb_minilm_ridge", {}).get("alpha", 0.03)).fit(
                    emb.embed(tr["text"].tolist()), tr["exp_year"])
                return emb
            models["emb_minilm_ridge"], notes["emb_minilm_ridge"] = joblib_or("emb_minilm_ridge", build_emb)
        except Exception as e:  # noqa: BLE001
            notes["emb_minilm_ridge"] = f"no disponible: {e}"
    else:
        notes["emb_minilm_ridge"] = ("no hay models/baselines/emb_minilm_ridge.joblib; actívalo en la barra lateral "
                                     "para reentrenarlo (~4 min en CPU, descarga all-MiniLM-L6-v2)")
    path = bert_path()
    if path is None:
        notes[BERT_KEY] = "faltan los pesos en models/bert/ (config.json + model.safetensors); ver README"
    else:
        try:
            from src.train_bert import BertRegressor
            models[BERT_KEY], notes[BERT_KEY] = BertRegressor(path), f"pesos de {path.relative_to(U.ROOT_DIR)}"
        except Exception as e:  # noqa: BLE001
            notes[BERT_KEY] = f"no se pudo cargar: {e}"
    return models, notes


@st.cache_resource(show_spinner="Cargando PaddleOCR (la primera vez descarga los modelos)…")
def load_ocr():
    import platform
    from src.ocr_extraction import PROFILES, build_ocr
    if platform.system() != "Windows":
        return build_ocr("default")
    # Paddle 3.x en CPU Windows falla con oneDNN (ConvertPirAttribute2RuntimeAttribute): misma configuración que
    # build_ocr, sin oneDNN.
    from paddleocr import PaddleOCR
    return PaddleOCR(lang="en", use_doc_orientation_classify=False, use_doc_unwarping=False,
                     use_textline_orientation=False, enable_mkldnn=False, **PROFILES["default"])


def file_to_png(uploaded) -> Path:
    """Guarda la subida como PNG temporal; un PDF se rasteriza (primera página, 200 dpi) con PyMuPDF."""
    tmp = Path(tempfile.mkdtemp())
    data = uploaded.getvalue()
    out = tmp / "cv.png"
    if uploaded.name.lower().endswith(".pdf"):
        import fitz  # PyMuPDF
        with fitz.open(stream=data, filetype="pdf") as doc:
            doc[0].get_pixmap(dpi=200).save(out)
    else:
        from PIL import Image
        import io
        Image.open(io.BytesIO(data)).convert("RGB").save(out)
    return out


# ── Cabecera ─────────────────────────────────────────────────────────────────
st.title("📄 Años de experiencia a partir de imágenes de CV")
st.caption("PopResume · PaddleOCR → texto limpio → BERT regresor vs. baselines · Tarea 3 (HW_04)")

tab1, tab2, tab3, tab4 = st.tabs(["1 · Problema y metodología", "2 · OCR y análisis exploratorio",
                                  "3 · Resultados de modelos", "4 · Estimador interactivo"])

# ════════════════════════════════════════════════════════════════════════════
with tab1:
    samp, ocr_rep, split = metrics("sampling_report.json"), metrics("ocr_report.json"), metrics("split_report.json")
    st.header("Problema")
    st.markdown(
        "Predecir, a partir de la **imagen de su CV**, los **años de experiencia laboral** de una persona "
        "(la variable objetivo, continua entre 0 y 20), sin que el CV diga explícitamente cuántos años "
        "tiene. Un sistema así sirve para "
        "**pre-llenar perfiles** o **priorizar la revisión** de CVs en reclutamiento; **nunca** para decidir una "
        "contratación (ver Pregunta 4).")
    c = st.columns(3)
    c[0].metric("CVs muestreados", f"{samp.get('total_cvs', '—')}")
    c[1].metric("Ocupaciones", len(samp.get("per_occupation", {})) or "—")
    c[2].metric("MAE de BERT en test", f"{fmt(mae_of(BERT_KEY))} años")
    sizes = split.get("sizes", {})
    c = st.columns(3)
    for col, name in zip(c, ("train", "val", "test")):
        col.metric(f"CVs en {name}", sizes.get(name, "—"))

    st.header("Metodología")
    st.markdown(f"""
1. **Muestreo** — PopResume (`sumin-yu/PopResume`, dataset sintético restringido) por *streaming*: 800 CVs **sin foto**
   por cada una de 5 ocupaciones (`shuffle(seed=42, buffer_size=5000)`). Solo {samp.get('n_at_or_above_cap', '—')} CVs
   ({samp.get('share_at_or_above_cap', 0):.2%}) llegan al tope de 20 años, así que el tope se mantiene.
2. **OCR** — PaddleOCR {ocr_rep.get('hardware', {}).get('paddleocr_version', '3.7')} (perfil por defecto) en CPU,
   un JSON por CV con texto, caja y confianza de cada línea. **Orden de lectura:** de arriba a abajo y, a la misma
   altura (|Δy del centro| < 15 px), de izquierda a derecha.
3. **Calidad del OCR** — CER/WER contra el texto de referencia del dataset y % de años (AAAA) leídos bien.
4. **Limpieza** — umbral de confianza 0,5, unión de líneas rotas, normalización de rangos de fechas, eliminación de PII
   (cabecera con nombre, ciudad, teléfono y email) y enmascarado `[MASKED]` de frases como «X years of experience» o
   la edad. **Las fechas de empleo y graduación se conservan**: de ahí sale la experiencia.
5. **Split** — 70/15/15 estratificado por ocupación × banda (0-2, 3-5, 6-10, 11-20), semilla 42.
6. **Modelos** (solo train para entrenar, val para elegir hiperparámetros, test una sola vez): mediana,
   TF-IDF + Ridge, MiniLM congelado + Ridge, **BERT (all-MiniLM-L6-v2) ajustado como regresor** (`num_labels=1`, MSE,
   target y/20) y, como *bonus*, una regla que suma las duraciones de los rangos de fechas.
7. **Evaluación** — MAE (principal), RMSE, R², % dentro de ±1/±2/±3 años, exactitud y F1 por bandas, IC 95 % de la
   ganancia de BERT con bootstrap pareado, y 4 preguntas analíticas (qué aprende BERT, costo del ruido OCR,
   sensibilidad metodológica, equidad y ética).
""")
    st.info("**Sexo y raza nunca son entradas de ningún modelo.** Solo se usan después de predecir, para auditar si el "
            "error es parejo entre grupos (Pregunta 4).")

# ════════════════════════════════════════════════════════════════════════════
with tab2:
    st.header("Distribución de la variable objetivo")
    show_fig(V.fig_exp_distribution(),
             "Histograma de los años de experiencia de los 4000 CVs y caja por ocupación. La mayoría tiene menos de 10 años y la "
             "cola llega a 25,5; como menos del 1 % supera 20, el tope de 20 casi no recorta información.")

    st.header("Calidad del OCR")
    c1, c2 = st.columns([1, 1.3])
    with c1:
        show_table(table("ocr_quality_summary.csv", index_col=0),
                   "CER y WER sobre los 4000 CVs (0 = idéntico a la referencia). La mediana y el p90 son 0: casi "
                   "todos los CVs se leen perfecto.")
        ocr_rep = metrics("ocr_report.json")
        if ocr_rep:
            st.markdown(f"- CVs procesados: **{ocr_rep.get('cvs_processed')}/{ocr_rep.get('cvs_expected')}** "
                        f"(fallidos: {ocr_rep.get('cvs_failed_or_pending')})\n"
                        f"- Tiempo medio por CV: **{ocr_rep.get('mean_seconds_per_cv')} s** (CPU)\n"
                        f"- Confianza media: **{ocr_rep.get('mean_confidence')}**, "
                        f"{ocr_rep.get('mean_lines_per_cv')} líneas por CV")
    with c2:
        q = V.ocr_quality_by_occupation()
        show_table(q[["n", "cer_%", "wer_%", "cvs_con_error", "years_accuracy"]].round(4) if q is not None else None,
                   "Por ocupación, recalculado sin redondear. Desarrolladores y docentes concentran los pocos "
                   "CVs con algún error de carácter; los años se leen bien al 100 % en todas.")
    show_fig(V.fig_ocr_quality(),
             "CER/WER medios (en %) y años leídos bien por ocupación. Las barras son diminutas porque PopResume son "
             "plantillas limpias de una columna: el OCR no es el cuello de botella del problema.")

    st.subheader("CV de ejemplo con las cajas de PaddleOCR")
    show_fig(V.fig_example_cv(),
             "Cada caja es una línea detectada; el número es el orden de lectura (arriba→abajo, izquierda→derecha).",
             missing="No hay imágenes (`data/raw/images/`) ni JSON de OCR (`data/ocr/`) en este equipo: se comparten "
                     "fuera de git. Sube un CV en la pestaña 4 para ver sus cajas.")

    st.header("Limpieza del texto")
    pre = metrics("preprocessing_report.json")
    if pre:
        c = st.columns(4)
        c[0].metric("Umbral de confianza", pre.get("conf_threshold"))
        c[1].metric("% líneas descartadas", f"{pre.get('pct_lines_dropped_by_confidence', 0):.1f} %")
        c[2].metric("CVs enmascarados", f"{pre.get('cvs_masked')} ({pre.get('pct_cvs_masked', 0):.1f} %)")
        c[3].metric("CVs con fecha truncada", pre.get("cvs_with_truncated_date_range"))
        st.caption("Ningún CV de PopResume dice «X years of experience» ni la edad, así que el enmascarado no tuvo nada "
                   "que tapar (los patrones siguen activos). Ningún CV perdió un año al limpiar.")
    show_table(table("confidence_threshold_analysis.csv"),
               "Qué pasa al subir el umbral de confianza: por encima de 0,95 se empiezan a borrar líneas correctas y "
               "el CER sube. Por eso se dejó 0,5 (red de seguridad que no descarta nada).")

    st.header("Split train / val / test")
    sb = table("split_balance.csv")
    show_table(sb[sb["level"] != "occupation x band"] if sb is not None else None,
               "Proporción de cada ocupación y banda en cada conjunto. La diferencia máxima es de 0,33 puntos "
               "porcentuales: los tres conjuntos son comparables.")

# ════════════════════════════════════════════════════════════════════════════
with tab3:
    st.header("Comparación de modelos en test (n = 600)")
    if comparison is not None:
        cmp = comparison.copy()
        cmp["label"] = cmp["model"].map(MODELS).fillna(cmp["label"])
        cmp = cmp.set_index("label").drop(columns=["model", "n_test"])
        for col in ("acc_pm1", "acc_pm2", "acc_pm3", "band_accuracy"):
            cmp[col] = (cmp[col] * 100).round(1)
        cmp = cmp.rename(columns={"acc_pm1": "±1 año %", "acc_pm2": "±2 %", "acc_pm3": "±3 %",
                                  "band_accuracy": "acc. bandas %", "band_macro_f1": "F1 macro bandas",
                                  "bias": "sesgo (pred−real)"})
        show_table(cmp, "MAE = error absoluto medio en años (menor es mejor). BERT es el mejor modelo aprendido; la "
                        "regla de fechas (bonus, sin aprendizaje) es aún mejor porque los años de experiencia son casi la suma de "
                        "las duraciones de los empleos.")
    else:
        st.warning("Falta output/tables/model_comparison.csv")

    st.subheader("Predicho vs. real")
    preds = test_predictions()
    avail = [k for k in MODELS if k in preds]
    if avail:
        key = st.selectbox("Modelo", avail, format_func=MODELS.get, index=0)
        c1, c2 = st.columns([1, 1.4])
        with c1:
            show_fig(V.fig_pred_vs_real([key]),
                     "Cada punto es un CV de test; sobre la línea de 45° la predicción es perfecta. La mediana es una "
                     "línea horizontal; BERT se pega a la diagonal y se abre un poco en la banda alta.")
        with c2:
            d = preds[key]
            st.markdown(f"**{MODELS[key]}** — MAE {d['error'].abs().mean():.3f} · sesgo {d['error'].mean():+.3f} años · "
                        f"{(d['error'].abs() <= 2).mean():.1%} dentro de ±2 años")
            show_fig(V.fig_confusion([key]), "Matriz de confusión de bandas de este modelo (filas = banda real).")
    else:
        st.warning("Faltan las predicciones en output/predictions/.")

    st.subheader("MAE por banda y por ocupación")
    show_med = st.checkbox("Incluir la mediana (aplasta la escala)", value=False)
    show_fig(V.fig_mae_band_occupation(include_median=show_med),
             "Todos los modelos aprendidos fallan más en 11-20 años (la banda con menos CVs de entrenamiento). Por "
             "ocupación el error es parejo: ninguna ocupación queda claramente peor servida.")

    st.subheader("Matrices de confusión de bandas")
    show_fig(V.fig_confusion(),
             "Número de CVs por banda real (filas) y predicha (columnas). Los errores de BERT caen solo en la banda "
             "vecina, casi siempre hacia arriba (sobrestima levemente).")

    st.subheader("Ganancia de BERT con IC 95 %")
    show_fig(V.fig_bert_gain(),
             "Si el intervalo no toca 0, la diferencia es significativa. BERT gana a los tres baselines aprendidos y "
             "pierde contra la regla de fechas.")
    show_table(V.bert_gain_table().drop(columns="key") if V.bert_gain_table() is not None else None)

    st.header("Preguntas analíticas")
    with st.expander("Pregunta 1 — ¿Qué aprende BERT que los baselines no?", expanded=True):
        st.markdown(
            "BERT baja el MAE de 1,018 (TF-IDF) a **0,296** (−71 %, IC 95 % de la diferencia [0,65; 0,80]) y ayuda en "
            "todas las bandas, sobre todo en 11-20 (0,68 vs. 1,56). Pero la **prueba de perturbación** muestra que **no "
            "resta fechas**: si se suman 5 años a todas las fechas (la duración real no cambia) su predicción cambia "
            "~2,4 años, y si se borra un empleo casi no se mueve (pendiente −0,01 cuando debería ser 1). Aprendió a "
            "reconocer **años absolutos** (todos los CVs terminan en 2023.01), no aritmética: funciona en este dataset "
            "pero no generalizaría a otra fecha de corte.")
        show_table(table("q1_perturbation.csv"))
    with st.expander("Pregunta 2 — ¿Cuánto cuesta el ruido del OCR?"):
        st.markdown(
            "Casi nada: con el formato armonizado, la brecha OCR − referencia es ≤ 0,003 años en todos los modelos "
            "(CER medio 0,0001; solo 14 de 600 CVs de test tienen algún error). Lo que sí importa es el **formato**: "
            "el MAE de BERT sube de 0,296 a 0,358 si solo cambian viñetas y saltos de línea, porque se entrenó con el "
            "estilo exacto del OCR. La regla de fechas es la única afectada por ruido real (fechas truncadas).")
        show_table(table("q2_ocr_noise.csv"))
    with st.expander("Pregunta 3 — Sensibilidad metodológica"):
        st.markdown(
            "- **Quitar los números** empeora TF-IDF 75 % (1,02 → 1,78): los años son casi toda la señal.\n"
            "- **Umbral de confianza alto (0,99)** borra texto correcto: la regla pasa de 0,02 a 1,87 y BERT a 1,17.\n"
            "- **Texto crudo** (con cabecera) apenas daña a TF-IDF (1,08) pero sí a BERT (1,75), que no vio ese formato.\n"
            "- **Texto largo:** ningún CV supera 161 tokens, así que `head`, `head_tail` y *chunking* dan lo mismo con "
            "`max_len=256`; con topes artificiales `head` se degrada más despacio.\n"
            "- **MSE vs. Huber:** no se entrenó Huber (≈2 h en CPU); queda como limitación.")
        show_table(table("q3_sensitivity.csv"))
    with st.expander("Pregunta 4 — Equidad y ética", expanded=True):
        sex, race = V.compute_fairness(save=False)
        if sex is None and race is None:
            st.warning("Faltan `output/tables/fairness_by_sex.csv` y `fairness_by_race.csv`. Para generarlas: "
                       "`python scripts/fetch_demographics.py` (token HF) y `python -m src.visualization`.")
        else:
            c1, c2 = st.columns(2)
            with c1:
                show_table(sex, "MAE y error medio (pred − real) de BERT por sexo en test, con n por grupo.")
            with c2:
                show_table(race, "Lo mismo por raza. Grupos con n pequeño tienen métricas poco estables.")
            show_fig(V.fig_fairness())
        st.markdown("""
**Usuarios posibles y para qué.** Equipos de reclutamiento y plataformas de empleo, para **pre-llenar** el campo «años
de experiencia» de un perfil o **ordenar la cola de revisión** humana. Nunca para filtrar automáticamente ni decidir
una contratación: la estimación es un apoyo que una persona confirma.

**Costo de los errores.** Un error de **±2 años** rara vez cambia el tramo de un puesto (junior/semi-senior) y se corrige
al revisar; uno de **±5 años** sí cambia de categoría y puede excluir a alguien o asignarle un salario equivocado.
**Subestimar es peor** para el candidato (puede quedar fuera de la lista corta sin que nadie lo revise);
sobrestimar se detecta en la entrevista, aunque crea expectativas falsas. BERT tiene un sesgo medio de
**+0,21 años** (sobrestima levemente) y ningún error en test supera 2 años.

**Resultados de equidad (BERT, test).** IC 95 % por bootstrap de la diferencia entre grupos (2000 remuestreos).
- **Sexo: no hay diferencia.** MAE 0,299 en mujeres (n = 299) y 0,294 en hombres (n = 301); ΔMAE +0,005, IC
  [−0,039; 0,048]. A ambos grupos se los **sobrestima** lo mismo (~+0,21 años, unos 2,6 meses).
- **Raza: Asian/Pacific Islander tiene más error.** MAE 0,361 (n = 91) frente a 0,282 en White (n = 462): **+0,079 años
  (~1 mes)**, IC [0,016; 0,147], la única diferencia significativa. También es el grupo **más sobrestimado** (+0,288 vs.
  +0,208; Δ +0,080, IC [−0,003; 0,163], en el límite de la significancia).
- **Black es el grupo menos sobrestimado** (+0,134) y su MAE (0,307) es parecido al de White (Δ +0,025, IC
  [−0,049; 0,099]), pero con n = 47 la estimación es poco estable.
- **Ningún grupo se subestima en promedio**: BERT sobrestima a todos. Las brechas son de semanas a ~1 mes, muy lejos de
  los ±2 años que cambiarían una decisión.

**Por qué hay diferencias aunque sexo y raza no sean entradas.** El texto trae **proxies** del tipo de CV en que BERT
falla más: su error crece con el número de empleos (0,18 con 1, 0,64 con 4) y con los huecos de carrera (0,37 vs.
0,25). En test, el grupo Asian/Pacific Islander tiene más CVs en la banda 11-20 (25 % vs. 14 % en White), más empleos
(2,65 vs. 2,37), algo más de huecos (43 % vs. 39 %) y un 54 % son desarrolladores. Dentro de cada banda su MAE es
parecido al de White; si se reponderan sus bandas con la distribución de White, su MAE baja de 0,361 a ~0,310. Es decir,
**cerca de dos tercios de la brecha se debe a la composición** (CVs más largos y senior), no a que el modelo «vea» la
raza. Con datos reales los proxies (nombres, universidades, huecos por cuidado de hijos) pueden pesar más, así que la
auditoría por grupo debe repetirse antes de cualquier uso.

**Limitaciones.** Datos **sintéticos** (PopResume), solo **5 ocupaciones**, CVs de **EE. UU.** y solo en **inglés**, con
plantillas limpias de una columna y una fecha de corte común (2023.01). La muestra solo trae tres categorías de raza
(White, Asian/Pacific Islander, Black) y sexo binario, con grupos chicos en test. Los resultados no se pueden extrapolar
a CVs reales escaneados, de otros países, idiomas o formatos.
""")

# ════════════════════════════════════════════════════════════════════════════
with tab4:
    st.header("Estimador: sube un CV")
    with st.sidebar:
        st.subheader("Estimador")
        want_emb = st.checkbox("Incluir MiniLM congelado + Ridge (si no hay .joblib, lo reentrena: ~4 min)",
                               value=(U.BASELINES_DIR / "emb_minilm_ridge.joblib").exists())
    models, notes = load_models(want_emb)
    with st.expander("Estado de los modelos", expanded=not all(k in models for k in MODELS)):
        for k in MODELS:
            (st.success if k in models else st.warning)(f"**{MODELS[k]}** — {notes.get(k, 'no disponible')}")

    up = st.file_uploader("Imagen (PNG/JPG) o PDF del CV (se usa la primera página)", type=["png", "jpg", "jpeg", "pdf"])
    if up is not None:
        try:
            png = file_to_png(up)
        except Exception as e:  # noqa: BLE001
            st.error(f"No se pudo leer el archivo: {e}")
            png = None
        if png is not None:
            try:
                from src.ocr_extraction import ocr_one
                from src.preprocessing import clean_one
                with st.spinner("PaddleOCR leyendo el CV (≈30 s en CPU)…"):
                    res = ocr_one(load_ocr(), png)
                text, was_masked = clean_one(res["lines"])
            except Exception as e:  # noqa: BLE001
                st.error(f"PaddleOCR no está disponible o falló ({type(e).__name__}: {e}). Instala "
                         "`paddlepaddle` y `paddleocr` (ver README).")
                res = None
            if res is not None:
                c1, c2 = st.columns([1, 1])
                with c1:
                    from PIL import Image
                    show_fig(V.draw_ocr_boxes(res["lines"], Image.open(png).convert("RGB"),
                                              title=f"{len(res['lines'])} cajas · confianza media "
                                                    f"{res['mean_confidence']:.3f} · {res['ocr_time_seconds']} s"),
                             "Cajas detectadas por PaddleOCR y su orden de lectura.")
                with c2:
                    st.markdown("**Texto limpio que reciben los modelos** (sin PII; las fechas se conservan)")
                    if was_masked:
                        st.info("Se enmascararon frases que delatan la experiencia o la edad (`[MASKED]`).")
                    st.code(text or "(vacío)", language=None)
                    rows = []
                    for k in MODELS:
                        if k in models:
                            try:
                                rows.append({"modelo": MODELS[k], "años estimados": float(models[k].predict([text])[0]),
                                             "MAE en test": mae_of(k)})
                            except Exception as e:  # noqa: BLE001
                                rows.append({"modelo": MODELS[k], "años estimados": np.nan,
                                             "MAE en test": mae_of(k), "nota": str(e)})
                    if rows:
                        out = pd.DataFrame(rows).set_index("modelo")
                        st.dataframe(out.style.format({"años estimados": "{:.1f}", "MAE en test": "{:.3f}"}),
                                     width="stretch")
                        if BERT_KEY in models:
                            st.success(f"Estimación de BERT: **{out.loc[MODELS[BERT_KEY], 'años estimados']:.1f} años** "
                                       f"(error típico en test ±{fmt(mae_of(BERT_KEY), 2)} años). Es un apoyo para "
                                       "pre-llenar o priorizar, no para decidir.")
                    if not text:
                        st.warning("El OCR no encontró texto: revisa la calidad de la imagen.")
                    st.caption("Los modelos se entrenaron con CVs sintéticos de PopResume (inglés, EE. UU., fechas "
                               "«AAAA.MM–AAAA.MM»); en CVs con otro formato la estimación puede ser poco fiable.")

    st.divider()
    st.header("Explorador de CVs de test")
    preds = test_predictions()
    texts = clean_texts()
    if BERT_KEY not in preds:
        st.warning("Faltan las predicciones de BERT (output/predictions/).")
    else:
        base = preds[BERT_KEY][["id", "occupation", "y_true", "y_pred", "error"]].rename(
            columns={"y_true": "años reales", "y_pred": "BERT", "error": "error BERT"})
        for k in MODELS:
            if k != BERT_KEY and k in preds:
                base = base.merge(preds[k][["id", "y_pred"]].rename(columns={"y_pred": MODELS[k]}), on="id", how="left")
        c = st.columns(3)
        occ = c[0].multiselect("Ocupación", U.OCCUPATIONS, default=U.OCCUPATIONS, format_func=V.OCC_SHORT.get)
        yr = c[1].slider("Años reales", 0.0, float(U.TARGET_CAP), (0.0, float(U.TARGET_CAP)), 0.5)
        err = c[2].slider("|error| de BERT (años)", 0.0, float(np.ceil(base["error BERT"].abs().max() * 10) / 10),
                          (0.0, float(np.ceil(base["error BERT"].abs().max() * 10) / 10)), 0.05)
        f = base[base["occupation"].isin(occ) & base["años reales"].between(*yr)
                 & base["error BERT"].abs().between(*err)].sort_values("error BERT", key=np.abs, ascending=False)
        st.caption(f"{len(f)} de {len(base)} CVs de test. Ordenados por |error| de BERT, de mayor a menor.")
        st.dataframe(f.round(2), width="stretch", hide_index=True, height=260)
        if len(f):
            sel = st.selectbox("Ver el texto de un CV", f["id"].tolist())
            r = f.set_index("id").loc[sel]
            st.markdown(f"**CV {sel}** · {V.OCC_SHORT.get(r['occupation'])} · real {r['años reales']:.2f} · "
                        f"BERT {r['BERT']:.2f} (error {r['error BERT']:+.2f})")
            st.code(texts.get(sel, "(texto no disponible)"), language=None)

        st.subheader("Ejemplos de aciertos y errores de BERT")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Mejores aciertos**")
            st.dataframe(base.loc[base["error BERT"].abs().nsmallest(5).index,
                                  ["id", "occupation", "años reales", "BERT", "error BERT"]].round(3),
                         hide_index=True, width="stretch")
            prof = error_profile(base[["id", "error BERT"]])
            if prof is not None:
                st.dataframe(prof, hide_index=True, width="stretch")
            st.caption("Hay aciertos casi exactos con 1 a 4 empleos, pero el error medio crece con el número de empleos "
                       "y con los huecos de carrera: con pocos rangos de fechas, ubicar el año del primer empleo basta "
                       "(lo que BERT aprendió, Pregunta 1); con muchos rangos y huecos, eso ya no alcanza.")
        with c2:
            st.markdown("**Mayores errores**")
            top = table("bert_top10_errors.csv", dtype={"id": str})
            show_table(top[["id", "occupation", "y_true", "y_pred", "error", "rule_pred", "cause"]] if top is not None
                       else None, hide_index=True)
            st.caption("Los 10 mayores errores son sobrestimaciones de 1,1–1,4 años en CVs con 4 empleos y 12–19 años: "
                       "5 tienen huecos de carrera (probablemente BERT cuenta desde el primer empleo, hueco incluido) y "
                       "5 son errores de aritmética con muchos empleos. La regla de fechas acierta en los 10.")

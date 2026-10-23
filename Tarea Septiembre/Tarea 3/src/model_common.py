"""Utilidades compartidas por los modelos (Persona 2): datos, texto de referencia limpio, métricas y predictores.

Todos los modelos (mediana, TF-IDF, embeddings, regla de fechas y BERT) exponen la misma interfaz
``predictor.predict(list[str]) -> np.ndarray`` (años de experiencia, ya recortados a [0, TARGET_CAP]).
Eso permite evaluarlos sobre texto OCR, texto de referencia y textos perturbados (Preguntas 1, 2 y 3) sin código extra.

La ENTRADA de los modelos es siempre texto: el OCR limpio (``clean_texts.csv``) o, solo para medir el costo del ruido
del OCR (Pregunta 2), el texto de referencia pasado por la MISMA limpieza.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src import utils as U
from src import preprocessing as P

BANDS = U.EXP_BAND_LABELS  # ['0-2', '3-5', '6-10', '11-20']
SPLITS = ("train", "val", "test")


# ── Datos ────────────────────────────────────────────────────────────────────
def clip_target(y) -> np.ndarray:
    return np.clip(np.asarray(y, dtype=float), 0, U.TARGET_CAP)


def clean_plain_text(text: str) -> str:
    """Aplica al texto de REFERENCIA exactamente la limpieza que ``preprocessing.clean_one`` aplica al OCR
    (sin el filtro por confianza, que no existe en el texto de referencia)."""
    text = P.normalize_date_ranges(P.fix_broken_lines(text))
    text = P.remove_pii(text)
    return P.tidy(P.mask_leaks(text))


def load_split(split: str, source: str = "ocr") -> pd.DataFrame:
    """Devuelve id, occupation, exp_year (recortado), band y ``text`` de un split.

    source='ocr'        → data/processed/clean_texts.csv (lo que ve el sistema real)
    source='reference'  → data/raw/reference_texts.csv limpiado igual (solo para la Pregunta 2)
    source='ocr_raw'    → OCR sin limpiar (full_text del JSON), para la sensibilidad de limpieza (Pregunta 3)
    """
    df = pd.read_csv(U.SPLITS_DIR / f"{split}.csv", dtype={"id": str})
    df["exp_year"] = clip_target(df["exp_year"])
    if source == "ocr":
        txt = pd.read_csv(U.CLEAN_TEXTS_CSV, dtype={"id": str}).set_index("id")["clean_text"]
    elif source == "reference":
        ref = pd.read_csv(U.REFERENCE_TEXTS_CSV, dtype={"id": str}).set_index("id")["text"]
        txt = ref.map(clean_plain_text)
    elif source == "ocr_raw":
        txt = pd.Series({i: U.read_json(U.OCR_DIR / f"{i}.json")["full_text"] for i in df["id"]})
    else:
        raise ValueError(source)
    df["text"] = df["id"].map(txt).fillna("")
    return df


def load_all(source: str = "ocr") -> dict[str, pd.DataFrame]:
    return {s: load_split(s, source) for s in SPLITS}


def to_band(y) -> np.ndarray:
    """Banda de experiencia de cada valor (misma regla que ``utils.assign_band``)."""
    return np.array([U.assign_band(float(v)) for v in np.asarray(y)])


# ── Métricas ─────────────────────────────────────────────────────────────────
def regression_metrics(y_true, y_pred) -> dict[str, float]:
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    err = y_pred - y_true
    ss_res, ss_tot = float((err ** 2).sum()), float(((y_true - y_true.mean()) ** 2).sum())
    out = {
        "MAE": float(np.abs(err).mean()),
        "RMSE": float(np.sqrt((err ** 2).mean())),
        "R2": 1 - ss_res / ss_tot if ss_tot > 0 else float("nan"),
        "bias": float(err.mean()),  # >0 = sobrestima
    }
    for k in (1, 2, 3):
        out[f"acc_pm{k}"] = float((np.abs(err) <= k).mean())
    tb, pb = to_band(y_true), to_band(y_pred)
    out["band_accuracy"] = float((tb == pb).mean())
    out["band_macro_f1"] = macro_f1(tb, pb)
    return out


def macro_f1(true_labels, pred_labels, labels=BANDS) -> float:
    f1s = []
    for lab in labels:
        tp = np.sum((true_labels == lab) & (pred_labels == lab))
        fp = np.sum((true_labels != lab) & (pred_labels == lab))
        fn = np.sum((true_labels == lab) & (pred_labels != lab))
        f1s.append(0.0 if tp == 0 else 2 * tp / (2 * tp + fp + fn))
    return float(np.mean(f1s))


def confusion_matrix_bands(y_true, y_pred) -> pd.DataFrame:
    tb, pb = to_band(y_true), to_band(y_pred)
    cm = pd.crosstab(pd.Categorical(tb, BANDS), pd.Categorical(pb, BANDS), dropna=False)
    cm.index.name, cm.columns.name = "real", "predicho"
    return cm


def mae_by(df: pd.DataFrame, col: str) -> pd.Series:
    return (df["y_pred"] - df["y_true"]).abs().groupby(df[col]).mean()


# ── Duración de empleos a partir de las fechas del texto ─────────────────────
DATE_RANGE = re.compile(r"((?:19|20)\d{2})\.(\d{2})\s*[^\d\s]{0,3}\s*((?:19|20)\d{2})(?:\.(\d{2}))?(?!\d)")
YEAR_TOKEN = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


def job_ranges(text: str) -> list[tuple[float, float]]:
    """(inicio, fin) en años decimales de cada rango «AAAA.MM–AAAA.MM» del texto.

    Si el OCR cortó el mes final («2020.02–2023.») se asume enero, que es el mes de corte de PopResume."""
    out = []
    for y1, m1, y2, m2 in DATE_RANGE.findall(text or ""):
        m1 = min(max(int(m1), 1), 12)
        m2 = min(max(int(m2), 1), 12) if m2 else 1
        s, e = int(y1) + (m1 - 1) / 12, int(y2) + (m2 - 1) / 12
        if e >= s:
            out.append((s, e))
    return out


def rule_experience(text: str, mode: str = "sum") -> float:
    """Regla de fechas: 'sum' suma duraciones, 'union' une solapes, 'span' = primer inicio → último fin."""
    r = sorted(job_ranges(text))
    if not r:
        return 0.0
    if mode == "sum":
        return sum(e - s for s, e in r)
    if mode == "span":
        return max(e for _, e in r) - min(s for s, _ in r)
    total, (cs, ce) = 0.0, r[0]
    for s, e in r[1:]:
        if s > ce:
            total += ce - cs
            cs, ce = s, e
        else:
            ce = max(ce, e)
    return total + (ce - cs)


def strip_digits_lower(text: str) -> str:
    """Preprocesador de TF-IDF «sin números»: minúsculas y sin dígitos (función de módulo para poder serializarla)."""
    return re.sub(r"\d+", " ", text).lower()


# ── Predictores (interfaz común) ─────────────────────────────────────────────
@dataclass
class MedianModel:
    median_: float = 0.0

    def fit(self, texts, y):
        self.median_ = float(np.median(y))
        return self

    def predict(self, texts) -> np.ndarray:
        return np.full(len(texts), self.median_)


@dataclass
class RuleModel:
    mode: str = "sum"

    def fit(self, texts, y):
        return self

    def predict(self, texts) -> np.ndarray:
        return clip_target([rule_experience(t, self.mode) for t in texts])


@dataclass
class SklearnTextModel:
    """TF-IDF (o cualquier ``pipeline`` sklearn texto→número) + Ridge; recorta la predicción."""
    pipeline: object = None

    def predict(self, texts) -> np.ndarray:
        return clip_target(self.pipeline.predict(list(texts)))


def chunk_text(text: str, tokenizer, max_tokens: int) -> list[str]:
    """Estrategia para textos largos de los embeddings congelados: agrupa líneas completas en trozos de
    ≤ max_tokens tokens (el CV se promedia luego trozo a trozo). Un texto corto queda en un solo trozo."""
    chunks, cur, cur_len = [], [], 0
    for line in text.split("\n"):
        n = len(tokenizer.tokenize(line))
        if cur and cur_len + n > max_tokens:
            chunks.append("\n".join(cur))
            cur, cur_len = [], 0
        cur.append(line)
        cur_len += n
    if cur:
        chunks.append("\n".join(cur))
    return chunks or [""]


@dataclass
class EmbeddingRidgeModel:
    encoder_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    max_tokens: int = 200
    ridge: object = None
    _encoder: object = field(default=None, repr=False)

    def __getstate__(self):  # el encoder (pesos) no se serializa: se baja de HF al usarlo
        d = dict(self.__dict__)
        d["_encoder"] = None
        return d

    def encoder(self):
        if self._encoder is None:
            from sentence_transformers import SentenceTransformer
            self._encoder = SentenceTransformer(self.encoder_name, device="cpu")
        return self._encoder

    def embed(self, texts) -> np.ndarray:
        enc = self.encoder()
        tok = enc.tokenizer
        pieces, owner = [], []
        for i, t in enumerate(texts):
            for c in chunk_text(t, tok, self.max_tokens):
                pieces.append(c)
                owner.append(i)
        emb = enc.encode(pieces, batch_size=64, normalize_embeddings=True, show_progress_bar=False)
        owner = np.array(owner)
        out = np.zeros((len(texts), emb.shape[1]))
        for i in range(len(texts)):
            out[i] = emb[owner == i].mean(axis=0)
        return out

    def predict(self, texts) -> np.ndarray:
        return clip_target(self.ridge.predict(self.embed(list(texts))))


# ── Perturbaciones de texto (Pregunta 1) ─────────────────────────────────────
def shift_dates(text: str, years: int = 5) -> str:
    """Suma ``years`` a TODOS los años del texto (rangos de empleo y graduación). Las duraciones no cambian."""
    return YEAR_TOKEN.sub(lambda m: str(int(m.group(1)) + years), text)


def drop_job(text: str, k: int = 0) -> tuple[str, float | None]:
    """Borra el k-ésimo bloque de trabajo (línea con rango de fechas + sus viñetas). Devuelve (texto, años borrados)."""
    lines = text.split("\n")
    heads = [i for i, ln in enumerate(lines) if DATE_RANGE.search(ln) and not _is_education(lines, i)]
    if len(heads) < 2 or k >= len(heads):
        return text, None
    a = heads[k]
    b = heads[k + 1] if k + 1 < len(heads) else _end_of_work(lines, a)
    dur = job_ranges(lines[a])
    removed = sum(e - s for s, e in dur)
    return "\n".join(lines[:a] + lines[b:]), removed


def _is_education(lines, i) -> bool:
    for j in range(i, -1, -1):
        if re.match(r"(?i)^\s*education\b", lines[j]):
            return True
        if re.match(r"(?i)^\s*work history\b", lines[j]):
            return False
    return False


def _end_of_work(lines, a) -> int:
    for j in range(a + 1, len(lines)):
        if re.match(r"(?i)^\s*education\b", lines[j]):
            return j
    return len(lines)

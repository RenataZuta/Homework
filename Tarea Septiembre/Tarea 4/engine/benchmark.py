"""Benchmark del ASR: todas las combinaciones modelo × precisión × dispositivo (con y sin glosario).

Para cada audio mide WER y CER (jiwer) contra la transcripción de referencia (el guion), el tiempo y la VRAM, y reporta
si el texto cambia entre precisiones (float16 vs int8) y entre dispositivos. El efecto del glosario y todas las
métricas agregadas llevan un intervalo de confianza del 95 % por bootstrap sobre los clips.

Antes de comparar, los textos se normalizan: minúsculas, sin puntuación y sin espacios dobles (`normalize_for_wer`).
Además se reporta `wer_numnorm`, que pasa antes los números hablados a dígitos ("cuatro mil quinientos" -> 4500),
porque Whisper escribe en cifras lo que el guion tiene en palabras.

Salidas (CSV) en tasks/{task}/metrics/: benchmark_detail, benchmark_summary, glossary_effect, precision_changes y
benchmark_skipped. Las transcripciones se guardan como JSON en tasks/{task}/transcriptions_cache/.

Uso:  python -m engine.benchmark [--tasks ...] [--models ...] [--precisions ...] [--devices ...] [--glossary off on]
      python -m engine.benchmark --ladder-dir tasks/task2_sales/degradation [--levels ...]   (escalera de degradación)
"""
import argparse
import itertools
import json
import re
import time
from pathlib import Path

import jiwer
import numpy as np
import pandas as pd

from . import load_config, task_dir
from .transcriber import Transcriber, build_glossary, is_supported
from .validator import normalize_spoken_numbers, normalize_text, _stem

SCHEMA_DE_TAREA = {"task1_interview": "interview", "task2_sales": "sales"}
EXT_AUDIO = {".m4a", ".wav", ".mp3", ".ogg", ".opus", ".flac"}
COLS_GLOSARIO = ["task", "model", "compute_type", "device", "n_clips", "wer_sin_glosario", "wer_con_glosario",
                 "delta_wer", "delta_ci_low", "delta_ci_high", "clips_mejoran", "clips_empeoran", "clips_iguales",
                 "ic_excluye_cero"]
COLS_CURVA = ["model", "compute_type", "device", "glossary", "level", "family", "severity", "param", "n_clips",
              "wer_original", "wer_level", "delta_wer", "delta_ci_low", "delta_ci_high", "ic_excluye_cero"]
COLS_CAMBIOS = ["task", "clip", "model", "glossary", "eje", "config_a", "config_b", "texto_cambio",
                "wer_entre_textos", "wer_a", "wer_b"]


# ── Referencias y normalización ───────────────────────────────────────────────

def _leer_guion(path):
    lineas = []
    for linea in Path(path).read_text(encoding="utf-8").splitlines():
        m = re.match(r"^(A|B):\s*(.*)$", linea.strip())
        if m:
            lineas.append(m.group(2).strip())
    return " ".join(lineas)


def load_references(config, task):
    """{clip: texto de referencia}. Usa la columna transcript_referencia del ground_truth.csv y, si no está, el guion."""
    refs = {}
    csv_path = task_dir(config, task, "ground_truth") / "ground_truth.csv"
    if csv_path.exists():
        df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
        if "transcript_referencia" in df.columns:
            refs = {c: t for c, t in zip(df["clip"], df["transcript_referencia"]) if t}
    for md in sorted(task_dir(config, task, "scripts").glob("*.md")):
        refs.setdefault(md.stem, _leer_guion(md))
    return refs


def list_audios(config, task, refs, limit=None):
    carpeta = task_dir(config, task, "audio")
    audios = [p for p in sorted(carpeta.glob("*")) if p.suffix.lower() in EXT_AUDIO and p.stem in refs] if carpeta.exists() else []
    return audios[:limit] if limit else audios


def normalize_for_wer(text):
    """Minúsculas, sin puntuación y sin espacios dobles (se conservan las tildes)."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (text or "").lower())).strip()


def _normalize_numnorm(text):
    return normalize_for_wer(normalize_spoken_numbers(text or ""))


def _conteos(ref, hyp):
    """(errores_palabras, palabras_ref, errores_caracteres, caracteres_ref) con jiwer."""
    w, c = jiwer.process_words(ref, hyp), jiwer.process_characters(ref, hyp)
    return (w.substitutions + w.deletions + w.insertions, w.hits + w.substitutions + w.deletions,
            c.substitutions + c.deletions + c.insertions, c.hits + c.substitutions + c.deletions)


# ── Bootstrap ─────────────────────────────────────────────────────────────────

def bootstrap_ci(num, den=None, n_boot=1000, seed=0, confidence=0.95):
    """(punto, bajo, alto). Con `den` es la razón sum(num)/sum(den) (WER de corpus); sin `den`, la media.
    Se remuestrean los clips con reemplazo."""
    num = np.asarray(num, dtype=float)
    den = None if den is None else np.asarray(den, dtype=float)
    ok = ~np.isnan(num) if den is None else ~(np.isnan(num) | np.isnan(den))
    num, den = num[ok], (None if den is None else den[ok])
    if len(num) == 0:
        return (np.nan, np.nan, np.nan)
    estadistico = (lambda n, d: n.sum() / d.sum()) if den is not None else (lambda n, d: n.mean())
    punto = estadistico(num, den)
    if len(num) == 1:
        return (punto, np.nan, np.nan)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(num), size=(n_boot, len(num)))
    valores = [estadistico(num[i], None if den is None else den[i]) for i in idx]
    a = (1 - confidence) / 2
    return (punto, float(np.quantile(valores, a)), float(np.quantile(valores, 1 - a)))


# ── Transcripción con caché ───────────────────────────────────────────────────

def _cache_path(cache_dir, clip, model, compute_type, device, gloss):
    return Path(cache_dir) / f"{clip}__{model}_{compute_type}_{device}_{'gloss' if gloss else 'nogloss'}.json"


def _version_faster_whisper():
    try:
        import faster_whisper

        return faster_whisper.__version__
    except Exception:
        return None


# ── Benchmark ─────────────────────────────────────────────────────────────────

def run_benchmark(config, tasks=None, models=None, precisions=None, devices=None, glossary=None, limit=None,
                  metrics_dir=None, cache_dir=None, warmup=None, use_cache=True, n_boot=None, progress=print,
                  models_cpu=None):
    """Ejecuta el benchmark y devuelve un dict de DataFrames (detail, summary, glossary_effect, precision_changes,
    skipped) además de escribirlos como CSV. `use_cache=True` reutiliza las transcripciones ya guardadas.
    `models_cpu` limita los modelos que corren en CPU (en la CPU de Colab, medium tarda ~1,5 min por audio y large-v3
    bastante más); None = los mismos modelos que en GPU."""
    asr, bench = config["asr"], config.get("benchmark", {})
    tasks = tasks or [t for t in config["paths"] if t != "root"]
    models = models or asr["models"]
    precisions = precisions or asr["precisions"]
    devices = devices or bench.get("devices", ["cuda", "cpu"])
    glosarios = glossary or bench.get("glossary", ["off", "on"])
    warmup = bench.get("warmup", True) if warmup is None else warmup
    n_boot = n_boot or bench.get("bootstrap_samples", 1000)

    datos = {}
    for t in tasks:
        refs = load_references(config, t)
        datos[t] = {"refs": refs, "audios": list_audios(config, t, refs, limit)}
        progress(f"{t}: {len(datos[t]['audios'])} audios con referencia")

    def carpeta(base, t, clave):
        return (Path(base) / t) if base else task_dir(config, t, clave)

    filas, textos, omitidas = [], {}, []
    for dispositivo, modelo, precision in itertools.product(devices, models, precisions):
        if dispositivo == "cpu" and models_cpu is not None and modelo not in models_cpu:
            omitidas.append({"model": modelo, "compute_type": precision, "device": dispositivo,
                             "reason": "excluida con models_cpu (la CPU es lenta)"})
            progress(f"  [omitida] {modelo} {precision} {dispositivo}: excluida con models_cpu")
            continue
        if not is_supported(dispositivo, precision):
            motivo = "sin GPU disponible" if dispositivo == "cuda" and not is_supported("cuda", "float32") \
                else f"{precision} no está soportado en {dispositivo}"
            omitidas.append({"model": modelo, "compute_type": precision, "device": dispositivo, "reason": motivo})
            progress(f"  [omitida] {modelo} {precision} {dispositivo}: {motivo}")
            continue
        progress(f"== {modelo} · {precision} · {dispositivo}")
        tr = None
        for t in tasks:
            cdir = carpeta(cache_dir, t, "transcriptions_cache")
            cdir.mkdir(parents=True, exist_ok=True)
            for gl in glosarios:
                for audio in datos[t]["audios"]:
                    clip = audio.stem
                    cp = _cache_path(cdir, clip, modelo, precision, dispositivo, gl == "on")
                    if use_cache and cp.exists():
                        res = json.loads(cp.read_text(encoding="utf-8"))
                    else:
                        if tr is None:
                            tr = Transcriber(modelo, dispositivo, precision, config).load()
                            if warmup and datos[t]["audios"]:
                                tr.transcribe(datos[t]["audios"][0], None)  # descartada: arranque de CUDA/CPU
                        r = tr.transcribe(audio, build_glossary(config, SCHEMA_DE_TAREA.get(t)) if gl == "on" else None)
                        res = {"clip": clip, "task": t, "model": modelo, "compute_type": precision,
                               "device_requested": dispositivo, "device_used": r.device_used, "glossary": gl == "on",
                               "glossary_mechanism": r.glossary_mechanism, "language": r.language, "transcript": r.text,
                               "vram_mb": r.vram_peak_mb, "vram_device_mb": r.vram_device_peak_mb,
                               "elapsed_s": r.elapsed_seconds, "faster_whisper": _version_faster_whisper(),
                               "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}
                        cp.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
                    ref = datos[t]["refs"][clip]
                    w_err, w_n, c_err, c_n = _conteos(normalize_for_wer(ref), normalize_for_wer(res["transcript"]))
                    n_err, n_n, _, _ = _conteos(_normalize_numnorm(ref), _normalize_numnorm(res["transcript"]))
                    textos[(t, clip, modelo, precision, dispositivo, gl)] = res["transcript"]
                    filas.append({"task": t, "clip": clip, "model": modelo, "compute_type": precision,
                                  "device": dispositivo, "device_used": res["device_used"], "glossary": gl,
                                  "w_err": w_err, "w_n": w_n, "c_err": c_err, "c_n": c_n, "wn_err": n_err, "wn_n": n_n,
                                  "wer": w_err / w_n, "cer": c_err / c_n, "wer_numnorm": n_err / n_n,
                                  "elapsed_s": res["elapsed_s"], "vram_mb": res["vram_mb"],
                                  "vram_device_mb": res["vram_device_mb"]})
        if tr is not None:
            tr.close()

    detail = pd.DataFrame(filas)
    out = {"detail": detail, "skipped": pd.DataFrame(omitidas, columns=["model", "compute_type", "device", "reason"])}
    if detail.empty:
        out.update(summary=pd.DataFrame(), glossary_effect=pd.DataFrame(columns=COLS_GLOSARIO),
                   precision_changes=pd.DataFrame(columns=COLS_CAMBIOS))
    else:
        out["summary"] = summarize(detail, n_boot, bench.get("bootstrap_seed", 0), bench.get("confidence", 0.95))
        out["glossary_effect"] = glossary_effect(detail, n_boot, bench.get("bootstrap_seed", 0), bench.get("confidence", 0.95))
        out["precision_changes"] = text_changes(detail, textos, config, datos)
    for t in tasks:
        mdir = carpeta(metrics_dir, t, "metrics")
        mdir.mkdir(parents=True, exist_ok=True)
        for nombre, df in (("benchmark_detail", out["detail"]), ("benchmark_summary", out["summary"]),
                           ("glossary_effect", out["glossary_effect"]), ("precision_changes", out["precision_changes"]),
                           ("benchmark_skipped", out["skipped"])):
            sub = df[df["task"] == t] if "task" in df.columns and not df.empty else df
            sub.to_csv(mdir / f"{nombre}.csv", index=False, encoding="utf-8")
        progress(f"CSVs guardados en {mdir}")
    return out


def summarize(detail, n_boot=1000, seed=0, confidence=0.95, keys=None):
    """Una fila por (tarea, modelo, precisión, dispositivo, glosario): WER/CER de corpus con IC 95 %, tiempo y VRAM.
    `keys` cambia las columnas de agrupación (la escalera de degradación añade el nivel)."""
    keys = keys or ["task", "model", "compute_type", "device", "glossary"]
    filas = []
    for clave, g in detail.groupby(keys, sort=False):
        fila = dict(zip(keys, clave), n_clips=len(g))
        for nombre, (n, d) in {"wer": ("w_err", "w_n"), "cer": ("c_err", "c_n"), "wer_numnorm": ("wn_err", "wn_n")}.items():
            fila[nombre], fila[f"{nombre}_ci_low"], fila[f"{nombre}_ci_high"] = bootstrap_ci(g[n], g[d], n_boot, seed, confidence)
        for nombre in ("elapsed_s", "vram_device_mb", "vram_mb"):
            fila[nombre], fila[f"{nombre}_ci_low"], fila[f"{nombre}_ci_high"] = bootstrap_ci(
                pd.to_numeric(g[nombre], errors="coerce"), None, n_boot, seed, confidence)
        filas.append(fila)
    return pd.DataFrame(filas)


def load_ladder_meta(ladder_dir):
    """{nivel: (familia, severidad, parámetro)} leído de ladder_manifest.csv (vacío si no existe)."""
    ruta = Path(ladder_dir) / "ladder_manifest.csv"
    if not ruta.exists():
        return {}
    df = pd.read_csv(ruta, dtype=str, keep_default_na=False).drop_duplicates("level")
    return {r["level"]: (r["family"], int(r["severity"]), r["param"]) for r in df.to_dict("records")}


def list_ladder(ladder_dir, refs, levels=None, limit=None):
    """[(ruta, clip, nivel)] de ladder_dir/<nivel>/<clip>.wav que tengan referencia. `original` va primero y el resto
    por familia y severidad (según ladder_manifest.csv). `limit` recorta los clips de cada nivel."""
    ladder_dir = Path(ladder_dir)
    meta = load_ladder_meta(ladder_dir)
    niveles = [d.name for d in sorted(ladder_dir.iterdir()) if d.is_dir() and any(d.glob("*.wav"))]
    if meta and not levels:  # carpetas ajenas al manifiesto (p. ej. L0-L3 del preset) solo entran si se piden con levels
        niveles = [n for n in niveles if n in meta]
    if levels:
        faltan = [n for n in levels if n not in niveles]
        if faltan:
            raise ValueError(f"niveles sin audios en {ladder_dir}: {faltan} (hay: {niveles})")
        niveles = [n for n in niveles if n in levels]
    niveles.sort(key=lambda n: (n != "original", meta.get(n, ("~", 99, ""))[0], meta.get(n, ("~", 99, ""))[1], n))
    items = []
    for n in niveles:
        wavs = [p for p in sorted((ladder_dir / n).glob("*.wav")) if p.stem in refs]
        items += [(p, p.stem, n) for p in (wavs[:limit] if limit else wavs)]
    return items


def run_ladder(config, ladder_dir, task="task2_sales", levels=None, models=None, precisions=None, devices=None,
               glossary=None, limit=None, metrics_dir=None, cache_dir=None, warmup=None, use_cache=True, n_boot=None,
               progress=print, models_cpu=None):
    """Transcribe cada nivel de la escalera de degradación (tasks/task2_sales/degradation/build_ladder.py) y mide cuánto
    empeora el WER respecto al nivel `original`. Escribe en tasks/{task}/metrics/: ladder_detail, ladder_summary
    (WER/CER por nivel con IC 95 %), ladder_curve (diferencia de WER contra `original`, pareada por clip, con IC 95 %) y
    ladder_skipped. Las transcripciones van a transcriptions_cache/ como {clip}@{nivel}__{modelo}_{precisión}_....json."""
    asr, bench = config["asr"], config.get("benchmark", {})
    models = models or asr["models"]
    precisions = precisions or asr["precisions"]
    devices = devices or bench.get("devices", ["cuda", "cpu"])
    glosarios = glossary or bench.get("glossary", ["off", "on"])
    warmup = bench.get("warmup", True) if warmup is None else warmup
    n_boot = n_boot or bench.get("bootstrap_samples", 1000)
    seed, confianza = bench.get("bootstrap_seed", 0), bench.get("confidence", 0.95)

    refs = load_references(config, task)
    items = list_ladder(ladder_dir, refs, levels, limit)
    if not items:
        raise ValueError(f"no hay audios con referencia en {ladder_dir}")
    meta = load_ladder_meta(ladder_dir)
    niveles = list(dict.fromkeys(n for _, _, n in items))
    progress(f"{task}: {len(items)} audios en {len(niveles)} niveles: {niveles}")
    cdir = (Path(cache_dir) / task) if cache_dir else task_dir(config, task, "transcriptions_cache")
    cdir.mkdir(parents=True, exist_ok=True)

    filas, omitidas = [], []
    for dispositivo, modelo, precision in itertools.product(devices, models, precisions):
        if dispositivo == "cpu" and models_cpu is not None and modelo not in models_cpu:
            omitidas.append({"model": modelo, "compute_type": precision, "device": dispositivo,
                             "reason": "excluida con models_cpu (la CPU es lenta)"})
            continue
        if not is_supported(dispositivo, precision):
            motivo = "sin GPU disponible" if dispositivo == "cuda" and not is_supported("cuda", "float32") \
                else f"{precision} no está soportado en {dispositivo}"
            omitidas.append({"model": modelo, "compute_type": precision, "device": dispositivo, "reason": motivo})
            progress(f"  [omitida] {modelo} {precision} {dispositivo}: {motivo}")
            continue
        progress(f"== {modelo} · {precision} · {dispositivo}")
        tr = None
        for gl in glosarios:
            for ruta, clip, nivel in items:
                cp = _cache_path(cdir, f"{clip}@{nivel}", modelo, precision, dispositivo, gl == "on")
                familia, severidad, parametro = meta.get(nivel, ("", "", ""))
                if use_cache and cp.exists():
                    res = json.loads(cp.read_text(encoding="utf-8"))
                else:
                    if tr is None:
                        tr = Transcriber(modelo, dispositivo, precision, config).load()
                        if warmup:
                            tr.transcribe(items[0][0], None)  # descartada: arranque de CUDA/CPU
                    r = tr.transcribe(ruta, build_glossary(config, SCHEMA_DE_TAREA.get(task)) if gl == "on" else None)
                    res = {"clip": clip, "level": nivel, "family": familia, "severity": severidad, "task": task,
                           "model": modelo, "compute_type": precision, "device_requested": dispositivo,
                           "device_used": r.device_used, "glossary": gl == "on",
                           "glossary_mechanism": r.glossary_mechanism, "language": r.language, "transcript": r.text,
                           "vram_mb": r.vram_peak_mb, "vram_device_mb": r.vram_device_peak_mb,
                           "elapsed_s": r.elapsed_seconds, "faster_whisper": _version_faster_whisper(),
                           "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}
                    cp.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
                ref = refs[clip]
                w_err, w_n, c_err, c_n = _conteos(normalize_for_wer(ref), normalize_for_wer(res["transcript"]))
                n_err, n_n, _, _ = _conteos(_normalize_numnorm(ref), _normalize_numnorm(res["transcript"]))
                filas.append({"task": task, "level": nivel, "family": familia, "severity": severidad, "param": parametro,
                              "clip": clip, "model": modelo, "compute_type": precision, "device": dispositivo,
                              "device_used": res["device_used"], "glossary": gl, "w_err": w_err, "w_n": w_n,
                              "c_err": c_err, "c_n": c_n, "wn_err": n_err, "wn_n": n_n, "wer": w_err / w_n,
                              "cer": c_err / c_n, "wer_numnorm": n_err / n_n, "elapsed_s": res["elapsed_s"],
                              "vram_mb": res["vram_mb"], "vram_device_mb": res["vram_device_mb"]})
        if tr is not None:
            tr.close()

    detail = pd.DataFrame(filas)
    out = {"detail": detail, "skipped": pd.DataFrame(omitidas, columns=["model", "compute_type", "device", "reason"])}
    if detail.empty:
        out.update(summary=pd.DataFrame(), curve=pd.DataFrame(columns=COLS_CURVA))
    else:
        claves = ["task", "level", "family", "severity", "param", "model", "compute_type", "device", "glossary"]
        out["summary"] = summarize(detail, n_boot, seed, confianza, keys=claves)
        out["curve"] = degradation_curve(detail, n_boot, seed, confianza)
    mdir = (Path(metrics_dir) / task) if metrics_dir else task_dir(config, task, "metrics")
    mdir.mkdir(parents=True, exist_ok=True)
    for nombre, clave in (("ladder_detail", "detail"), ("ladder_summary", "summary"), ("ladder_curve", "curve"),
                          ("ladder_skipped", "skipped")):
        out[clave].to_csv(mdir / f"{nombre}.csv", index=False, encoding="utf-8")
    progress(f"CSVs de la escalera guardados en {mdir}")
    return out


def degradation_curve(detail, n_boot=1000, seed=0, confidence=0.95):
    """Cuánto sube el WER de corpus en cada nivel respecto a `original` (pareado por clip), con IC 95 % por bootstrap."""
    claves = ["model", "compute_type", "device", "glossary"]
    filas = []
    for clave, g in detail.groupby(claves, sort=False):
        base = g[g["level"] == "original"].set_index("clip")
        if base.empty:
            continue
        for nivel, h in g[g["level"] != "original"].groupby("level", sort=False):
            h = h.set_index("clip")
            comunes = h.index.intersection(base.index)
            if len(comunes) == 0:
                continue
            b, h = base.loc[comunes], h.loc[comunes]
            punto, lo, hi = bootstrap_ci((h["w_err"] - b["w_err"]).values, h["w_n"].values, n_boot, seed, confidence)
            filas.append({**dict(zip(claves, clave)), "level": nivel, "family": h["family"].iloc[0],
                          "severity": h["severity"].iloc[0], "param": h["param"].iloc[0], "n_clips": len(comunes),
                          "wer_original": b["w_err"].sum() / b["w_n"].sum(), "wer_level": h["w_err"].sum() / h["w_n"].sum(),
                          "delta_wer": punto, "delta_ci_low": lo, "delta_ci_high": hi,
                          "ic_excluye_cero": bool(not np.isnan(lo) and (lo > 0 or hi < 0))})
    return pd.DataFrame(filas, columns=COLS_CURVA)


def glossary_effect(detail, n_boot=1000, seed=0, confidence=0.95):
    """Diferencia de WER con − sin glosario (negativa = el glosario ayuda), pareada por clip, con IC 95 %."""
    filas = []
    for clave, g in detail.groupby(["task", "model", "compute_type", "device"], sort=False):
        on, off = g[g["glossary"] == "on"].set_index("clip"), g[g["glossary"] == "off"].set_index("clip")
        comunes = on.index.intersection(off.index)
        if len(comunes) == 0:
            continue
        on, off = on.loc[comunes], off.loc[comunes]
        # Diferencia de corpus remuestreando clips: (errores_on − errores_off) / palabras.
        punto, lo, hi = bootstrap_ci((on["w_err"] - off["w_err"]).values, on["w_n"].values, n_boot, seed, confidence)
        mejora, peor = int((on["wer"] < off["wer"]).sum()), int((on["wer"] > off["wer"]).sum())
        filas.append({**dict(zip(["task", "model", "compute_type", "device"], clave)), "n_clips": len(comunes),
                      "wer_sin_glosario": off["w_err"].sum() / off["w_n"].sum(),
                      "wer_con_glosario": on["w_err"].sum() / on["w_n"].sum(),
                      "delta_wer": punto, "delta_ci_low": lo, "delta_ci_high": hi,
                      "clips_mejoran": mejora, "clips_empeoran": peor, "clips_iguales": len(comunes) - mejora - peor,
                      "ic_excluye_cero": bool(not np.isnan(lo) and (lo > 0 or hi < 0))})
    return pd.DataFrame(filas, columns=COLS_GLOSARIO)


def text_changes(detail, textos, config, datos):
    """¿Cambia el texto entre precisiones (mismo dispositivo) o entre dispositivos (misma precisión)?"""
    filas = []
    grupos = detail.groupby(["task", "clip", "model", "glossary"], sort=False)
    for (t, clip, modelo, gl), g in grupos:
        configs = {(r.device, r.compute_type): r for r in g.itertuples()}
        for (a, ra), (b, rb) in itertools.combinations(sorted(configs.items()), 2):
            if a[0] == b[0] and a[1] != b[1]:
                eje = "precision"
            elif a[1] == b[1] and a[0] != b[0]:
                eje = "dispositivo"
            else:
                continue
            ta = normalize_for_wer(textos[(t, clip, modelo, a[1], a[0], gl)])
            tb = normalize_for_wer(textos[(t, clip, modelo, b[1], b[0], gl)])
            filas.append({"task": t, "clip": clip, "model": modelo, "glossary": gl, "eje": eje,
                          "config_a": f"{a[1]}/{a[0]}", "config_b": f"{b[1]}/{b[0]}", "texto_cambio": ta != tb,
                          "wer_entre_textos": jiwer.wer(ta, tb) if ta else np.nan, "wer_a": ra.wer, "wer_b": rb.wer})
    return pd.DataFrame(filas, columns=COLS_CAMBIOS)


# ── Exactitud de la extracción (para comparar reglas vs LLM contra el ground truth) ────────────────────────────

def load_ground_truth(config, task):
    """{clip: fila del ground_truth.csv} (todo como texto)."""
    df = pd.read_csv(task_dir(config, task, "ground_truth") / "ground_truth.csv", dtype=str, keep_default_na=False)
    return {r["clip"]: r for r in df.to_dict("records")}


def _igual_num(a, b):
    try:
        return abs(float(a) - float(b)) < 0.01
    except (TypeError, ValueError):
        return False


def _tokens_plato(nombre):
    return {_stem(w) for w in normalize_text(str(nombre), numbers=False).split()}


def _items_coinciden(gt_items, ex_items):
    """(nombres_y_cantidades_ok, fracción_de_precios_ok). Los nombres se comparan por tokens singularizados."""
    libres = list(range(len(ex_items)))
    precios_ok, ok = 0, len(gt_items) == len(ex_items)
    for g in gt_items:
        a = _tokens_plato(g["plato"])
        mejor = None
        for i in libres:
            b = _tokens_plato(ex_items[i].get("plato", ""))
            if a and b and len(a & b) / min(len(a), len(b)) >= 0.8 and len(a & b) / max(len(a), len(b)) >= 0.5:
                mejor = i
                break
        if mejor is None:
            ok = False
            continue
        libres.remove(mejor)
        e = ex_items[mejor]
        ok &= _igual_num(e.get("cantidad"), g["cantidad"])
        precios_ok += _igual_num(e.get("precio_unitario"), g["precio_unitario"])
    return ok, (precios_ok / len(gt_items) if gt_items else np.nan)


def field_accuracy(config, task, clip, fields, gt=None):
    """{campo: bool} comparando un registro extraído con el ground truth del clip.
    Interview: igualdad (números con tolerancia, listas como conjunto). Sales: `items` compara nombre y cantidad
    (`items_precio` es la fracción de precios correctos), `direccion_entrega` ignora abreviaturas y tildes y
    `promocion` exige las mismas palabras de contenido."""
    fila = (gt or load_ground_truth(config, task))[clip]
    res = {}
    if SCHEMA_DE_TAREA.get(task) == "interview":
        res["anios_experiencia"] = _igual_num(fields.get("anios_experiencia"), fila["anios_experiencia"])
        res["ultimo_puesto"] = normalize_text(str(fields.get("ultimo_puesto") or ""), False) == normalize_text(fila["ultimo_puesto"], False)
        esperado = {x.strip().lower() for x in fila["tecnologias"].split(",") if x.strip()}
        res["tecnologias"] = {str(x).lower() for x in (fields.get("tecnologias") or [])} == esperado
        res["pretension_salarial"] = _igual_num(fields.get("pretension_salarial"), fila["pretension_salarial"])
        res["disponibilidad"] = normalize_text(str(fields.get("disponibilidad") or "")) == normalize_text(fila["disponibilidad"])
        res["nivel_ingles"] = str(fields.get("nivel_ingles") or "").lower() == fila["nivel_ingles"].lower()
    else:
        res["items"], res["items_precio"] = _items_coinciden(json.loads(fila["items_json"]), fields.get("items") or [])
        promo_gt = None if fila["promocion"] in ("", "null") else fila["promocion"]
        promo_ex = fields.get("promocion") or None
        if promo_gt is None or promo_ex is None:
            res["promocion"] = promo_gt is None and promo_ex is None
        else:
            pal = lambda s: {_stem(w) for w in normalize_text(str(s), numbers=False).split() if len(w) > 3 and w.isalpha()}
            res["promocion"] = pal(promo_gt) == pal(promo_ex)
        res["direccion_entrega"] = normalize_text(str(fields.get("direccion_entrega") or "")) == normalize_text(fila["direccion_entrega"])
        res["metodo_pago"] = str(fields.get("metodo_pago") or "").lower() == fila["metodo_pago"].lower()
        res["total_dicho"] = _igual_num(fields.get("total_dicho"), fila["total_dicho"])
    return res


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Benchmark ASR modelo × precisión × dispositivo")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--tasks", nargs="+")
    p.add_argument("--models", nargs="+")
    p.add_argument("--precisions", nargs="+")
    p.add_argument("--devices", nargs="+")
    p.add_argument("--glossary", nargs="+", choices=["off", "on"])
    p.add_argument("--limit", type=int, help="solo los primeros N audios de cada tarea")
    p.add_argument("--metrics-dir", help="carpeta alternativa para los CSV (por defecto tasks/{task}/metrics/)")
    p.add_argument("--cache-dir", help="carpeta alternativa para las transcripciones")
    p.add_argument("--no-warmup", action="store_true")
    p.add_argument("--no-cache", action="store_true", help="volver a transcribir aunque exista la caché")
    p.add_argument("--n-boot", type=int)
    p.add_argument("--models-cpu", nargs="+", help="modelos que corren en CPU (por defecto, los mismos que en GPU)")
    p.add_argument("--ladder-dir", type=Path, help="carpeta de la escalera de degradación (build_ladder.py): "
                   "transcribe cada nivel en vez de los audios normales")
    p.add_argument("--levels", nargs="+", help="con --ladder-dir: subconjunto de niveles")
    p.add_argument("--ladder-task", default="task2_sales", help="tarea de la escalera (por defecto task2_sales)")
    a = p.parse_args()
    if a.ladder_dir:
        run_ladder(load_config(a.config), a.ladder_dir, a.ladder_task, a.levels, a.models, a.precisions, a.devices,
                   a.glossary, a.limit, a.metrics_dir, a.cache_dir, False if a.no_warmup else None, not a.no_cache,
                   a.n_boot, models_cpu=a.models_cpu)
        return
    run_benchmark(load_config(a.config), a.tasks, a.models, a.precisions, a.devices, a.glossary, a.limit,
                  a.metrics_dir, a.cache_dir, False if a.no_warmup else None, not a.no_cache, a.n_boot,
                  models_cpu=a.models_cpu)


if __name__ == "__main__":
    main()

"""From Voice to Record — interfaz de la Tarea 4 (HW05).

Cuatro pestañas:
  1. Problema y Método: qué resuelve el proyecto, qué existe y qué falta, y el pipeline.
  2. Resultados Task 1 (Entrevistas): extracción por campo contra el ground truth, WER/CER y exactitud por campo.
  3. Resultados Task 2 (Ventas): lo mismo, más la aritmética del pedido y la comparación por nivel de degradación L0-L3.
  4. Demo en vivo: sube un audio, se transcribe con faster-whisper (modelo medium), se extrae y se verifica.

Los resultados salen de tasks/*/metrics/*.csv y de las transcripciones cacheadas con el motor de engine/; no hay datos de
ejemplo inventados. Si falta algún CSV, la pestaña lo avisa en lugar de rellenarlo.

Uso (desde la carpeta de la Tarea 4):  streamlit run app.py
"""
import difflib
import html
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import altair as alt
import jiwer
import pandas as pd
import streamlit as st

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from engine import load_config, task_dir  # noqa: E402
from engine.benchmark import (  # noqa: E402
    field_accuracy, load_ground_truth, load_ladder_meta, load_references, normalize_for_wer,
)
from engine.compare_extractors import ClienteSimulado  # noqa: E402
from engine.core import process_audio  # noqa: E402
from engine.extractor import RuleExtractor  # noqa: E402
from engine.transcriber import cuda_available, supported_compute_types  # noqa: E402
from engine.validator import normalize_spoken_numbers, validate_order_arithmetic  # noqa: E402

st.set_page_config(page_title="From Voice to Record", page_icon="🎙️", layout="wide")

TAREAS = {"Entrevistas laborales": ("task1_interview", "interview"), "Llamadas de ventas": ("task2_sales", "sales")}
EXT_AUDIO = ["m4a", "wav", "mp3", "ogg", "opus", "flac"]
ICONO = {"verificado": "✅ verificado", "sin_verificar": "⚠️ sin verificar", "sin_valor": "— sin valor"}
ORDEN_FAMILIA = {"original": 0, "ruido": 1, "telefono": 2, "compresion": 3, "volumen": 4}
NIVELES_L = {"L0": "L0 · original", "L1": "L1 · WhatsApp (Opus 24 kbps)", "L2": "L2 · teléfono (300–3400 Hz, 8 kHz)",
             "L3": "L3 · ruido (restaurante, SNR 10 dB)"}
EXTRACTORES = {"rules": "Reglas (regex)", "llm_sim": "LLM — respuestas simuladas (no mide un modelo)",
               "llm_api": "LLM — API de Anthropic (de pago)"}
RESPUESTAS_SIMULADAS = RAIZ / "tasks" / "comparison" / "llm_answers_simulado.json"
CAMPOS = {"interview": ["anios_experiencia", "ultimo_puesto", "tecnologias", "pretension_salarial", "disponibilidad", "nivel_ingles"],
          "sales": ["items", "promocion", "direccion_entrega", "metodo_pago", "total_dicho"]}

st.markdown(
    "<style>mark.del{background:#fecaca;color:#111;padding:0 2px;border-radius:3px}"
    "mark.ins{background:#fde68a;color:#111;padding:0 2px;border-radius:3px}</style>",
    unsafe_allow_html=True,
)


# ── Carga de datos ────────────────────────────────────────────────────────────

@st.cache_resource
def config():
    return load_config(str(RAIZ / "config.yaml"))


@st.cache_data(show_spinner=False)
def leer_csv(ruta, mtime):
    return pd.read_csv(ruta)


def csv_metricas(task, nombre):
    ruta = task_dir(config(), task, "metrics") / nombre
    return leer_csv(str(ruta), ruta.stat().st_mtime) if ruta.exists() else None


@st.cache_data(show_spinner=False)
def referencias(task):
    return load_references(config(), task)


@st.cache_data(show_spinner=False)
def ground_truth(task):
    return load_ground_truth(config(), task)


@st.cache_data(show_spinner=False)
def indice_transcripciones(task):
    """Todas las transcripciones en caché de una tarea (benchmark normal y escalera) como DataFrame."""
    filas = []
    for p in sorted(task_dir(config(), task, "transcriptions_cache").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        filas.append({"clip": d["clip"], "level": d.get("level", ""), "model": d["model"], "compute_type": d["compute_type"],
                      "device": d.get("device_requested", ""), "glossary": bool(d["glossary"]),
                      "elapsed_s": d.get("elapsed_s"), "transcript": d["transcript"]})
    return pd.DataFrame(filas, columns=["clip", "level", "model", "compute_type", "device", "glossary", "elapsed_s", "transcript"])


def carpeta_escalera(task):
    """Carpeta de la escalera de degradación, o None si la tarea no tiene (solo ventas la tiene)."""
    return task_dir(config(), task, "degradation") if "degradation" in config()["paths"][task] else None


def pct(x, d=1):
    return None if pd.isna(x) else round(float(x) * 100, d)


def valor_txt(v):
    if v is None or v == [] or v == "":
        return "—"
    if isinstance(v, list):
        return ", ".join(f"{x:g}" if isinstance(x, (int, float)) else str(x) for x in v)
    return f"{v:g}" if isinstance(v, float) else str(v)


def items_txt(items):
    return "; ".join(f"{i.get('cantidad', '?')}× {i['plato']}" + (f" (S/ {i['precio_unitario']:g})" if i.get("precio_unitario") is not None else "")
                     for i in items or []) or "—"


def clip_de_archivo(nombre):
    """'Entrevista 1.m4a' / 'llamada_03.wav' -> ('task1_interview', 'entrevista_01') si hay referencia."""
    m = re.match(r"(entrevista|llamada)[ _-]*(\d+)", Path(nombre).stem, re.IGNORECASE)
    if not m:
        return None
    task = "task1_interview" if m.group(1).lower() == "entrevista" else "task2_sales"
    clip = f"{m.group(1).lower()}_{int(m.group(2)):02d}"
    return (task, clip) if clip in referencias(task) else None


def diff_html(ref, hip):
    """HTML de dos columnas: palabras del guion que faltan o cambian (rojo) y palabras añadidas o distintas (amarillo)."""
    a, b = ref.split(), hip.split()
    sm = difflib.SequenceMatcher(None, [normalize_for_wer(t) for t in a], [normalize_for_wer(t) for t in b], autojunk=False)
    izq, der = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            izq += [html.escape(t) for t in a[i1:i2]]
            der += [html.escape(t) for t in b[j1:j2]]
        else:
            izq += [f"<mark class='del'>{html.escape(t)}</mark>" for t in a[i1:i2]]
            der += [f"<mark class='ins'>{html.escape(t)}</mark>" for t in b[j1:j2]]
    return " ".join(izq), " ".join(der)


def wer_cer(ref, hip):
    r, h = normalize_for_wer(ref), normalize_for_wer(hip)
    rn, hn = normalize_for_wer(normalize_spoken_numbers(ref)), normalize_for_wer(normalize_spoken_numbers(hip))
    return jiwer.wer(r, h), jiwer.cer(r, h), jiwer.wer(rn, hn)


# ── Bloques de visualización ──────────────────────────────────────────────────

def tabla_campos(fields, verified, detalle):
    filas = []
    for campo, valor in fields.items():
        if campo == "items":
            continue
        estado, d, nota = verified.get(campo, "sin_valor"), detalle.get(campo), ""
        if isinstance(d, dict):
            if d.get("items"):
                malos = [f"{i['value']}" + (f" (casi igual: «{i['near_match']}»)" if i.get("near_match") else "")
                         for i in d["items"] if i["status"] != "verificado"]
                nota = ("no aparece: " + ", ".join(malos)) if malos else ""
            elif d.get("missing"):
                nota = "palabras que no aparecen: " + ", ".join(d["missing"])
            elif d.get("near_match"):
                nota = f"casi igual en el texto: «{d['near_match']}»"
            elif estado == "verificado" and d.get("found_as"):
                nota = f"aparece como «{d['found_as']}»"
        filas.append({"Campo": campo, "Valor extraído": valor_txt(valor), "Verificación": ICONO.get(estado, estado), "Detalle": nota})
    return pd.DataFrame(filas)


def tabla_items(items, detalle_items):
    filas = []
    for it, d in zip(items, detalle_items or [None] * len(items)):
        malos = [k for k, v in (d or {}).items() if k != "_plato" and v["status"] != "verificado"]
        filas.append({"Plato": it["plato"], "Tamaño": it.get("tamaño", ""), "Cantidad": it.get("cantidad"),
                      "Precio unitario": it.get("precio_unitario"),
                      "Verificación": "✅ verificado" if not malos else "⚠️ sin verificar: " + ", ".join(malos)})
    return pd.DataFrame(filas)


def bloque_aritmetica(a):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total dicho (S/)", valor_txt(a["total_dicho"]))
    c2.metric("Total esperado (S/)", valor_txt(a["expected_total"]))
    c3.metric("Diferencia", valor_txt(a["difference"]))
    c4.metric("Diagnóstico", a["diagnosis"])
    msg = f"{a['status']}: {a['explanation']}"
    (st.success if a["status"] == "ok" else st.warning)(msg)
    if a["breakdown"].get("promocion"):
        st.caption(f"Promoción: {a['breakdown']['promocion']}")


def mostrar_resultado(res):
    r, schema, nombre = res["r"], res["schema"], res["nombre"]
    if r["error"]:
        st.error(f"Algo falló en el pipeline: {r['error']}")
    if r["transcript"] is None:
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Dispositivo usado", r["device_used"] or "—")
    c2.metric("Modelo · precisión", f"{r['model']} · {r['compute_type']}")
    c3.metric("Tiempo de transcripción", f"{r['elapsed_seconds']} s" if r["elapsed_seconds"] is not None else "—")
    vram = r.get("vram_device_peak_mb")
    c4.metric("VRAM pico (GPU)", f"{vram:g} MB" if vram else "n/a (CPU)")
    st.markdown("**Transcripción**")
    st.text_area("transcripción", r["transcript"], height=170, label_visibility="collapsed")
    if r["fields"]:
        st.markdown(f"**Campos extraídos** (extractor: {r['extractor_used']})")
        det = r["diagnostics"].get("verification", {})
        st.dataframe(tabla_campos(r["fields"], r["verified_fields"], det), width="stretch", hide_index=True)
        if schema == "sales":
            st.markdown("**Pedido (orden final tras las correcciones)**")
            st.dataframe(tabla_items(r["fields"]["items"], det.get("items")), width="stretch", hide_index=True)
            if "arithmetic" in r["diagnostics"]:
                st.markdown("**Aritmética del pedido**")
                bloque_aritmetica(r["diagnostics"]["arithmetic"])
        if r["diagnostics"].get("aviso"):
            st.info(r["diagnostics"]["aviso"])
    ref = clip_de_archivo(nombre)
    if ref:
        task, clip = ref
        st.markdown(f"**Comparación con la referencia** (`{clip}` está en el corpus)")
        wer, cer, wern = wer_cer(referencias(task)[clip], r["transcript"])
        a, b, c = st.columns(3)
        a.metric("WER vs guion", f"{wer:.1%}")
        b.metric("CER vs guion", f"{cer:.1%}")
        c.metric("WER (números normalizados)", f"{wern:.1%}")
        if r["fields"] and TAREAS_POR_TASK[task] == schema:
            acc = field_accuracy(config(), task, clip, r["fields"], ground_truth(task))
            filas = [{"Campo": k, "Coincide con el ground truth": ("✅" if v else "❌") if isinstance(v, bool) else f"{v:.0%}"}
                     for k, v in acc.items()]
            st.dataframe(pd.DataFrame(filas), width="stretch", hide_index=True)
        elif r["fields"]:
            st.warning("El nombre del archivo indica otro tipo de audio que el elegido arriba.")


TAREAS_POR_TASK = {t: s for t, s in TAREAS.values()}


# ── Pestaña 2: Benchmark ──────────────────────────────────────────────────────

def pestana_benchmark(task):
    st.caption("WER = porcentaje de palabras mal transcritas respecto al guion (textos normalizados: minúsculas y sin puntuación). "
               "Los intervalos son bootstrap al 95 % sobre los clips; con 5 clips por tarea son anchos.")
    resumen = csv_metricas(task, "benchmark_summary.csv")
    if resumen is None:
        st.info("Aún no hay resultados del benchmark para esta tarea (ver `engine/benchmark.py`).")
        return
    d = resumen.copy()
    d["Configuración"] = d["model"] + " · " + d["compute_type"] + " · " + d["device"] + " · glosario " + d["glossary"]
    base = alt.Chart(d).encode(y=alt.Y("Configuración:N", sort="x", axis=alt.Axis(labelLimit=320, title=None)))
    escala = alt.Scale(domain=[0, float(d["wer_ci_high"].max()) * 1.05])  # el eje arranca en 0: las barras no deben exagerar diferencias
    barras = base.mark_bar().encode(x=alt.X("wer:Q", title="WER", axis=alt.Axis(format="%"), scale=escala),
                                    color=alt.Color("glossary:N", title="Glosario"),
                                    tooltip=["Configuración", alt.Tooltip("wer:Q", format=".1%"), alt.Tooltip("cer:Q", format=".1%")])
    error = base.mark_errorbar(color="#444").encode(x=alt.X("wer_ci_low:Q", title="WER", scale=escala), x2="wer_ci_high:Q")
    st.altair_chart((barras + error).properties(height=max(260, 26 * len(d))), width="stretch")
    tabla = pd.DataFrame({
        "Configuración": d["Configuración"], "WER %": d["wer"].map(pct),
        "IC 95 % (WER %)": d.apply(lambda r: f"{pct(r.wer_ci_low)} – {pct(r.wer_ci_high)}", axis=1),
        "CER %": d["cer"].map(pct), "WER con números normalizados %": d["wer_numnorm"].map(pct),
        "Tiempo medio por audio (s)": d["elapsed_s"].round(1), "VRAM pico en GPU (MB)": d["vram_device_mb"].round(0)})
    decimal = {c: st.column_config.NumberColumn(format="%.1f") for c in tabla.columns if c != "Configuración" and "IC" not in c}
    st.dataframe(tabla.sort_values("WER %"), width="stretch", hide_index=True, column_config=decimal)

    st.subheader("Efecto del glosario")
    g = csv_metricas(task, "glossary_effect.csv")
    if g is not None and len(g):
        st.caption("Δ negativo = el glosario ayuda. «Distinguible de cero» = el IC 95 % no incluye el 0.")
        st.dataframe(pd.DataFrame({
            "Configuración": g["model"] + " · " + g["compute_type"] + " · " + g["device"], "WER sin glosario %": g["wer_sin_glosario"].map(pct),
            "WER con glosario %": g["wer_con_glosario"].map(pct), "Δ (puntos)": g["delta_wer"].map(lambda x: pct(x, 2)),
            "IC 95 % Δ": g.apply(lambda r: f"{pct(r.delta_ci_low, 2)} – {pct(r.delta_ci_high, 2)}", axis=1),
            "Distinguible de cero": g["ic_excluye_cero"].map({True: "✅", False: "—"}),
            "Clips que mejoran / empeoran": g["clips_mejoran"].astype(str) + " / " + g["clips_empeoran"].astype(str)}),
            width="stretch", hide_index=True,
            column_config={c: st.column_config.NumberColumn(format="%.1f") for c in ("WER sin glosario %", "WER con glosario %")}
            | {"Δ (puntos)": st.column_config.NumberColumn(format="%.2f")})

    st.subheader("¿Cambia el texto entre precisiones o dispositivos?")
    c = csv_metricas(task, "precision_changes.csv")
    if c is not None and len(c):
        agg = c.groupby(["model", "eje", "config_a", "config_b"])["texto_cambio"].agg(["sum", "count"]).reset_index()
        st.dataframe(pd.DataFrame({"Modelo": agg["model"], "Comparación": agg["eje"], "Config. A": agg["config_a"], "Config. B": agg["config_b"],
                                   "Pares con texto distinto": agg["sum"].astype(str) + " de " + agg["count"].astype(str)}),
                     width="stretch", hide_index=True)
    s = csv_metricas(task, "benchmark_skipped.csv")
    if s is not None and len(s):
        with st.expander("Combinaciones omitidas"):
            st.dataframe(s, width="stretch", hide_index=True)


# ── Pestaña 3: Escalera de degradación ────────────────────────────────────────

def pestana_escalera():
    st.caption("Cada llamada de ventas se degrada en 11 niveles (`tasks/task2_sales/degradation/build_ladder.py`) y se transcribe. "
               "Δ WER = cuánto sube el WER respecto al audio original (pareado por clip); la barra es el IC 95 %.")
    curva = csv_metricas("task2_sales", "ladder_curve.csv")
    if curva is None or curva.empty:
        st.info("Aún no hay resultados de la escalera (ver `python -m engine.benchmark --ladder-dir tasks/task2_sales/degradation`).")
        return
    modelos = sorted(curva["model"].unique())
    elegidos = st.multiselect("Modelos", modelos, default=modelos)
    c = curva[curva["model"].isin(elegidos)].copy()
    if c.empty:
        st.info("Elige al menos un modelo.")
        return
    orden = [n for n, _ in sorted(c.drop_duplicates("level")[["level", "family", "severity"]].set_index("level").iterrows(),
                                  key=lambda kv: (ORDEN_FAMILIA.get(kv[1]["family"], 9), kv[1]["severity"]))]
    base = alt.Chart(c).encode(x=alt.X("level:N", sort=orden, axis=alt.Axis(labelAngle=-40, title="Nivel de degradación")),
                               color=alt.Color("model:N", title="Modelo"))
    linea = base.mark_line(point=True, opacity=0.6).encode(y=alt.Y("delta_wer:Q", title="Δ WER vs original", axis=alt.Axis(format="%")),
                                                          tooltip=["model", "level", "param", alt.Tooltip("wer_level:Q", format=".1%"),
                                                                   alt.Tooltip("delta_wer:Q", format="+.1%")])
    error = base.mark_errorbar(thickness=2).encode(y=alt.Y("delta_ci_low:Q", title="Δ WER vs original"), y2="delta_ci_high:Q")
    cero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(strokeDash=[4, 4], color="#888").encode(y="y:Q")
    st.altair_chart((cero + linea + error).properties(height=380), width="stretch")
    tabla = pd.DataFrame({
        "Modelo": c["model"], "Nivel": c["level"], "Parámetro": c["param"], "WER original %": c["wer_original"].map(pct),
        "WER del nivel %": c["wer_level"].map(pct), "Δ (puntos)": c["delta_wer"].map(lambda x: pct(x, 1)),
        "IC 95 % Δ": c.apply(lambda r: f"{pct(r.delta_ci_low)} – {pct(r.delta_ci_high)}", axis=1),
        "Distinguible de cero": c["ic_excluye_cero"].map({True: "✅", False: "—"}),
        "_o": c["level"].map({n: i for i, n in enumerate(orden)})})
    st.dataframe(tabla.sort_values(["Modelo", "_o"]).drop(columns="_o"), width="stretch", hide_index=True,
                 column_config={c: st.column_config.NumberColumn(format="%.1f") for c in ("WER original %", "WER del nivel %", "Δ (puntos)")})
    st.markdown("Ruido blanco con SNR de 20, 10, 5 y 0 dB · banda telefónica (300–3400 Hz, 8 kHz) · MP3 a 32, 16 y 8 kbps · "
                "volumen reducido 20, 30 y 40 dB.")


# ── Pestaña 4: Ejemplos ───────────────────────────────────────────────────────

def pestana_ejemplos(task):
    cfg = config()
    schema = TAREAS_POR_TASK[task]
    refs = referencias(task)
    clip = st.selectbox("Clip", sorted(refs), key=f"ej_clip_{task}")
    idx = indice_transcripciones(task)
    idx = idx[idx["clip"] == clip]
    if idx.empty:
        st.info("No hay transcripciones en caché para este clip.")
        return
    escalera = carpeta_escalera(task)
    meta = load_ladder_meta(escalera) if escalera else {}
    niveles = sorted(idx["level"].unique(), key=lambda n: (n != "", ORDEN_FAMILIA.get(meta.get(n, ("", 0))[0], 9), meta.get(n, ("", 0))[1]))
    etiqueta = {n: ("(audio original, sin degradar)" if n == "" else n) for n in niveles}
    nivel = st.selectbox("Nivel de degradación", niveles, format_func=etiqueta.get, key=f"ej_nivel_{task}")
    sub = idx[idx["level"] == nivel].copy()
    sub["cfg"] = sub["model"] + " · " + sub["compute_type"] + " · " + sub["device"] + " · glosario " + sub["glossary"].map({True: "sí", False: "no"})
    elegida = st.selectbox("Configuración", sub["cfg"].tolist(), key=f"ej_cfg_{task}")
    fila = sub[sub["cfg"] == elegida].iloc[0]

    audio = task_dir(cfg, task, "audio") / next(iter([p.name for p in task_dir(cfg, task, "audio").glob(f"{clip}.*")]), "")
    if nivel and escalera:
        audio = escalera / nivel / f"{clip}.wav"
    if audio.is_file():
        st.audio(audio.read_bytes())
    else:
        st.caption("Audio no disponible aquí: los `.wav` degradados no se versionan (se regeneran con `build_ladder.py`).")

    wer, cer, wern = wer_cer(refs[clip], fila["transcript"])
    a, b, c, d = st.columns(4)
    a.metric("WER vs guion", f"{wer:.1%}")
    b.metric("CER", f"{cer:.1%}")
    c.metric("WER (números normalizados)", f"{wern:.1%}")
    d.metric("Tiempo de transcripción", f"{fila['elapsed_s']:g} s")
    izq, der = diff_html(refs[clip], fila["transcript"])
    col_i, col_d = st.columns(2)
    col_i.markdown("**Guion (referencia)** · <mark class='del'>falta o cambia</mark>", unsafe_allow_html=True)
    col_i.markdown(izq, unsafe_allow_html=True)
    col_d.markdown("**Transcripción de Whisper** · <mark class='ins'>añadido o distinto</mark>", unsafe_allow_html=True)
    col_d.markdown(der, unsafe_allow_html=True)

    st.subheader("Ground truth frente a lo extraído por las reglas")
    gt = ground_truth(task)[clip]
    got = RuleExtractor(cfg).extract(fila["transcript"], schema)
    acc = field_accuracy(cfg, task, clip, got, ground_truth(task))
    if schema == "interview":
        esperado = {k: gt[k] for k in ("anios_experiencia", "ultimo_puesto", "tecnologias", "pretension_salarial", "disponibilidad", "nivel_ingles")}
    else:
        esperado = {"items": items_txt(json.loads(gt["items_json"])), "promocion": gt["promocion"], "direccion_entrega": gt["direccion_entrega"],
                    "metodo_pago": gt["metodo_pago"], "total_dicho": gt["total_dicho"]}
    filas = []
    for campo, valor in esperado.items():
        extraido = items_txt(got["items"]) if campo == "items" else valor_txt(got.get(campo))
        ok = acc.get(campo)
        filas.append({"Campo": campo, "Ground truth": valor, "Extraído": extraido, "": "✅" if ok else "❌"})
    st.dataframe(pd.DataFrame(filas), width="stretch", hide_index=True)
    if schema == "sales":
        st.caption(f"Ground truth del total correcto: S/ {gt['total_correcto']} · ¿el operador se equivocó en el total? {gt['total_es_incorrecto']} · "
                   f"¿hubo corrección del cliente? {gt['tiene_correccion']}")


# ── Datos de resultados (compartidos por los tabs 2 y 3) ──────────────────────

def configs_asr(task):
    """Configuraciones de ASR con transcripciones del audio original: [(model, compute_type, device, glossary)]."""
    idx = indice_transcripciones(task)
    idx = idx[idx["level"] == ""]
    return sorted(idx[["model", "compute_type", "device", "glossary"]].drop_duplicates().itertuples(index=False, name=None))


def config_principal(task):
    """La de menor WER normalizado del benchmark (la misma que usan el notebook y los scripts de métricas)."""
    resumen = csv_metricas(task, "benchmark_summary.csv")
    if resumen is None:
        return None
    m = resumen[resumen["task"] == task].sort_values("wer_numnorm").iloc[0]
    return (m["model"], m["compute_type"], m["device"], m["glossary"] == "on")


def etiqueta_cfg(c):
    return f"{c[0]} · {c[1]} · {c[2]} · glosario {'sí' if c[3] else 'no'}"


def selector_asr(task, clave):
    configs = {etiqueta_cfg(c): c for c in configs_asr(task)}
    if not configs:
        st.warning("No hay transcripciones cacheadas de esta tarea (ver `engine/benchmark.py`).")
        return None
    etiquetas = list(configs)
    principal = config_principal(task)
    pos = etiquetas.index(etiqueta_cfg(principal)) if principal and etiqueta_cfg(principal) in configs else 0
    elegida = st.selectbox("Configuración de ASR (transcripciones cacheadas del audio original)", etiquetas, index=pos, key=f"asr_{clave}",
                           help="Por defecto, la de menor WER del benchmark. Las demás permiten ver cómo cambian los campos con el ASR.")
    return configs[elegida]


def selector_extractor(clave, n_llamadas):
    """Radio de método de extracción. Devuelve el método listo para usar, o None si aún no se puede (sin clave o sin confirmar)."""
    ext = st.radio("Método de extracción", list(EXTRACTORES), format_func=EXTRACTORES.get, horizontal=True, key=f"ext_{clave}")
    if ext == "llm_sim":
        st.warning("Respuestas LLM **simuladas**: escritas a mano viendo el ground truth. Sirven para probar el flujo sin clave, "
                   "pero **no miden a ningún modelo**; no las cites como resultado del LLM.")
        return ext if RESPUESTAS_SIMULADAS.exists() else None
    if ext == "llm_api":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            st.info("No hay `ANTHROPIC_API_KEY` en el entorno: el camino LLM con la API real no está disponible. "
                    "La API es de pago; con la clave en `.env` o en el entorno aparecería aquí.")
            return None
        if not st.session_state.get(f"api_ok_{clave}"):
            if st.button(f"Ejecutar con la API ({n_llamadas} llamadas, de pago)", key=f"api_btn_{clave}"):
                st.session_state[f"api_ok_{clave}"] = True
                st.rerun()
            return None
    return ext


def valor_gt(task, clip, campo):
    fila = ground_truth(task)[clip]
    if campo == "items":
        return items_txt(json.loads(fila["items_json"]))
    v = fila[campo]
    return "—" if v in ("", "null") else v


@st.cache_data(show_spinner="Extrayendo y verificando…")
def extraer(task, extractor, model, compute_type, device, glossary):
    """(tabla larga, aritmética, error). Una fila por clip y campo con lo extraído, el ground truth, si coincide y si
    el valor aparece literalmente en la transcripción."""
    cfg, schema, gt = config(), TAREAS_POR_TASK[task], ground_truth(task)
    idx = indice_transcripciones(task)
    idx = idx[(idx["level"] == "") & (idx["model"] == model) & (idx["compute_type"] == compute_type)
              & (idx["device"] == device) & (idx["glossary"] == glossary)]
    cliente = ClienteSimulado(json.loads(RESPUESTAS_SIMULADAS.read_text(encoding="utf-8"))) if extractor == "llm_sim" else None
    motor = "rules" if extractor == "rules" else "llm"
    filas, aritmetica = [], []
    for clip, texto in sorted(zip(idx["clip"], idx["transcript"])):
        if cliente:
            cliente.clip = clip
        r = process_audio(None, schema, config_path=str(RAIZ / "config.yaml"), extractor=motor, transcript=texto, llm_client=cliente)
        if r["error"]:
            return None, None, f"{clip}: {r['error']}"
        acc = field_accuracy(cfg, task, clip, r["fields"], gt)
        for campo in CAMPOS[schema]:
            valor = r["fields"].get(campo)
            filas.append({"clip": clip, "campo": campo,
                          "valor_extraido": items_txt(valor) if campo == "items" else valor_txt(valor),
                          "valor_ground_truth": valor_gt(task, clip, campo), "match": "✅" if acc[campo] else "❌",
                          "verified": ICONO.get(r["verified_fields"].get(campo, "sin_valor"), "—").split(" ")[0],
                          "_ok": bool(acc[campo])})
        if schema == "sales":
            fila_gt = gt[clip]
            a = validate_order_arithmetic(r["fields"], ground_truth={
                "items": json.loads(fila_gt["items_json"]), "total_dicho": fila_gt["total_dicho"], "total_correcto": fila_gt["total_correcto"]})
            b = a["breakdown"]
            aritmetica.append({"clip": clip, "Σ cantidad × precio": b.get("subtotal"), "− promoción": b.get("descuento") or 0,
                               "+ paquete promocional": b.get("paquete") or 0, "total esperado": a["expected_total"], "total dicho": a["total_dicho"], "diferencia": a["difference"],
                               "estado": a["status"], "diagnóstico": a["diagnosis"], "trampa en el ground truth": fila_gt["total_es_incorrecto"]})
    return pd.DataFrame(filas), (pd.DataFrame(aritmetica) if aritmetica else None), None


def metricas_asr(task, cfg_asr):
    """Promedio de WER, WER con números normalizados y CER de la configuración elegida (benchmark_detail.csv)."""
    d = csv_metricas(task, "benchmark_detail.csv")
    if d is None:
        return None
    m, ct, dev, gl = cfg_asr
    d = d[(d["model"] == m) & (d["compute_type"] == ct) & (d["device"] == dev) & (d["glossary"] == ("on" if gl else "off"))]
    return d if len(d) else None


def bloque_resultados(task, clave):
    """Tabla clip × campo, métricas de transcripción y exactitud por campo, con selector de ASR y de método de extracción."""
    schema = TAREAS_POR_TASK[task]
    cfg_asr = selector_asr(task, clave)
    if cfg_asr is None:
        return None
    n = len(referencias(task))
    metodo = selector_extractor(clave, n)
    if metodo is None:
        return None
    tabla, aritmetica, error = extraer(task, metodo, *cfg_asr)
    if error:
        st.error(f"El extractor falló: {error}")
        return None
    if tabla is None or tabla.empty:
        st.warning("No hay transcripciones para esa configuración.")
        return None

    st.markdown("**Campos extraídos frente al ground truth**")
    st.caption("`match`: coincide con el ground truth (números con tolerancia, listas como conjunto). "
               "`verified`: el valor aparece literalmente en la transcripción (✅), no aparece (⚠️) o no hay valor (—). "
               "Un valor puede estar verificado y aun así ser incorrecto, y al revés.")
    st.dataframe(tabla.drop(columns="_ok"), width="stretch", hide_index=True, height=min(740, 38 * (len(tabla) + 1)))

    st.markdown("**Métricas**")
    wer = metricas_asr(task, cfg_asr)
    c1, c2, c3, c4 = st.columns(4)
    if wer is not None:
        c1.metric("WER promedio", f"{wer['wer'].mean():.1%}", help="Capa transcripción: palabras mal transcritas frente al guion.")
        c2.metric("WER (números normalizados)", f"{wer['wer_numnorm'].mean():.1%}")
        c3.metric("CER promedio", f"{wer['cer'].mean():.1%}")
    else:
        st.info("No hay `benchmark_detail.csv` para esta configuración: sin WER/CER.")
    c4.metric("Campos correctos (registro)", f"{tabla['_ok'].mean():.0%}", help="Capa registro: fracción de campos que coinciden con el ground truth.")
    por_campo = tabla.groupby("campo", sort=False)["_ok"].mean().reset_index().rename(columns={"_ok": "exactitud"})
    grafico = alt.Chart(por_campo).mark_bar().encode(
        y=alt.Y("campo:N", sort=None, title=None), x=alt.X("exactitud:Q", title="Exactitud por campo", axis=alt.Axis(format="%"),
                                                           scale=alt.Scale(domain=[0, 1])),
        tooltip=["campo", alt.Tooltip("exactitud:Q", format=".0%")]).properties(height=34 * len(por_campo) + 30)
    izq, der = st.columns([3, 2])
    izq.altair_chart(grafico, width="stretch")
    der.dataframe(por_campo.assign(exactitud=por_campo["exactitud"].map(lambda x: f"{x:.0%}")), width="stretch", hide_index=True)
    return tabla, aritmetica, cfg_asr


# ── Pestaña 1: Problema y método ──────────────────────────────────────────────

def pestana_problema():
    st.header("Del audio a un registro verificado")
    st.markdown(
        "Una entrevista laboral o una llamada de pedidos contiene datos valiosos (sueldo pretendido, años de experiencia, "
        "platos, cantidades, dirección, total) que hoy quedan encerrados en un audio. Este proyecto los **convierte en un registro "
        "estructurado** y, sobre todo, **verifica cada campo contra lo que realmente se dijo**: un campo solo se marca como "
        "verificado si su valor aparece literalmente en la transcripción, y en las ventas se comprueba además que "
        "`cantidad × precio − promoción` cuadre con el total.")
    st.subheader("Lo que existe y lo que falta")
    st.caption("Resumen de las funciones de transcripción de uso general; lo que se compara es el tipo de resultado, no su calidad.")
    st.dataframe(pd.DataFrame([
        {"Herramienta": "WhatsApp", "Qué entrega": "Transcripción de notas de voz (texto)", "Campos estructurados": "❌", "Verificación contra lo dicho": "❌"},
        {"Herramienta": "YouTube", "Qué entrega": "Subtítulos automáticos (texto con tiempos)", "Campos estructurados": "❌", "Verificación contra lo dicho": "❌"},
        {"Herramienta": "Zoom", "Qué entrega": "Transcripción y resúmenes de la reunión", "Campos estructurados": "❌ (resumen libre, no un esquema fijo)", "Verificación contra lo dicho": "❌"},
        {"Herramienta": "Este proyecto", "Qué entrega": "Registro con campos de un esquema + bandera por campo", "Campos estructurados": "✅", "Verificación contra lo dicho": "✅ literal, y aritmética en ventas"},
    ]), width="stretch", hide_index=True)
    st.markdown("Transcribir no basta: falta pasar del texto a **campos** y saber **cuáles son de fiar**.")

    st.subheader("El pipeline")
    st.graphviz_chart('''digraph G { rankdir=LR; node [shape=box, style="rounded,filled", fillcolor="#eef2ff", color="#6366f1", fontname="Helvetica"];
        audio [label="Audio\\n(entrevista o llamada)"]; asr [label="Transcripción\\nfaster-whisper"]; txt [label="Texto", shape=note, fillcolor="#fff"];
        ext [label="Extracción\\nreglas (regex) o LLM"]; cam [label="Campos del esquema", shape=note, fillcolor="#fff"];
        ver [label="Verificación\\nliteral + aritmética", fillcolor="#dcfce7", color="#16a34a"]; reg [label="Registro verificado\\n(bandera por campo)", fillcolor="#dcfce7", color="#16a34a"];
        audio -> asr -> txt -> ext -> cam -> ver -> reg; }''')
    st.markdown(
        "1. **Transcribir** con `faster-whisper` (modelos `medium` y `large-v3`, GPU o CPU).\n"
        "2. **Extraer** los campos del esquema con expresiones regulares en español o con un LLM (ambos implementan `extract(texto, esquema)`).\n"
        "3. **Verificar** cada valor: primero de forma literal, luego con los números hablados pasados a dígitos; en ventas, la aritmética del pedido "
        "con un diagnóstico de quién se equivocó (el hablante o el ASR).\n"
        "4. **Medir en dos capas**: la transcripción (WER, CER) y el registro (exactitud por campo). Se miden por separado porque no van de la mano.")

    contrastes = csv_metricas("task1_interview", "extraction_metrics_contrasts.csv")
    if contrastes is not None and len(contrastes):
        st.subheader("Por qué dos capas: WER y registro no van de la mano")
        cols = st.columns(len(contrastes))
        for col, (_, f) in zip(cols, contrastes.iterrows()):
            col.metric(f["contraste"], f"{f['clip']}")
            col.markdown(f"{f['palabras_erradas']} palabras mal transcritas · {f['campos_correctos']} campos correctos")
        st.caption("Medidos sobre las entrevistas con el extractor por reglas (detalle en la pestaña de Task 1). "
                   "Una sola palabra mal transcrita en un campo crítico rompe el registro; muchas palabras de relleno mal transcritas no lo tocan.")
    with st.expander("Diagrama del pipeline (imagen)"):
        ruta = RAIZ / "docs" / "pipeline_diagram.png"
        st.image(str(ruta)) if ruta.exists() else st.caption("`docs/pipeline_diagram.png` no está disponible.")


# ── Pestaña 2: Resultados Task 1 ──────────────────────────────────────────────

def pestana_task1():
    task = "task1_interview"
    st.caption("5 entrevistas laborales · 6 campos por entrevista · transcripciones cacheadas de Whisper (sin volver a transcribir).")
    bloque_resultados(task, "t1")
    with st.expander("Benchmark completo del ASR (modelo × precisión × dispositivo)"):
        pestana_benchmark(task)
    with st.expander("Ver un clip en detalle: guion frente a transcripción"):
        pestana_ejemplos(task)


# ── Pestaña 3: Resultados Task 2 ──────────────────────────────────────────────

def comparacion_por_nivel():
    """WER (transcripción) frente a exactitud del registro en L0-L3: el WER sube, la exactitud no siempre baja."""
    wer = csv_metricas("task2_sales", "l0_l3_wer_summary.csv")
    reg = csv_metricas("task2_sales", "l0_l3_summary.csv")
    det = csv_metricas("task2_sales", "l0_l3_detection.csv")
    if wer is None or reg is None:
        st.info("Aún no hay resultados de L0-L3 (`python -m engine.evaluate_ladder --levels L0 L1 L2 L3 --prefix l0_l3`).")
        return
    st.caption("L0 es el audio sin tocar; L1 simula una nota de voz de WhatsApp (Opus 24 kbps mono); L2, una llamada telefónica "
               "(300–3400 Hz a 8 kHz); L3, un restaurante ruidoso (Opus + ruido ambiente real a SNR 10 dB). Registro medido con el extractor por reglas.")
    modelo = st.radio("Modelo de ASR", sorted(wer["model"].unique()), horizontal=True, key="nivel_modelo", index=0)
    w = wer[wer["model"] == modelo].set_index("level")
    r = reg[reg["model"] == modelo].set_index("level")
    niveles = [n for n in NIVELES_L if n in w.index and n in r.index]
    if not niveles:
        st.info("Sin datos para ese modelo.")
        return
    orden = [NIVELES_L[n] for n in niveles]
    wer_df = pd.DataFrame({"nivel": orden, "valor": [w.loc[n, "wer_numnorm"] for n in niveles]})
    reg_df = pd.DataFrame({"nivel": orden, "valor": [r.loc[n, "todos_los_campos"] for n in niveles]})

    def panel(df, titulo, color, tope):
        base = alt.Chart(df, title=titulo).encode(
            x=alt.X("nivel:N", sort=orden, title=None, axis=alt.Axis(labelAngle=-15, labelLimit=260)),
            y=alt.Y("valor:Q", title=None, axis=alt.Axis(format="%"), scale=alt.Scale(domain=[0, tope])))
        return (base.mark_line(point=True, color=color) + base.mark_text(dy=-12, fontSize=12, color=color).encode(text=alt.Text("valor:Q", format=".1%"))
                ).properties(height=170)
    # cada panel con su propia escala, ambas desde 0: así se ve cuánto sube el WER sin que el registro lo tape
    st.altair_chart(alt.vconcat(panel(wer_df, "Capa transcripción: WER (palabras mal transcritas)", "#d97706", max(0.3, float(wer_df["valor"].max()) * 1.6)),
                                panel(reg_df, "Capa registro: campos correctos", "#1d4ed8", 1.0)).resolve_scale(x="shared"), width="stretch")
    w0, w3 = w.loc[niveles[0], "wer_numnorm"], w.loc[niveles[-1], "wer_numnorm"]
    r0, r3 = r.loc[niveles[0], "todos_los_campos"], r.loc[niveles[-1], "todos_los_campos"]
    sube_wer = w3 > w0
    st.markdown(f"**Lectura ({modelo}):** del audio original a {niveles[-1]} el WER pasa de {w0:.1%} a {w3:.1%} "
                f"({'sube' if sube_wer else 'no sube'}) y la exactitud del registro de {r0:.0%} a {r3:.0%}. "
                + ("En los niveles intermedios el registro se mantiene aunque el WER suba." if
                   any(w.loc[n, "wer_numnorm"] > w0 and r.loc[n, "todos_los_campos"] >= r0 for n in niveles[1:-1]) else ""))
    tabla = pd.DataFrame({"Nivel": [NIVELES_L[n] for n in niveles], "WER %": [round(w.loc[n, "wer_numnorm"] * 100, 1) for n in niveles],
                          "CER %": [round(w.loc[n, "cer"] * 100, 1) for n in niveles],
                          "Campos correctos %": [round(r.loc[n, "todos_los_campos"] * 100) for n in niveles]})
    if det is not None:
        d = det[det["model"] == modelo].set_index("level")
        tabla["Trampas detectadas"] = [f"{int(d.loc[n, 'detectadas'])}/{int(d.loc[n, 'trampas'])}" if n in d.index else "—" for n in niveles]
        tabla["…por la razón correcta"] = [f"{int(d.loc[n, 'detectadas_como_hablante'])}/{int(d.loc[n, 'trampas'])}" if n in d.index else "—" for n in niveles]
    st.dataframe(tabla, width="stretch", hide_index=True)
    st.caption("«Trampas»: totales mal dichos a propósito (ground truth `total_es_incorrecto`). «Por la razón correcta»: el diagnóstico atribuye el error "
               "al hablante; si no, se detectó porque el ASR perdió una cifra. Con 5 clips las diferencias son ilustrativas, no estadísticas.")


def pestana_task2():
    task = "task2_sales"
    st.caption("5 llamadas de ventas a un restaurante · 5 campos por llamada · incluye correcciones del cliente y totales mal dichos a propósito.")
    res = bloque_resultados(task, "t2")
    if res is not None and res[1] is not None:
        st.markdown("**Validación aritmética del pedido** (`Σ cantidad × precio − promoción (+ precio del paquete, si la promoción es un paquete)` frente al total dicho)")
        st.dataframe(res[1], width="stretch", hide_index=True,
                     column_config={c: st.column_config.NumberColumn(format="%g") for c in ("Σ cantidad × precio", "− promoción", "+ paquete promocional", "total esperado", "total dicho", "diferencia")})
        st.caption("`diagnóstico` usa el total correcto del ground truth: **hablante** = los ítems cuadran con el total correcto y el operador dijo otro; "
                   "**asr** = el total calculado no coincide con ninguno (se perdió o leyó mal una cifra); **indeterminado** = faltan precios.")
    st.subheader("Comparación por nivel de degradación")
    comparacion_por_nivel()
    with st.expander("Benchmark completo del ASR (modelo × precisión × dispositivo)"):
        pestana_benchmark(task)
    with st.expander("Escalera de degradación completa (12 niveles: ruido, banda telefónica, MP3, volumen)"):
        pestana_escalera()
    with st.expander("Ver una llamada en detalle: guion frente a transcripción"):
        pestana_ejemplos(task)


# ── Pestaña 4: Demo en vivo ───────────────────────────────────────────────────

def pestana_demo():
    cfg = config()
    st.caption("Sube un audio (WAV recomendado), elige el tipo y se transcribe con `faster-whisper` (modelo **medium**), se extraen los campos con las "
               "reglas y se verifican literalmente. Corre en CPU, pero `medium` tarda: la primera vez descarga el modelo (~1.5 GB) y "
               "transcribir un minuto de audio puede tomar varios minutos.")
    izq, der = st.columns(2)
    with izq:
        archivo = st.file_uploader("Audio", type=EXT_AUDIO, key="demo_audio")
        ejemplos = {p.name: p for t in TAREAS.values() for p in sorted(task_dir(cfg, t[0], "audio").glob("*")) if p.suffix[1:] in EXT_AUDIO}
        ejemplo = st.selectbox("…o un audio del repositorio", ["—"] + list(ejemplos), key="demo_ejemplo")
    with der:
        etiqueta_tipo = st.radio("Tipo de audio", ["Entrevista", "Venta"], horizontal=True, key="demo_tipo")
        schema = "interview" if etiqueta_tipo == "Entrevista" else "sales"
        st.markdown("**Modelo:** `medium` · **Extractor:** reglas · **Verificación:** literal (con números hablados normalizados)")
        glosario = st.checkbox("Usar el glosario de dominio (initial_prompt)", key="demo_glosario")
    if archivo is not None:
        nombre, datos = archivo.name, archivo.getvalue()
    elif ejemplo != "—":
        nombre, datos = ejemplo, ejemplos[ejemplo].read_bytes()
    else:
        nombre, datos = None, None
    if st.button("Transcribir, extraer y verificar", type="primary", disabled=datos is None, width="stretch", key="demo_run"):
        with tempfile.NamedTemporaryFile(suffix=Path(nombre).suffix, delete=False) as f:
            f.write(datos)
            ruta = f.name
        try:
            with st.spinner("Transcribiendo con medium… (la primera vez descarga el modelo)"):
                r = process_audio(ruta, schema, extractor="rules", model="medium", device="auto", compute_type="auto", glossary=glosario)
            st.session_state["ultimo"] = {"r": r, "schema": schema, "nombre": nombre}
        finally:
            os.unlink(ruta)
    if datos is None:
        st.info("Sube un audio o elige uno del repositorio para empezar.")
    if "ultimo" in st.session_state:
        st.divider()
        st.subheader(f"Resultado: {st.session_state['ultimo']['nombre']}")
        mostrar_resultado(st.session_state["ultimo"])


# ── Página ────────────────────────────────────────────────────────────────────

st.title("🎙️ From Voice to Record")
modo = config().get("pipeline", {}).get("extractor", "auto")
st.caption(f"Whisper (faster-whisper) convierte entrevistas laborales y llamadas de ventas en registros estructurados y verificables. "
           f"GPU: {'sí' if cuda_available() else 'no (CPU)'} · extractor por defecto: {modo}")
t1, t2, t3, t4 = st.tabs(["📖 Problema y Método", "🧑‍💼 Resultados Task 1 (Entrevistas)", "🍽️ Resultados Task 2 (Ventas Restaurante)", "🎙️ Demo en Vivo"])
with t1:
    pestana_problema()
with t2:
    pestana_task1()
with t3:
    pestana_task2()
with t4:
    pestana_demo()

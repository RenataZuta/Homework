"""From Voice to Record — interfaz de la Tarea 4.

Cuatro pestañas:
  1. Probador: sube un audio y obtén transcripción, campos extraídos, verificación y (en ventas) aritmética del pedido.
  2. Benchmark: WER/CER, tiempo y VRAM por modelo × precisión × dispositivo, con y sin glosario.
  3. Escalera de degradación: cuánto sube el WER al degradar el audio (ruido, banda telefónica, MP3, volumen).
  4. Ejemplos: un clip a la vez, con guion, ground truth y transcripciones lado a lado.

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
from engine.core import process_audio  # noqa: E402
from engine.extractor import RuleExtractor  # noqa: E402
from engine.transcriber import cuda_available, supported_compute_types  # noqa: E402
from engine.validator import normalize_spoken_numbers  # noqa: E402

st.set_page_config(page_title="From Voice to Record", page_icon="🎙️", layout="wide")

TAREAS = {"Entrevistas laborales": ("task1_interview", "interview"), "Llamadas de ventas": ("task2_sales", "sales")}
EXT_AUDIO = ["m4a", "wav", "mp3", "ogg", "opus", "flac"]
ICONO = {"verificado": "✅ verificado", "sin_verificar": "⚠️ sin verificar", "sin_valor": "— sin valor"}
ORDEN_FAMILIA = {"original": 0, "ruido": 1, "telefono": 2, "compresion": 3, "volumen": 4}

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


# ── Pestaña 1: Probador ───────────────────────────────────────────────────────

def pestana_probador():
    cfg = config()
    hay_gpu = cuda_available()
    st.caption("Sube un audio (o usa uno del repositorio), elige el modelo y se transcribe, extrae y verifica todo. "
               "En CPU `tiny` y `base` son rápidos pero menos precisos; `medium` y `large-v3` tardan bastante.")
    izq, der = st.columns(2)
    with izq:
        archivo = st.file_uploader("Audio", type=EXT_AUDIO)
        ejemplos = {p.name: p for t in TAREAS.values() for p in sorted(task_dir(cfg, t[0], "audio").glob("*")) if p.suffix[1:] in EXT_AUDIO}
        ejemplo = st.selectbox("…o un audio del repositorio", ["—"] + list(ejemplos))
    with der:
        etiqueta_tipo = st.radio("Tipo de audio", list(TAREAS), horizontal=True)
        task, schema = TAREAS[etiqueta_tipo]
        modelos = list(dict.fromkeys(["tiny", "base", "small"] + cfg["asr"]["models"]))
        defecto = cfg["asr"]["default_model"] if hay_gpu else "tiny"
        modelo = st.selectbox("Modelo", modelos, index=modelos.index(defecto))
        c1, c2 = st.columns(2)
        dispositivo = c1.selectbox("Dispositivo", ["auto", "cpu"] + (["cuda"] if hay_gpu else []))
        real = "cuda" if (dispositivo == "cuda" or (dispositivo == "auto" and hay_gpu)) else "cpu"
        precision = c2.selectbox("Precisión", ["auto"] + sorted(supported_compute_types(real)))
        glosario = st.checkbox("Usar el glosario de dominio (initial_prompt)")
        opciones_ext = ["rules"] + (["llm", "both"] if os.environ.get("ANTHROPIC_API_KEY") else [])
        extractor = st.selectbox("Extractor", opciones_ext, help="rules = sin API ni clave. llm/both solo aparecen si hay ANTHROPIC_API_KEY (de pago).")

    if archivo is not None:
        nombre, datos = archivo.name, archivo.getvalue()
    elif ejemplo != "—":
        nombre, datos = ejemplo, ejemplos[ejemplo].read_bytes()
    else:
        nombre, datos = None, None
    if st.button("Transcribir y extraer", type="primary", disabled=datos is None, width="stretch"):
        with tempfile.NamedTemporaryFile(suffix=Path(nombre).suffix, delete=False) as f:
            f.write(datos)
            ruta = f.name
        try:
            with st.spinner(f"Transcribiendo con {modelo} en {real}… (la primera vez descarga el modelo)"):
                r = process_audio(ruta, schema, extractor=extractor, model=modelo, device=dispositivo,
                                  compute_type=precision, glossary=glosario)
            st.session_state["ultimo"] = {"r": r, "schema": schema, "nombre": nombre}
        finally:
            os.unlink(ruta)
    if datos is None:
        st.info("Sube un audio o elige uno del repositorio para empezar.")
    if "ultimo" in st.session_state:
        st.divider()
        st.subheader(f"Resultado: {st.session_state['ultimo']['nombre']}")
        mostrar_resultado(st.session_state["ultimo"])


# ── Pestaña 2: Benchmark ──────────────────────────────────────────────────────

def pestana_benchmark():
    st.caption("WER = porcentaje de palabras mal transcritas respecto al guion (textos normalizados: minúsculas y sin puntuación). "
               "Los intervalos son bootstrap al 95 % sobre los clips; con 5 clips por tarea son anchos.")
    tarea = st.radio("Tarea", list(TAREAS), horizontal=True, key="bench_tarea")
    task = TAREAS[tarea][0]
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

def pestana_ejemplos():
    cfg = config()
    c1, c2 = st.columns(2)
    tarea = c1.radio("Tarea", list(TAREAS), horizontal=True, key="ej_tarea")
    task, schema = TAREAS[tarea]
    refs = referencias(task)
    clip = c2.selectbox("Clip", sorted(refs), key="ej_clip")
    idx = indice_transcripciones(task)
    idx = idx[idx["clip"] == clip]
    if idx.empty:
        st.info("No hay transcripciones en caché para este clip.")
        return
    escalera = carpeta_escalera(task)
    meta = load_ladder_meta(escalera) if escalera else {}
    niveles = sorted(idx["level"].unique(), key=lambda n: (n != "", ORDEN_FAMILIA.get(meta.get(n, ("", 0))[0], 9), meta.get(n, ("", 0))[1]))
    etiqueta = {n: ("(audio original, sin degradar)" if n == "" else n) for n in niveles}
    nivel = st.selectbox("Nivel de degradación", niveles, format_func=etiqueta.get, key="ej_nivel")
    sub = idx[idx["level"] == nivel].copy()
    sub["cfg"] = sub["model"] + " · " + sub["compute_type"] + " · " + sub["device"] + " · glosario " + sub["glossary"].map({True: "sí", False: "no"})
    elegida = st.selectbox("Configuración", sub["cfg"].tolist(), key="ej_cfg")
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


# ── Página ────────────────────────────────────────────────────────────────────

st.title("🎙️ From Voice to Record")
modo = config().get("pipeline", {}).get("extractor", "auto")
st.caption(f"Whisper (faster-whisper) convierte entrevistas laborales y llamadas de ventas en registros estructurados y verificables. "
           f"GPU: {'sí' if cuda_available() else 'no (CPU)'} · extractor por defecto: {modo}")
t1, t2, t3, t4 = st.tabs(["🧪 Probador", "📊 Benchmark", "📉 Escalera de degradación", "🔎 Ejemplos"])
with t1:
    pestana_probador()
with t2:
    pestana_benchmark()
with t3:
    pestana_escalera()
with t4:
    pestana_ejemplos()

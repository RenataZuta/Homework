"""app.py — interfaz Streamlit del asistente sobre contrataciones públicas del Perú.

Ejecutar (desde tarea1/, con el entorno virtual activo):  streamlit run app.py

Esta interfaz SOLO llama a ``MotorRAG.responder(pregunta)`` y lee reportes ya generados por las fases offline. NUNCA reconstruye el índice: lo carga una
vez (``@st.cache_resource``) y, si falta, muestra un error con las instrucciones para construirlo. Toda la lógica RAG vive en ``src/rag_engine``, que no
importa Streamlit.
Pestañas: Consulta · Calidad de extracción · Evaluación · Costos.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import pandas as pd  # noqa: E402

from rag_engine.config import ConfigError, cargar_config  # noqa: E402
from rag_engine.embeddings.base import ErrorEmbeddings  # noqa: E402
from rag_engine.engine import MotorRAG  # noqa: E402
from rag_engine.llm.pricing import ErrorPrecio  # noqa: E402
from rag_engine.retrieval.indice import IndiceNoDisponible  # noqa: E402
from reporting import datos  # noqa: E402

ERRORES_DE_ARRANQUE = (IndiceNoDisponible, ConfigError, ErrorEmbeddings, ErrorPrecio, FileNotFoundError)
ORIGEN = {"recuperado": "recuperado por similitud", "version": "modificatoria forzada (DS 001-2026-EF)", "original": "texto original forzado (para completar la modificatoria)"}
MOTIVO = {"umbral": "la mejor similitud quedó por debajo del umbral", "llm_sin_contexto": "el modelo declaró que el contexto recuperado no alcanza"}
COLORES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]        # categóricos 1-4 en orden fijo (paleta de referencia de la guía de visualización)
SERIES_UMBRAL = [("correctas", "Respuestas correctas (in_domain)"), ("abstenciones_incorrectas", "Abstenciones incorrectas (in_domain)"),
                 ("abstenciones_correctas", "Abstenciones correctas (fuera de dominio)"), ("indebidas", "Respuestas indebidas (fuera de dominio)")]

st.set_page_config(page_title="Contrataciones públicas del Perú · RAG", page_icon="⚖️", layout="wide")


@st.cache_resource(show_spinner=False)
def cargar_cfg():
    return cargar_config()


@st.cache_resource(show_spinner="Cargando el índice y el modelo de embeddings…")
def cargar_motor():
    """UNA sola vez por proceso. Solo LEE el índice ya construido: aquí no se indexa nada (si falta, lanza IndiceNoDisponible con instrucciones)."""
    return MotorRAG.desde_config(cargar_cfg())


def tabla(filas: list[dict], **kw):
    st.dataframe(pd.DataFrame(filas), hide_index=True, **kw)


# ───────────────────────── pestaña Consulta ─────────────────────────

def ejemplos(cfg) -> list[str]:
    """Preguntas de ejemplo: las primeras del set de evaluación (dominio), para probar sin escribir."""
    filas = [f for f in datos.leer_csv(cfg.ruta("eval_preguntas")) if f.get("tipo") == "in_domain"]
    return [f["pregunta"] for f in filas[:1] + filas[1:12:4]][:4]


def mostrar_fuentes(r) -> None:
    if not r.fuentes:
        return
    citadas = [f for f in r.fuentes if f.citada]
    grupos = [("Fragmentos citados por el modelo", citadas), ("Otros fragmentos recuperados (no citados)", [f for f in r.fuentes if not f.citada])] if citadas \
        else [("Fragmentos más cercanos a la pregunta", r.fuentes)]
    for titulo, lista in grupos:
        if not lista:
            continue
        st.markdown(f"**{titulo}**")
        for i, f in enumerate(lista):
            with st.expander(f"{f.documento} · p. {f.pagina} · similitud {f.similitud:.3f} · {ORIGEN.get(f.origen, f.origen)}"):
                st.caption(f"Versión: {f.version} · {f.fragmento_id}")
                st.text_area("Texto del fragmento", f.texto, height=200, disabled=True, label_visibility="collapsed", key=f"frag_{titulo}_{i}_{f.fragmento_id}")


def mostrar_costo(r, cfg) -> None:
    st.markdown("**Costo y latencia de la consulta**")
    if not r.modelo:
        st.info("No hubo llamada al modelo (la compuerta del umbral respondió antes): costo USD 0.")
    c = st.columns(6)
    c[0].metric("Tokens de entrada", f"{r.tokens_entrada:,}")
    c[1].metric("Tokens de salida", f"{r.tokens_salida:,}")
    c[2].metric("Costo real (USD)", f"{r.costo_usd_real:.6f}", help="Lo que se cobra: 0 en la capa gratuita.")
    c[3].metric("Costo de referencia (USD)", f"{r.costo_usd_referencia:.6f}", help="Lo que costaría con el precio de pago del modelo (pricing.yaml).")
    c[4].metric("Latencia total", f"{r.latencia_ms / 1000:.2f} s")
    c[5].metric("Modelo", r.modelo or "—", help=f"Proveedor: {r.proveedor or '—'}")


def mostrar_resultado(r, cfg) -> None:
    if r.error:                                                    # los errores se muestran como errores, nunca como una respuesta
        st.error(cfg.get("mensajes.error_cuota") if r.error_tipo == "cuota_agotada" else r.error)
        if r.error_tipo == "cuota_agotada":
            st.caption(f"Detalle técnico: {r.error}")
        mostrar_fuentes(r)
        return
    if r.abstuvo:
        st.markdown(":orange-badge[Se abstuvo de responder]")
        st.warning(r.respuesta)
        st.caption(f"Motivo: {MOTIVO.get(r.motivo_abstencion, r.motivo_abstencion)} (mejor similitud {r.mejor_similitud:.3f}; umbral {cfg.get('retrieval.umbral_similitud'):.3f}).")
    else:
        st.markdown(":green-badge[Respondió]")
        st.markdown(r.respuesta)
    if r.advertencias_version:
        unicos = list(dict.fromkeys(r.advertencias_version))       # sin repetidos y en orden
        st.warning("**Aviso de versión**\n\n" + "\n".join(f"- {a}" for a in unicos))
    mostrar_fuentes(r)
    mostrar_costo(r, cfg)


def pestana_consulta(cfg, motor, error_motor) -> None:
    if error_motor:
        st.error(f"No se pudo iniciar el asistente.\n\n{error_motor}")
        st.stop()
    st.caption(" ".join(cfg.get("mensajes.aviso_privacidad").split()))
    ej = ejemplos(cfg)
    if ej:
        st.caption("Ejemplos:")
        cols = st.columns(len(ej))
        for c, texto in zip(cols, ej):
            c.button(texto if len(texto) < 70 else texto[:67] + "…", key=f"ej_{texto[:20]}", help=texto, on_click=lambda t=texto: st.session_state.update(pregunta=t), width="stretch")
    with st.form("consulta"):
        pregunta = st.text_area("Tu pregunta sobre contrataciones públicas", key="pregunta", height=90, placeholder="Ej.: ¿Cuál es el plazo máximo para que la entidad me pague?")
        enviar = st.form_submit_button("Consultar", type="primary")
    if enviar:
        if not pregunta.strip():
            st.warning("Escribe una pregunta.")
        else:
            with st.spinner("Buscando en las normas y generando la respuesta…"):
                st.session_state["ultimo"] = motor.responder(pregunta)
    if "ultimo" in st.session_state:
        mostrar_resultado(st.session_state["ultimo"], cfg)


# ───────────────────────── pestaña Calidad de extracción ─────────────────────────

def pestana_extraccion(cfg) -> None:
    e = datos.extraccion(cfg)
    if not e["documentos"]:
        st.info("Todavía no hay reporte de extracción. Ejecuta: `python scripts/run_extraction.py`.")
        return
    st.caption(f"Reporte de la Fase 2, generado el {e['generado']}. La página de cada fragmento es el índice del PDF (empezando en 1).")
    tabla(e["documentos"])
    for d in e["documentos"]:
        det = e["detalle"][d["documento"]]
        with st.expander(f"{d['documento']} — muestra de una página del medio"):
            m = det.get("muestra_del_medio") or {}
            st.caption(f"Página {m.get('pagina')} · origen {m.get('origen')}")
            st.text_area("Texto", m.get("texto", ""), height=240, disabled=True, label_visibility="collapsed", key=f"muestra_{d['documento']}")
    if e["plan_ocr"]:
        with st.expander("Plan de OCR del Reglamento (páginas OCR-eadas y motivo)"):
            st.json(e["plan_ocr"], expanded=False)
    for nombre, texto in e["notas"].items():
        with st.expander(f"Nota técnica: {nombre}"):
            st.markdown(texto)


# ───────────────────────── pestaña Evaluación ─────────────────────────

def grafico_umbral(filas: list[dict], elegido: float, dominio: tuple[float, float] | None) -> None:
    import altair as alt
    largo = pd.DataFrame([{"umbral": f["umbral"], "caso": nombre, "preguntas": f[clave]} for f in filas for clave, nombre in SERIES_UMBRAL])
    if dominio:
        largo = largo[(largo["umbral"] >= dominio[0]) & (largo["umbral"] <= dominio[1])]
    orden = [n for _, n in SERIES_UMBRAL]
    lineas = alt.Chart(largo).mark_line(interpolate="step-after", strokeWidth=2).encode(
        x=alt.X("umbral:Q", title="Umbral de similitud (coseno)", scale=alt.Scale(zero=False)), y=alt.Y("preguntas:Q", title="Preguntas"),
        color=alt.Color("caso:N", scale=alt.Scale(domain=orden, range=COLORES), legend=alt.Legend(orient="bottom", title=None)), tooltip=["umbral", "caso", "preguntas"])
    regla = alt.Chart(pd.DataFrame({"umbral": [elegido]})).mark_rule(strokeDash=[4, 3], strokeWidth=1.2).encode(x="umbral:Q")
    st.altair_chart(lineas + regla)


def pestana_evaluacion(cfg) -> None:
    ev = datos.evaluacion(cfg)
    if not ev["set_validado"]:
        st.warning("**PROVISIONAL.** Las páginas esperadas del set de evaluación aún no han sido validadas manualmente (Fase 3): todas las métricas de esta pestaña pueden cambiar.")
    rec = ev["recuperacion"]
    st.subheader("Recuperación (sin LLM)")
    if not rec:
        st.info("Sin resultados. Ejecuta: `python -m evaluation.run_eval` (con `PYTHONPATH=src`).")
    else:
        c = st.columns(5)
        for col, k in zip(c, ev["ks"]):
            col.metric(f"Recall@{k}", f"{rec[f'recall@{k}']:.3f}")
        c[3].metric("MRR", f"{rec['mrr']:.3f}")
        c[4].metric("Recall@3 modificatoria", f"{rec['recall@3_modificatoria']:.3f}", help="Preguntas sobre artículos que cambió el DS 001-2026-EF.")
        st.caption("Recall@k: ¿la página esperada está entre los k fragmentos más parecidos? Mide SOLO la recuperación, no la calidad de la respuesta.")
        with st.expander("Por pregunta"):
            tabla(ev["por_pregunta"])
    st.subheader("Abstención y punta a punta (con el LLM real)")
    ab = ev["abstencion_recuperacion"]
    if ab:
        st.caption(f"Solo con la compuerta del umbral ({ab['umbral']:.3f}): abstenciones correctas {ab['abstenciones_correctas']}/{ab['out_of_domain']} fuera de dominio; "
                   f"abstenciones incorrectas {ab['abstenciones_incorrectas']}/{ab['in_domain']} del dominio.")
    s = ev["e2e_resumen"]
    if not s:
        st.info("Sin evaluación de punta a punta. Ejecuta: `python -m evaluation.eval_end_to_end` (usa la cuota gratuita del proveedor).")
    else:
        st.caption(f"Evaluación con {ev['e2e_etiqueta']}: cada pregunta pasa por el motor completo.")
        c = st.columns(4)
        c[0].metric("Del dominio respondidas", f"{s['in_domain_respondidas']}/{s['in_domain']}")
        c[1].metric("…con cita correcta", f"{s['in_domain_con_cita_correcta']}/{s['in_domain']}")
        c[2].metric("Ajenas rechazadas", f"{s['fuera_abstenciones']}/{s['fuera_de_dominio']}", help=f"{s['fuera_abstenciones_por_llm']} las rechazó el propio LLM (contexto_suficiente=false).")
        c[3].metric("Respuestas indebidas", f"{s['fuera_respondidas']}", help="Pregunta ajena al corpus que el sistema respondió.")
        with st.expander("Detalle por pregunta"):
            tabla([{k: v for k, v in f.items() if k in ("id", "tipo", "desenlace", "cita_correcta", "mejor_similitud", "costo_usd_referencia", "latencia_ms", "respuesta")} for f in ev["e2e"]])
    st.subheader("Barrido del umbral de similitud")
    if ev["barrido_e2e"]:
        sims = [f["mejor_similitud"] for f in ev["e2e"] if f.get("desenlace") == "respondida" and isinstance(f.get("mejor_similitud"), float)]
        dominio = (max(0.0, min(sims) - 0.05), min(1.0, max(sims) + 0.03)) if sims else None
        grafico_umbral(ev["barrido_e2e"], ev["umbral"], dominio)
        st.caption(f"Línea punteada: umbral configurado ({ev['umbral']:.3f}). Calibrado con el LLM real; la tabla completa (0 a 1) está en `eval/results/umbral_e2e_barrido.csv`.")
        if ev["umbral_e2e_md"]:
            with st.expander("Cómo se eligió el umbral"):
                st.markdown(ev["umbral_e2e_md"])
    else:
        st.info("Sin barrido. Ejecuta `python -m evaluation.sweep_threshold_e2e`.")
    if ev["barrido_recuperacion"]:
        with st.expander("Barrido solo con recuperación (primera versión, sin LLM)"):
            grafico_umbral(ev["barrido_recuperacion"], 0.865, (0.78, 0.96))
    st.subheader("Embeddings: local frente a API")
    if ev["embeddings"]:
        tabla([{k: v for k, v in f.items() if k in ("tipo", "modelo", "estado", "nivel", "dim", "indexacion_s", "costo_usd", "consulta_ms_media", "recall@1", "recall@3", "recall@5")}
               for f in ev["embeddings"]])
        if ev["embeddings_md"]:
            with st.expander("Detalle y costos"):
                st.markdown(ev["embeddings_md"])
    else:
        st.info("Sin comparación. Ejecuta `python -m evaluation.compare_embeddings`.")
    st.subheader("Troceado (chunking)")
    if ev["chunking"]:
        tabla(ev["chunking"])
    st.subheader("BM25 frente a semántica")
    if ev["retrievers"]:
        tabla(ev["retrievers"])
        if ev["sonda_articulos"]:
            st.caption("Sonda sintética de búsqueda por número de artículo («artículo N de la Ley»); no forma parte del set de evaluación.")
            tabla(ev["sonda_articulos"])
    else:
        st.info("Pendiente (Fase 8): la comparación BM25 / semántica / híbrida aún no se ha ejecutado.")


# ───────────────────────── pestaña Costos ─────────────────────────

def pestana_costos(cfg) -> None:
    c = datos.costos(cfg)
    if not c["hay_datos"]:
        st.info("Todavía no hay llamadas registradas en `logs/llm_calls.jsonl`.")
        return
    r = c["resumen"]
    st.caption("Agregado de `logs/llm_calls.jsonl`: solo llamadas reales al proveedor (las respuestas reutilizadas de la caché de evaluación no cuentan).")
    k = st.columns(5)
    k[0].metric("Llamadas", r["llamadas"], help=f"{r['exitosas']} exitosas, {r['fallidas']} fallidas, {r['reintentos']} reintentos.")
    k[1].metric("Tokens entrada / salida", f"{r['tokens_in']:,} / {r['tokens_out']:,}")
    k[2].metric("Costo real (USD)", f"{r['costo_real_total_usd']:.4f}")
    k[3].metric("Costo de referencia (USD)", f"{r['costo_referencia_total_usd']:.4f}", help="Precio de pago del modelo aplicado a los mismos tokens.")
    k[4].metric("Latencia mediana / p90", f"{(r['latencia_mediana_ms'] or 0) / 1000:.2f} s / {(c['latencia_p90_ms'] or 0) / 1000:.2f} s")
    if c["aviso_nivel_gratuito"]:
        st.info("Se usa la **capa gratuita**: el costo real es 0. El costo de referencia sirve para dimensionar el gasto si algún día se pasara a un plan de pago.")
    if c["proyeccion_referencia_1000_usd"] is not None:
        st.metric("Proyección de referencia: 1000 consultas (USD)", f"{c['proyeccion_referencia_1000_usd']:.2f}",
                  help=f"Costo de referencia medio por consulta exitosa × 1000, con {c['muestra_proyeccion']} llamadas de muestra: es una proyección, no una medición.")
    st.markdown("**Por modelo**")
    tabla(c["por_modelo"])
    if c["por_dia"]:
        st.markdown("**Llamadas por día**")
        st.bar_chart(pd.DataFrame(c["por_dia"]).set_index("día"))
    if c["errores"]:
        st.markdown("**Llamadas fallidas por tipo**")
        st.write(c["errores"])
    with st.expander("Últimas 20 llamadas"):
        tabla(c["ultimas"])
    fb = datos.feedback(cfg)
    if fb["filas"]:
        st.markdown("**Feedback del bot de Telegram (👍/👎)**")
        st.caption("Generado por `python -m evaluation.feedback_summary`; los IDs de usuario de Telegram no se muestran (dato personal).")
        tabla(fb["filas"])


# ───────────────────────── página ─────────────────────────

def main() -> None:
    try:
        cfg = cargar_cfg()
    except ConfigError as exc:
        st.error(f"Configuración inválida o incompleta.\n\n{exc}")
        st.stop()
    motor, error_motor = None, None
    try:
        motor = cargar_motor()
    except ERRORES_DE_ARRANQUE as exc:
        error_motor = str(exc)
    with st.sidebar:
        st.title("⚖️ Contrataciones públicas")
        st.caption("Ley 32069 · Reglamento DS 009-2025-EF (subconjunto OCR) · Modificatoria DS 001-2026-EF")
        aj = cfg.get("llm.proveedores." + cfg.get("llm.provider"))
        st.markdown(f"**Modelo:** `{cfg.get('llm.provider')}/{aj['modelo']}` ({cfg.get('llm.nivel')})  \n**Búsqueda:** {cfg.get('retrieval.busqueda')}, top-{cfg.get('retrieval.top_k')}  \n"
                    f"**Umbral de similitud:** {cfg.get('retrieval.umbral_similitud'):.3f}")
        st.info(" ".join(cfg.get("mensajes.aviso_privacidad").split()))
        st.caption("Información normativa, no asesoría legal vinculante.")
    t1, t2, t3, t4 = st.tabs(["Consulta", "Calidad de extracción", "Evaluación", "Costos"])
    with t1:
        pestana_consulta(cfg, motor, error_motor)
    with t2:
        pestana_extraccion(cfg)
    with t3:
        pestana_evaluacion(cfg)
    with t4:
        pestana_costos(cfg)


main()

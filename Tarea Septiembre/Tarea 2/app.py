"""app.py — dashboard Streamlit de "Radar de contrataciones públicas" (Tarea 2, Fase 4).

Ejecutar (desde "Tarea Septiembre/Tarea 2/", con el entorno virtual activo):  streamlit run app.py

Esta interfaz SOLO lee archivos ya generados por las fases offline (parquet validado, reportes JSON/MD, el
índice ChromaDB) y llama a ``radar_engine.engine.consultar(pregunta, filtros)`` para la pestaña de preguntas.
NUNCA descarga datos de OECE ni reconstruye el índice: si falta, muestra el comando para construirlo
(``python src/build_index_radar.py``). Toda la lógica del RAG híbrido vive en ``src/radar_engine``, que no
importa Streamlit (verificable con ``grep -rn streamlit src/radar_engine`` — no debe encontrar nada).

Pestañas: Panorama · Consulta (RAG) · Riesgo (postor único) · Calidad de datos.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from radar_engine.config import Config, ConfigError, cargar_config  # noqa: E402
from radar_engine.embeddings import ErrorEmbeddings  # noqa: E402
from radar_engine.engine import MotorRadar  # noqa: E402
from radar_engine.filtros import Filtros  # noqa: E402
from radar_engine.llm import ErrorPrecio  # noqa: E402
from radar_engine.store import IndiceNoDisponible  # noqa: E402

ERRORES_DE_ARRANQUE = (IndiceNoDisponible, ConfigError, ErrorEmbeddings, ErrorPrecio, FileNotFoundError)
CATEGORIA_ES = {"goods": "Bienes", "services": "Servicios", "works": "Obras"}
CATEGORIA_EN = {v: k for k, v in CATEGORIA_ES.items()}
MOTIVO_ABST = {"sin_candidatos": "ningún proceso cumple los filtros indicados", "umbral": "la mejor similitud quedó por debajo del umbral",
              "llm_sin_contexto": "el modelo declaró que el contexto recuperado no alcanza"}

st.set_page_config(page_title="Radar de contrataciones públicas", page_icon="📡", layout="wide")


# ───────────────────────── carga de datos (cacheada; nunca se recalcula en cada interacción) ─────────────────────────

@st.cache_resource(show_spinner=False)
def cargar_cfg() -> Config:
    return cargar_config()


@st.cache_data(show_spinner="Cargando procesos de contratación…")
def cargar_datos(_cfg: Config) -> pd.DataFrame:
    df = pd.read_parquet(_cfg.base / _cfg.get("validation.output_file"))
    df["fecha_convocatoria_dt"] = pd.to_datetime(df["fecha_convocatoria"], errors="coerce", utc=True).dt.tz_localize(None)
    df["categoria_es"] = df["categoria"].map(CATEGORIA_ES).fillna(df["categoria"])
    df["postor_unico"] = (df["n_adjudicaciones"] > 0) & df["n_postores_unicos"].eq(1)
    return df


@st.cache_data(show_spinner=False)
def cargar_geojson(_cfg: Config) -> dict:
    return json.loads((_cfg.base / _cfg.get("territory.geojson_file")).read_text(encoding="utf-8"))


def _leer_json(ruta: Path) -> dict | None:
    return json.loads(ruta.read_text(encoding="utf-8")) if ruta.is_file() else None


def _leer_texto(ruta: Path) -> str | None:
    return ruta.read_text(encoding="utf-8") if ruta.is_file() else None


@st.cache_resource(show_spinner="Cargando el índice y el modelo de embeddings…")
def cargar_motor(_cfg: Config) -> MotorRadar:
    """UNA sola vez por proceso. Solo LEE el índice ya construido (si falta, lanza IndiceNoDisponible con instrucciones)."""
    return MotorRadar.desde_config(_cfg)


def tabla(df: pd.DataFrame, **kw) -> None:
    st.dataframe(df, hide_index=True, width="stretch", **kw)


# ───────────────────────── filtros de la barra lateral ─────────────────────────

def filtros_sidebar(df: pd.DataFrame, cfg: Config) -> tuple[pd.DataFrame, Filtros, float]:
    st.sidebar.title("📡 Radar de contrataciones")
    st.sidebar.caption("SEACE V3.0 (OCDS) · jun-ago 2026 · 25 departamentos")
    st.sidebar.subheader("Filtros")

    deptos_todos = sorted(df["departamento"].unique())
    deptos = st.sidebar.multiselect("Departamento", deptos_todos, default=[], help="Vacío = todos los departamentos.")

    categorias = st.sidebar.multiselect("Categoría", list(CATEGORIA_ES.values()), default=[], help="Vacío = todas las categorías.")

    monto_max_dato = float(df["monto_referencial_pen"].max(skipna=True) or 0)
    c1, c2 = st.sidebar.columns(2)
    monto_min = c1.number_input("Monto mín. (S/)", min_value=0.0, value=0.0, step=10_000.0, format="%.0f")
    monto_max = c2.number_input("Monto máx. (S/)", min_value=0.0, value=float(monto_max_dato), step=10_000.0, format="%.0f")

    fecha_min_dato, fecha_max_dato = df["fecha_convocatoria_dt"].min(), df["fecha_convocatoria_dt"].max()
    rango_fecha = st.sidebar.date_input("Fecha de convocatoria", value=(fecha_min_dato.date(), fecha_max_dato.date()),
                                        min_value=fecha_min_dato.date(), max_value=fecha_max_dato.date())

    umbral = st.sidebar.slider("Umbral de similitud (pestaña Consulta)", 0.0, 1.0, float(cfg.get("retrieval.umbral_similitud")), 0.01,
                               help="Por debajo de este coseno, el asistente se abstiene sin llamar al modelo generativo.")

    filtrado = df
    if deptos:
        filtrado = filtrado[filtrado["departamento"].isin(deptos)]
    if categorias:
        filtrado = filtrado[filtrado["categoria_es"].isin(categorias)]
    if monto_min > 0 or monto_max < monto_max_dato - 1.0:      # -1.0: tolerancia; el widget puede devolver el máximo con un redondeo de punto flotante distinto al de pandas
        # un monto reservado/no publicado (NaN) nunca "pasa" un filtro de monto: no se adivina (mismo criterio que radar_engine/store.py)
        filtrado = filtrado[filtrado["monto_referencial_pen"].between(monto_min, monto_max)]
    if isinstance(rango_fecha, tuple) and len(rango_fecha) == 2:
        # date_input devuelve fechas sin hora: "hasta" debe cubrir el día ENTERO (hasta 23:59:59), si no,
        # un proceso convocado esa misma fecha pero después de medianoche quedaría excluido por defecto.
        desde, hasta = pd.Timestamp(rango_fecha[0]), pd.Timestamp(rango_fecha[1]) + pd.Timedelta(hours=23, minutes=59, seconds=59)
        filtrado = filtrado[filtrado["fecha_convocatoria_dt"].between(desde, hasta) | filtrado["fecha_convocatoria_dt"].isna()]

    categoria_unica = CATEGORIA_EN.get(categorias[0]) if len(categorias) == 1 else None
    filtros_explicitos = Filtros(departamento=deptos[0] if len(deptos) == 1 else None, categoria=categoria_unica,
                                 monto_min=monto_min if monto_min > 0 else None, monto_max=monto_max if monto_max < monto_max_dato else None)
    return filtrado, filtros_explicitos, umbral


# ───────────────────────── Panorama: KPI + mapa + tabla + distribución ─────────────────────────

def render_kpis(df: pd.DataFrame) -> None:
    c = st.columns(4)
    c[0].metric("Procesos", f"{len(df):,}")
    monto_total = df["monto_referencial_pen"].sum(skipna=True)
    c[1].metric("Monto referencial total (S/)", f"{monto_total:,.0f}")
    c[2].metric("Departamentos representados", df["departamento"].nunique())
    adjudicados = df[df["n_adjudicaciones"] > 0]
    share = 100 * adjudicados["postor_unico"].mean() if len(adjudicados) else None
    c[3].metric("Adjudicaciones con un solo postor", f"{share:.1f}%" if share is not None else "—",
               help="Entre los procesos adjudicados de la selección actual. Es una señal para revisar, no evidencia de irregularidad (ver pestaña Riesgo).")


def render_mapa(df: pd.DataFrame, geojson: dict, cfg: Config) -> None:
    st.subheader("Mapa por departamento")
    if df.empty:
        st.info("No hay procesos para los filtros actuales.")
        return
    metrica = st.radio("Colorear por", ["Número de procesos", "Monto referencial total (S/)"], horizontal=True, key="metrica_mapa")
    agg = df.groupby("departamento").agg(procesos=("ocid", "size"), monto=("monto_referencial_pen", "sum")).reset_index()
    valor_col, titulo = ("procesos", "Procesos") if metrica == "Número de procesos" else ("monto", "Monto referencial (S/)")
    fig = px.choropleth(agg, geojson=geojson, locations="departamento", featureidkey=f"properties.{cfg.get('territory.geojson_key')}",
                        color=valor_col, color_continuous_scale="Blues", labels={valor_col: titulo},
                        hover_data={"departamento": True, "procesos": True, "monto": ":,.0f"})
    fig.update_geos(fitbounds="locations", visible=False)
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=450)
    st.plotly_chart(fig, width="stretch")


def render_tabla(df: pd.DataFrame) -> None:
    st.subheader(f"Procesos ({len(df):,})")
    if df.empty:
        st.info("No hay procesos para los filtros actuales.")
        return
    columnas = ["ocid", "nomenclatura", "descripcion", "departamento", "categoria_es", "comprador_nombre", "monto_referencial_pen",
               "fecha_convocatoria", "n_postores_unicos", "n_adjudicaciones"]
    vista = df[columnas].rename(columns={"categoria_es": "categoria", "monto_referencial_pen": "monto_pen"}).sort_values("monto_pen", ascending=False, na_position="last")
    tabla(vista, height=350)
    st.download_button("Descargar CSV (selección actual)", vista.to_csv(index=False).encode("utf-8"), "procesos_filtrados.csv", "text/csv")


def render_distribucion(df: pd.DataFrame) -> None:
    st.subheader("Distribución")
    if df.empty:
        st.info("No hay procesos para los filtros actuales.")
        return
    col1, col2 = st.columns(2)
    with col1:
        por_cat = df.groupby("categoria_es").agg(procesos=("ocid", "size"), monto=("monto_referencial_pen", "sum")).reset_index()
        st.plotly_chart(px.bar(por_cat, x="categoria_es", y="procesos", labels={"categoria_es": "Categoría", "procesos": "Procesos"}, title="Procesos por categoría"),
                        width="stretch")
    with col2:
        por_mes = df.dropna(subset=["fecha_convocatoria_dt"]).assign(mes=lambda d: d["fecha_convocatoria_dt"].dt.to_period("M").astype(str))
        por_mes = por_mes.groupby("mes").size().reset_index(name="procesos")
        st.plotly_chart(px.bar(por_mes, x="mes", y="procesos", title="Procesos por mes de convocatoria"), width="stretch")
    top_deptos = df.groupby("departamento")["monto_referencial_pen"].sum().sort_values(ascending=False).head(10).reset_index()
    st.plotly_chart(px.bar(top_deptos, x="departamento", y="monto_referencial_pen", title="Top 10 departamentos por monto referencial (S/)"), width="stretch")


def pestana_panorama(df: pd.DataFrame, geojson: dict, cfg: Config) -> None:
    render_kpis(df)
    render_mapa(df, geojson, cfg)
    render_distribucion(df)
    render_tabla(df)


# ───────────────────────── Consulta (RAG híbrido) ─────────────────────────

def mostrar_procesos_recuperados(r) -> None:
    if not r.procesos:
        return
    citados = [p for p in r.procesos if p.citado]
    grupos = [("Procesos citados por el modelo", citados), ("Otros procesos recuperados (no citados)", [p for p in r.procesos if not p.citado])] \
        if citados else [("Procesos más parecidos a la pregunta", r.procesos)]
    for titulo, lista in grupos:
        if not lista:
            continue
        st.markdown(f"**{titulo}**")
        for p in lista:
            monto = f"S/ {p.monto_pen:,.0f}" if p.monto_pen is not None else "reservado/no publicado"
            with st.expander(f"{p.ocid} · {p.departamento} · {monto} · similitud {p.similitud:.3f}"):
                st.caption(f"Comprador: {p.comprador or '—'} · Categoría: {CATEGORIA_ES.get(p.categoria, p.categoria)} · Fecha: {p.fecha or '—'}")
                st.text_area("Descripción", p.texto, height=140, disabled=True, label_visibility="collapsed", key=f"proc_{titulo}_{p.ocid}")


def mostrar_costo(r) -> None:
    st.markdown("**Costo y latencia de la consulta**")
    if not r.modelo:
        st.info("No hubo llamada al modelo (se decidió antes: filtros sin candidatos o compuerta del umbral): costo USD 0.")
        return
    c = st.columns(6)
    c[0].metric("Tokens entrada", f"{r.tokens_entrada:,}")
    c[1].metric("Tokens salida", f"{r.tokens_salida:,}")
    c[2].metric("Costo real (USD)", f"{r.costo_usd_real:.6f}")
    c[3].metric("Costo de referencia (USD)", f"{r.costo_usd_referencia:.6f}", help="Lo que costaría con el precio de pago del modelo.")
    c[4].metric("Latencia total", f"{r.latencia_ms / 1000:.2f} s")
    c[5].metric("Modelo", r.modelo or "—", help=f"Proveedor: {r.proveedor or '—'}")


def pestana_consulta(cfg: Config, motor: MotorRadar | None, error_motor: str | None, filtros_sidebar_actuales: Filtros, umbral: float) -> None:
    if error_motor:
        st.error(f"No se pudo iniciar el asistente.\n\n{error_motor}")
        return
    st.caption("Combina tus filtros de la barra lateral con lo que se entienda de la pregunta (departamento, categoría, monto). "
              "Los montos y territorios se aplican como filtro EXACTO; solo el resto de la pregunta se compara por similitud semántica.")
    pregunta = st.text_area("Tu pregunta sobre qué está comprando el Estado", height=90,
                            placeholder="Ej.: obras de agua y saneamiento en Cusco por encima de un millón de soles")
    enviar = st.button("Consultar", type="primary")
    if enviar:
        if not pregunta.strip():
            st.warning("Escribe una pregunta.")
        else:
            with st.spinner("Buscando procesos y generando la respuesta…"):
                r = motor.consultar(pregunta, filtros_sidebar_actuales, umbral_similitud=umbral)
            st.session_state["ultimo_radar"] = r
    if "ultimo_radar" in st.session_state:
        r = st.session_state["ultimo_radar"]
        st.caption(f"Filtros aplicados: {Filtros(**r.filtros_aplicados).como_texto()}")
        if r.error:
            st.error(r.error)
        elif r.abstuvo:
            st.markdown(":orange-badge[Se abstuvo de responder]")
            st.warning(r.respuesta)
            st.caption(f"Motivo: {MOTIVO_ABST.get(r.motivo_abstencion, r.motivo_abstencion)} (mejor similitud {r.mejor_similitud:.3f}; umbral {umbral:.3f}).")
        else:
            st.markdown(":green-badge[Respondió]")
            st.markdown(r.respuesta)
        mostrar_procesos_recuperados(r)
        mostrar_costo(r)


# ───────────────────────── Riesgo (Fase 5) ─────────────────────────

def pestana_riesgo(cfg: Config) -> None:
    datos = _leer_json(cfg.ruta("riesgo_json"))
    if not datos:
        st.info("Todavía no hay reporte de riesgo. Ejecuta: `python src/risk_indicator.py`.")
        return
    st.warning(datos["aviso"])
    c = st.columns(3)
    c[0].metric("Procesos adjudicados", f"{datos['procesos_adjudicados']:,}")
    c[1].metric("Con un solo postor", f"{datos['con_un_solo_postor']:,}")
    c[2].metric("Proporción global", f"{100*(datos['share_global'] or 0):.1f}%")
    st.subheader("Por departamento")
    tabla(pd.DataFrame(datos["por_departamento"]))
    st.subheader(f"Top {datos['top_n']} compradores (mínimo {datos['min_procesos_adjudicados_para_ranking']} procesos adjudicados)")
    st.caption(f"De {datos['compradores_totales']:,} compradores, {datos['compradores_con_muestra_suficiente']:,} tienen muestra suficiente. "
              "Los compradores son entidades públicas, nunca personas naturales.")
    tabla(pd.DataFrame(datos["top_compradores"]))


# ───────────────────────── Calidad de datos (Fase 2 + evaluación Fase 3) ─────────────────────────

def pestana_calidad(cfg: Config) -> None:
    st.subheader("Calidad de datos (Fase 2)")
    md = _leer_texto(cfg.ruta("outputs") / "reporte_calidad.md")
    if md:
        with st.expander("Ver reporte completo", expanded=False):
            st.markdown(md)
        rep = _leer_json(cfg.ruta("outputs") / "reporte_calidad.json")
        if rep:
            st.caption(f"Generado: {rep['generado']} · Procesos: {rep['procesos']:,} · Sin ninguna marca: {rep['procesos_sin_ninguna_marca']:,}")
            tabla(pd.DataFrame(rep["reglas"])[["id", "regla", "marcados", "total", "porcentaje"]])
    else:
        st.info("Todavía no hay reporte de calidad. Ejecuta: `python src/validation.py`.")

    st.subheader("Evaluación de recuperación (Fase 3, sin LLM)")
    ev = _leer_json(cfg.ruta("eval_radar_resultados"))
    if ev:
        st.caption(f"Umbral usado al generar este reporte: {ev['generado_con_umbral']:.3f}")
        c = st.columns(len(ev["ks"]) + 1)
        for col, k in zip(c, ev["ks"]):
            col.metric(f"Recall@{k}", f"{ev['resumen'][f'recall@{k}']:.3f}")
        c[-1].metric("MRR", f"{ev['resumen']['mrr']:.3f}")
        ab = ev["abstencion"]
        st.caption(f"Abstención con ese umbral: correctas {ab['abstenciones_correctas']}/{ab['out_of_domain']} (fuera de dominio) · "
                  f"incorrectas {ab['abstenciones_incorrectas']}/{ab['in_domain']} (dentro de dominio) · indebidas {ab['indebidas']}.")
        with st.expander("Por pregunta"):
            # "recuperados" es una lista de tuplas (ocid, similitud) por pregunta: Arrow no la serializa
            # como columna de un DataFrame, así que se muestra aparte (no se pierde información).
            filas = [{k: v for k, v in r.items() if k != "recuperados"} for r in ev["por_pregunta"]]
            tabla(pd.DataFrame(filas))
            st.caption("Los procesos recuperados por pregunta (ocid y similitud) están en el JSON: `data/outputs/eval_radar_resultados.json`.")
    else:
        st.info("Todavía no hay evaluación. Ejecuta: `python -m evaluation.run_eval_radar`.")

    barrido = cfg.ruta("umbral_barrido")
    if barrido.is_file():
        with st.expander("Barrido del umbral de similitud (¿transfiere el de la Tarea 1?)"):
            st.line_chart(pd.read_csv(barrido).set_index("umbral")[["respondidas_correctas", "abstenciones_incorrectas", "abstenciones_correctas", "indebidas"]])
            st.caption("Ejecutado con `python -m evaluation.sweep_threshold_radar`. Detalle y justificación del umbral elegido en el README.")


# ───────────────────────── página ─────────────────────────

def main() -> None:
    try:
        cfg = cargar_cfg()
    except ConfigError as exc:
        st.error(f"Configuración inválida o incompleta.\n\n{exc}")
        st.stop()

    try:
        df = cargar_datos(cfg)
        geojson = cargar_geojson(cfg)
    except FileNotFoundError as exc:
        st.error(f"Faltan datos procesados: {exc}\n\nEjecuta primero las Fases 1-2 (`src/acquisition_bulk.py`, `src/normalize_records.py`, `src/validation.py`).")
        st.stop()

    motor, error_motor = None, None
    try:
        motor = cargar_motor(cfg)
    except ERRORES_DE_ARRANQUE as exc:
        error_motor = str(exc)

    df_filtrado, filtros_explicitos, umbral = filtros_sidebar(df, cfg)
    st.sidebar.caption("El mapa, la tabla, la distribución y el indicador de postor único se actualizan con estos filtros. "
                      "La pestaña Consulta además entiende departamento/categoría/monto escritos en la propia pregunta.")

    t1, t2, t3, t4 = st.tabs(["Panorama", "Consulta (RAG)", "Riesgo (postor único)", "Calidad de datos"])
    with t1:
        pestana_panorama(df_filtrado, geojson, cfg)
    with t2:
        pestana_consulta(cfg, motor, error_motor, filtros_explicitos, umbral)
    with t3:
        pestana_riesgo(cfg)
    with t4:
        pestana_calidad(cfg)


main()

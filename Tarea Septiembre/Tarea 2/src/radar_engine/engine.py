"""Motor RAG híbrido: UNA función, ``consultar(pregunta, filtros)``, que devuelve un ``ResultadoRadar``
estructurado. Toda interfaz (``app.py``, o cualquier otra) solo llama a esa función; este módulo no importa
Streamlit ni ninguna librería de interfaz (verificable con ``grep -rn "^import streamlit\|^from streamlit" src/radar_engine/*.py``, que no
debe encontrar nada — ver README).

Orden de las decisiones (importa, mismo patrón que la Tarea 1: ``rag_engine.engine``):
  1. Filtros: se combinan los EXPLÍCITOS (sidebar) con los que se extraen de la pregunta en lenguaje natural
     (``filtros.py``). Si hay filtros y NINGÚN proceso los cumple, se abstiene sin tocar embeddings ni LLM.
  2. Recuperación: coseno exacto contra los procesos que pasan los filtros (``store.py``).
  3. COMPUERTA DEL UMBRAL, antes de cualquier llamada al LLM: si la mejor similitud es menor que
     ``retrieval.umbral_similitud``, se abstiene con costo 0.
  4. Generación con el LLM (salida estructurada). Si el modelo declara ``contexto_suficiente = false`` ->
     abstención con motivo ``llm_sin_contexto``. La abstención es un CAMPO (``abstuvo``), nunca se deduce
     leyendo el texto de la respuesta.
  5. Todo error (índice, red, clave, cuota agotada, formato) se devuelve en ``error``/``error_tipo``, con
     ``respuesta = None``: jamás como una respuesta normal.
El motor nunca lee ``procesos_validados.parquet``: solo el índice ya construido (``build_index_radar.py``) y
la configuración. Cada llamada al LLM queda en ``logs/llm_calls_radar.jsonl``.
"""
from __future__ import annotations

import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from radar_engine.config import Config, ConfigError, cargar_config
from radar_engine.embeddings import Embedder, ErrorEmbeddings, crear_embedder
from radar_engine.filtros import Filtros, combinar, extraer_filtros_pregunta
from radar_engine.llm import (ClienteLLM, ErrorLLM, ErrorPrecio, RespuestaLLM, ajustes_llm, cargar_tabla_precios,
                              crear_cliente_llm, registrar_llamada)
from radar_engine.llm_schema import EsquemaSalidaOCID, esquema_salida, etiqueta_proceso
from radar_engine.store import IndiceNoDisponible, Recuperado, abrir_para_lectura, buscar, candidatos

MOTIVO_SIN_CANDIDATOS = "sin_candidatos"
MOTIVO_UMBRAL = "umbral"
MOTIVO_LLM = "llm_sin_contexto"


@dataclass
class ProcesoCitado:
    ocid: str
    similitud: float
    comprador: str
    departamento: str
    categoria: str
    monto_pen: float | None       # None si es reservado/no publicado (nunca 0 disfrazando "desconocido")
    fecha: str
    nomenclatura: str
    texto: str
    citado: bool = False          # el modelo lo citó en su respuesta


@dataclass
class ResultadoRadar:
    respuesta: str | None
    procesos: list[ProcesoCitado] = field(default_factory=list)
    abstuvo: bool = False
    motivo_abstencion: str | None = None       # "sin_candidatos" | "umbral" | "llm_sin_contexto" | None
    mejor_similitud: float = 0.0
    filtros_aplicados: dict = field(default_factory=dict)
    tokens_entrada: int = 0
    tokens_salida: int = 0
    costo_usd_real: float = 0.0
    costo_usd_referencia: float = 0.0
    latencia_ms: float = 0.0
    modelo: str | None = None
    proveedor: str | None = None
    error: str | None = None
    error_tipo: str | None = None
    desde_cache: bool = False
    timestamp: str = ""

    def como_dict(self) -> dict:
        return asdict(self)


def _norm(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn").strip()


def _ahora() -> datetime:
    return datetime.now().astimezone()


class MotorRadar:
    def __init__(self, cfg: Config, embedder: Embedder, coleccion, tabla_precios, cliente_llm: ClienteLLM | None = None,
                 ruta_log: Path | None = None, reloj=_ahora):
        self.cfg, self.embedder, self.coleccion, self.tabla = cfg, embedder, coleccion, tabla_precios
        self._cliente_llm = cliente_llm
        self.ruta_log = ruta_log or cfg.ruta("llm_calls_log")
        self.reloj = reloj
        self._esquema: EsquemaSalidaOCID = esquema_salida(cfg)
        self.ajustes_llm = ajustes_llm(cfg)
        self.proveedor, self.nivel = self.ajustes_llm["provider"], self.ajustes_llm["nivel"]

    @classmethod
    def desde_config(cls, cfg: Config | None = None) -> "MotorRadar":
        cfg = cfg or cargar_config()
        return cls(cfg, crear_embedder(cfg), abrir_para_lectura(cfg), cargar_tabla_precios(cfg))

    def _llm(self) -> ClienteLLM:
        if self._cliente_llm is None:
            self._cliente_llm = crear_cliente_llm(self.cfg)
        return self._cliente_llm

    def usar_cliente_llm(self, cliente: ClienteLLM) -> None:
        """Sustituye el cliente de LLM (p. ej. por uno con caché para la evaluación). El motor no cambia en nada más."""
        self._cliente_llm = cliente

    def _proceso(self, r: Recuperado) -> ProcesoCitado:
        m = r.metadatos
        return ProcesoCitado(ocid=r.ocid, similitud=round(r.similitud, 4), comprador=m.get("comprador", ""),
                             departamento=m.get("departamento", ""), categoria=m.get("categoria", ""),
                             monto_pen=m["monto_pen"] if m.get("monto_conocido") else None, fecha=m.get("fecha", ""),
                             nomenclatura=m.get("nomenclatura", ""), texto=r.texto)

    def _prompt_usuario(self, pregunta: str, procesos: list[ProcesoCitado], filtros: Filtros) -> str:
        contexto = "\n\n".join(f"{etiqueta_proceso(self.cfg, asdict(p))}\n{p.texto}" for p in procesos)
        return self.cfg.get("prompts.usuario").format(contexto=contexto, filtros=filtros.como_texto(), pregunta=pregunta)

    def _marcar_citados(self, procesos: list[ProcesoCitado], citas: list[dict]) -> None:
        citados = {str(c.get("ocid", "")).strip() for c in citas if isinstance(c, dict)}
        for p in procesos:
            p.citado = p.ocid in citados

    def _resultado_error(self, mensaje: str, t0: float, ts: str, filtros: Filtros, procesos: list[ProcesoCitado] | None = None,
                         mejor: float = 0.0, modelo: str | None = None, tipo: str | None = None) -> ResultadoRadar:
        return ResultadoRadar(respuesta=None, procesos=procesos or [], mejor_similitud=mejor, filtros_aplicados=asdict(filtros),
                              latencia_ms=round((time.perf_counter() - t0) * 1000, 1), modelo=modelo,
                              proveedor=self.proveedor if modelo else None, error=mensaje, error_tipo=tipo, timestamp=ts)

    def consultar(self, pregunta: str, filtros: Filtros | None = None, umbral_similitud: float | None = None) -> ResultadoRadar:
        """``umbral_similitud`` sobrescribe (solo para esta llamada) ``retrieval.umbral_similitud`` de config.yaml: lo usa
        la interfaz cuando expone el umbral como control (ver app.py, slider de la barra lateral). No muta ``self.cfg``:
        cada llamada es independiente, incluso con varias sesiones de Streamlit compartiendo el mismo motor cacheado."""
        t0, ts = time.perf_counter(), self.reloj().isoformat(timespec="seconds")
        filtros = filtros or Filtros()
        umbral = umbral_similitud if umbral_similitud is not None else self.cfg.get("retrieval.umbral_similitud")
        if not pregunta or not pregunta.strip():
            return self._resultado_error("La pregunta está vacía.", t0, ts, filtros, tipo="pregunta_vacia")

        combinados = combinar(filtros, extraer_filtros_pregunta(pregunta, self.cfg))

        # 1. filtros: si hay alguno y ningún proceso los cumple, abstención sin tocar embeddings ni LLM
        if not combinados.esta_vacio() and candidatos(self.coleccion, combinados) == 0:
            return ResultadoRadar(respuesta=" ".join(self.cfg.get("mensajes.abstencion_sin_candidatos").split()), abstuvo=True,
                                  motivo_abstencion=MOTIVO_SIN_CANDIDATOS, filtros_aplicados=asdict(combinados),
                                  latencia_ms=round((time.perf_counter() - t0) * 1000, 1), timestamp=ts)

        # 2. recuperación
        try:
            recuperados = buscar(self.coleccion, self.embedder, pregunta, self.cfg.get("retrieval.top_k"), combinados)
        except Exception as exc:
            return self._resultado_error(f"No se pudo consultar el índice: {exc}", t0, ts, combinados, tipo="indice")
        mejor = max((r.similitud for r in recuperados), default=0.0)
        procesos = [self._proceso(r) for r in recuperados]

        # 3. compuerta del umbral: ANTES de llamar al LLM
        if not recuperados or mejor < umbral:
            return ResultadoRadar(respuesta=" ".join(self.cfg.get("mensajes.abstencion").split()), procesos=procesos, abstuvo=True,
                                  motivo_abstencion=MOTIVO_UMBRAL, mejor_similitud=round(mejor, 4), filtros_aplicados=asdict(combinados),
                                  latencia_ms=round((time.perf_counter() - t0) * 1000, 1), timestamp=ts)

        # 4. generación
        modelo = self.ajustes_llm["modelo"]
        try:
            llm = self._llm()
            r: RespuestaLLM = llm.generar(self.cfg.get("prompts.sistema"), self._prompt_usuario(pregunta, procesos, combinados), self._esquema)
        except ErrorLLM as exc:
            if exc.solicitud_enviada:
                registrar_llamada(self.ruta_log, timestamp=ts, proveedor=self.proveedor, modelo=modelo, nivel=self.nivel, tokens_in=0, tokens_out=0,
                                  latencia_ms=0.0, costo_usd_real=0.0, costo_usd_referencia=0.0, intentos=exc.intentos, exito=False,
                                  error=f"{exc.tipo}: {exc.mensaje}")
            return self._resultado_error(exc.mensaje, t0, ts, combinados, procesos, round(mejor, 4), modelo, exc.tipo)
        except ConfigError as exc:
            # crear_cliente_llm (Tarea 1) convierte un ConfigError propio en ErrorLLM, pero solo reconoce SU
            # propia clase rag_engine.config.ConfigError; self.cfg es radar_engine.config.Config y lanza ESTE
            # ConfigError (mismo nombre, clase distinta) cuando falta la variable de entorno de la clave de
            # API. Sin este except, una clave faltante tumbaba toda la app en vez de mostrarse como error.
            return self._resultado_error(str(exc), t0, ts, combinados, procesos, round(mejor, 4), modelo, "configuracion")
        try:
            referencia = self.tabla.costo(r.modelo, r.tokens_in, r.tokens_out, r.momento)
        except ErrorPrecio as exc:
            if not r.desde_cache:
                registrar_llamada(self.ruta_log, timestamp=ts, proveedor=r.proveedor or self.proveedor, modelo=r.modelo, nivel=self.nivel,
                                  tokens_in=r.tokens_in, tokens_out=r.tokens_out, latencia_ms=r.latencia_ms, costo_usd_real=0.0,
                                  costo_usd_referencia=0.0, intentos=r.intentos, exito=False, error=f"precio: {exc}")
            return self._resultado_error(f"La respuesta se generó pero no se pudo calcular su costo: {exc}", t0, ts, combinados, procesos,
                                         round(mejor, 4), r.modelo, "precio")
        real = 0.0 if self.nivel == "gratuito" else referencia
        if not r.desde_cache:
            registrar_llamada(self.ruta_log, timestamp=ts, proveedor=r.proveedor or self.proveedor, modelo=r.modelo, nivel=self.nivel,
                              tokens_in=r.tokens_in, tokens_out=r.tokens_out, latencia_ms=r.latencia_ms, costo_usd_real=real,
                              costo_usd_referencia=referencia, intentos=r.intentos, exito=True)
        self._marcar_citados(procesos, r.citas)
        comunes = dict(procesos=procesos, mejor_similitud=round(mejor, 4), filtros_aplicados=asdict(combinados), tokens_entrada=r.tokens_in,
                       tokens_salida=r.tokens_out, costo_usd_real=real, costo_usd_referencia=referencia,
                       latencia_ms=round((time.perf_counter() - t0) * 1000, 1), modelo=r.modelo, proveedor=r.proveedor or self.proveedor,
                       desde_cache=r.desde_cache, timestamp=ts)
        if not r.contexto_suficiente:
            return ResultadoRadar(respuesta=" ".join(self.cfg.get("mensajes.abstencion").split()), abstuvo=True, motivo_abstencion=MOTIVO_LLM, **comunes)
        return ResultadoRadar(respuesta=r.respuesta, abstuvo=False, **comunes)


# ───────────────────────── punto de entrada único ─────────────────────────

_MOTORES: dict[str, MotorRadar] = {}


def obtener_motor(cfg: Config | None = None) -> MotorRadar:
    """El índice y el modelo se cargan UNA sola vez por proceso (carga perezosa con caché)."""
    cfg = cfg or cargar_config()
    clave = str(cfg.archivo)
    if clave not in _MOTORES:
        _MOTORES[clave] = MotorRadar.desde_config(cfg)
    return _MOTORES[clave]


def consultar(pregunta: str, filtros: Filtros | None = None, cfg: Config | None = None, umbral_similitud: float | None = None) -> ResultadoRadar:
    """Responde una pregunta. Nunca lanza por errores esperados: los devuelve en ``ResultadoRadar.error``."""
    t0, ts = time.perf_counter(), _ahora().isoformat(timespec="seconds")
    try:
        motor = obtener_motor(cfg)
    except (IndiceNoDisponible, ConfigError, ErrorEmbeddings, ErrorPrecio, FileNotFoundError) as exc:
        return ResultadoRadar(respuesta=None, error=str(exc), error_tipo="configuracion",
                              latencia_ms=round((time.perf_counter() - t0) * 1000, 1), timestamp=ts)
    return motor.consultar(pregunta, filtros, umbral_similitud)

"""Motor RAG: UNA función, ``responder(pregunta)``, que devuelve un ``ResultadoRAG`` estructurado.

Toda interfaz (la app, un bot, una API) solo llama a esa función. Este módulo no conoce ninguna interfaz.
Orden de las decisiones (importa):
  1. Recuperar los fragmentos más similares.
  2. COMPUERTA DEL UMBRAL, ANTES de cualquier llamada al LLM: si la mejor similitud es menor que el umbral, se abstiene sin llamar
     al modelo (costo 0) y se devuelve el mensaje de config.yaml.
  3. Versiones: marcar fragmentos del Reglamento que mencionan artículos modificados y forzar los del DS 001.
  4. Generar con el LLM (salida estructurada). Si el modelo declara ``contexto_suficiente = false`` -> abstención con motivo
     ``llm_sin_contexto``. La abstención es un CAMPO (``abstuvo``), nunca se deduce leyendo el texto de la respuesta.
  5. Todo error (índice, red, clave, cuota agotada, formato) se devuelve en ``error`` (texto) y ``error_tipo`` (clasificación), con
     ``respuesta = None``: jamás como una respuesta normal.
Costos: ``costo_usd_real`` es lo que se cobra (0 en la capa gratuita) y ``costo_usd_referencia`` lo que costaría con el precio de pago.
Privacidad: al proveedor solo se envían la pregunta y fragmentos de normas públicas (ver ``_prompt_usuario``); nada más.
El motor nunca abre PDFs: solo lee el índice, la config y los JSON ya procesados. Cada llamada al LLM queda en logs/llm_calls.jsonl.
"""
from __future__ import annotations

import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from rag_engine.config import Config, ConfigError, cargar_config
from rag_engine.embeddings.base import Embedder, ErrorEmbeddings
from rag_engine.embeddings.factory import crear_embedder
from rag_engine.llm.base import ClienteLLM, ErrorLLM, RespuestaLLM
from rag_engine.llm.cost_log import registrar_llamada
from rag_engine.llm.factory import ajustes_llm, crear_cliente_llm, esquema_salida
from rag_engine.llm.pricing import ErrorPrecio, TablaPrecios, cargar_tabla
from rag_engine.retrieval.indice import IndiceNoDisponible, abrir_para_lectura
from rag_engine.retrieval.modos import buscar_por_modo
from rag_engine.retrieval.semantic import Recuperado
from rag_engine.retrieval.versions import GestorVersiones, Modificaciones

MOTIVO_UMBRAL = "umbral"
MOTIVO_LLM = "llm_sin_contexto"


@dataclass
class Fuente:
    documento: str
    version: str
    pagina: int
    similitud: float
    fragmento_id: str
    texto: str
    origen: str = "recuperado"          # "recuperado" (por similitud) | "version" (DS 001 forzado) | "original" (texto original del Reglamento forzado)
    citada: bool = False                # el modelo la citó en su respuesta


@dataclass
class ResultadoRAG:
    respuesta: str | None
    fuentes: list[Fuente] = field(default_factory=list)
    abstuvo: bool = False
    motivo_abstencion: str | None = None        # "umbral" | "llm_sin_contexto" | None
    mejor_similitud: float = 0.0
    tokens_entrada: int = 0
    tokens_salida: int = 0
    costo_usd_real: float = 0.0                 # lo que se cobra de verdad (0 en la capa gratuita)
    costo_usd_referencia: float = 0.0           # lo que costaría con el precio de PAGO del modelo (pricing.yaml)
    latencia_ms: float = 0.0                    # total de responder() (recuperación + generación)
    modelo: str | None = None
    proveedor: str | None = None
    advertencias_version: list[str] = field(default_factory=list)
    error: str | None = None
    error_tipo: str | None = None               # autenticacion | cuota_agotada | limite_de_tasa | red | servidor | solicitud | respuesta_malformada | ...
    desde_cache: bool = False                   # respuesta reutilizada de la caché de evaluación (no fue una llamada al proveedor)
    timestamp: str = ""

    def como_dict(self) -> dict:
        return asdict(self)


def _norm(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn").strip()


def _ahora() -> datetime:
    return datetime.now().astimezone()


class MotorRAG:
    def __init__(self, cfg: Config, embedder: Embedder, coleccion, modificaciones: Modificaciones, tabla_precios: TablaPrecios,
                 cliente_llm: ClienteLLM | None = None, ruta_log: Path | None = None, reloj=_ahora):
        self.cfg, self.embedder, self.coleccion = cfg, embedder, coleccion
        self.modificaciones, self.tabla, self._cliente_llm = modificaciones, tabla_precios, cliente_llm
        self.ruta_log = ruta_log or cfg.ruta("llm_calls_log")
        self.reloj = reloj
        self.docs = {d["id"]: d for d in cfg.documentos}
        self.roles = {i: d["rol"] for i, d in self.docs.items()}
        self.doc_modificatoria = next((i for i, r in self.roles.items() if r == "modificatoria"), "")
        self.versiones = GestorVersiones(coleccion, modificaciones, self.roles, cfg.get("mensajes.aviso_version"),
                                         cfg.get("retrieval.versiones.max_fragmentos_forzados"), cfg.get("retrieval.versiones.max_originales_forzados"))
        self._esquema = esquema_salida(cfg)
        self.ajustes_llm = ajustes_llm(cfg)
        self.proveedor, self.nivel = self.ajustes_llm["provider"], self.ajustes_llm["nivel"]

    @classmethod
    def desde_config(cls, cfg: Config | None = None) -> "MotorRAG":
        cfg = cfg or cargar_config()
        ruta_mod = cfg.ruta("articulos_modificados")
        if not ruta_mod.is_file():
            raise ConfigError(f"Falta {ruta_mod.name}. Ejecuta scripts/run_extraction.py para generarlo.")
        return cls(cfg, crear_embedder(cfg), abrir_para_lectura(cfg), Modificaciones.cargar(ruta_mod), cargar_tabla(cfg.ruta("pricing"), cfg.get("llm.provider")))

    # ── piezas ──

    def _llm(self) -> ClienteLLM:
        """Se crea al primer uso: una abstención por umbral no necesita clave de API."""
        if self._cliente_llm is None:
            self._cliente_llm = crear_cliente_llm(self.cfg)
        return self._cliente_llm

    def usar_cliente_llm(self, cliente: ClienteLLM) -> None:
        """Sustituye el cliente de LLM (p. ej. por uno con caché para la evaluación). El motor no cambia en nada más."""
        self._cliente_llm = cliente

    def _fuente(self, r: Recuperado) -> Fuente:
        return Fuente(documento=r.documento, version=r.version, pagina=r.pagina, similitud=round(r.similitud, 4), fragmento_id=r.id, texto=r.texto,
                      origen=r.metadatos.get("origen", "recuperado"))

    def _etiqueta(self, f: Fuente) -> str:
        nombre = self.docs.get(f.documento, {}).get("nombre_corto", f.documento)
        return self.cfg.get("prompts.etiqueta_fragmento").format(documento=nombre, version=f.version, pagina=f.pagina)

    def _prompt_usuario(self, pregunta: str, fuentes: list[Fuente]) -> str:
        """El contexto lleva primero los fragmentos de la modificatoria (prevalecen) y luego el resto, cada uno con su etiqueta de versión."""
        # La modificatoria va primero (prevalece), sea cual sea el motivo por el que está en el contexto; después el original forzado
        # para completarla; después el resto por similitud (sorted es estable: conserva el orden de relevancia dentro de cada grupo).
        orden = sorted(fuentes, key=lambda f: 0 if f.documento == self.doc_modificatoria else (1 if f.origen == "original" else 2))
        contexto = "\n\n".join(f"{self._etiqueta(f)}\n{f.texto}" for f in orden)
        return self.cfg.get("prompts.usuario").format(contexto=contexto, pregunta=pregunta)

    def _marcar_citadas(self, fuentes: list[Fuente], citas: list[dict]) -> None:
        nombres = {}
        for id_, d in self.docs.items():
            for alias in (id_, d.get("nombre_corto", ""), d["nombre"]):
                nombres[_norm(alias)] = id_
        citadas = set()
        for c in citas:
            doc = nombres.get(_norm(str(c.get("documento", ""))))
            try:
                citadas.add((doc, int(c.get("pagina"))))
            except (TypeError, ValueError):
                continue
        for f in fuentes:
            f.citada = (f.documento, f.pagina) in citadas

    def _resultado_error(self, mensaje: str, t0: float, ts: str, fuentes: list[Fuente] | None = None, mejor: float = 0.0, modelo: str | None = None,
                         tipo: str | None = None) -> ResultadoRAG:
        return ResultadoRAG(respuesta=None, fuentes=fuentes or [], abstuvo=False, mejor_similitud=mejor, latencia_ms=round((time.perf_counter() - t0) * 1000, 1),
                            modelo=modelo, proveedor=self.proveedor if modelo else None, error=mensaje, error_tipo=tipo, timestamp=ts)

    # ── la función principal ──

    def responder(self, pregunta: str) -> ResultadoRAG:
        t0, ts = time.perf_counter(), self.reloj().isoformat(timespec="seconds")
        if not pregunta or not pregunta.strip():
            return self._resultado_error("La pregunta está vacía.", t0, ts, tipo="pregunta_vacia")
        try:
            recuperados = buscar_por_modo(self.coleccion, self.embedder, pregunta, self.cfg)
        except Exception as exc:
            return self._resultado_error(f"No se pudo consultar el índice: {exc}", t0, ts, tipo="indice")
        mejor = max((r.similitud for r in recuperados), default=0.0)     # el mayor COSENO recuperado, sea cual sea el modo que ordenó (BM25 y RRF no son cosenos)
        fuentes = [self._fuente(r) for r in recuperados]

        # 2. compuerta del umbral: ANTES de llamar al LLM
        if not recuperados or mejor < self.cfg.get("retrieval.umbral_similitud"):
            return ResultadoRAG(respuesta=" ".join(self.cfg.get("mensajes.abstencion").split()), fuentes=fuentes, abstuvo=True, motivo_abstencion=MOTIVO_UMBRAL,
                                mejor_similitud=round(mejor, 4), latencia_ms=round((time.perf_counter() - t0) * 1000, 1), timestamp=ts)

        # 3. versiones
        advertencias: list[str] = []
        if self.cfg.get("retrieval.versiones.activo") and self.doc_modificatoria:
            vector = self.embedder.embed_query(pregunta)
            forzados, advertencias, _ = self.versiones.procesar(vector, recuperados)
            fuentes += [self._fuente(r) for r in forzados]

        # 4. generación
        modelo = self.ajustes_llm["modelo"]
        try:
            llm = self._llm()
            r: RespuestaLLM = llm.generar(self.cfg.get("prompts.sistema"), self._prompt_usuario(pregunta, fuentes), self._esquema)
        except ErrorLLM as exc:
            if exc.solicitud_enviada:              # solo las llamadas que realmente salieron al proveedor van al log de costos
                registrar_llamada(self.ruta_log, timestamp=ts, proveedor=self.proveedor, modelo=modelo, nivel=self.nivel, tokens_in=0, tokens_out=0, latencia_ms=0.0,
                                  costo_usd_real=0.0, costo_usd_referencia=0.0, intentos=exc.intentos, exito=False, error=f"{exc.tipo}: {exc.mensaje}")
            return self._resultado_error(exc.mensaje, t0, ts, fuentes, round(mejor, 4), modelo, exc.tipo)
        try:
            referencia = self.tabla.costo(r.modelo, r.tokens_in, r.tokens_out, r.momento)
        except ErrorPrecio as exc:
            if not r.desde_cache:
                registrar_llamada(self.ruta_log, timestamp=ts, proveedor=r.proveedor or self.proveedor, modelo=r.modelo, nivel=self.nivel, tokens_in=r.tokens_in,
                                  tokens_out=r.tokens_out, latencia_ms=r.latencia_ms, costo_usd_real=0.0, costo_usd_referencia=0.0, intentos=r.intentos,
                                  exito=False, error=f"precio: {exc}")
            return self._resultado_error(f"La respuesta se generó pero no se pudo calcular su costo: {exc}", t0, ts, fuentes, round(mejor, 4), r.modelo, "precio")
        real = 0.0 if self.nivel == "gratuito" else referencia          # en la capa gratuita no se cobra nada; la referencia dice cuánto costaría de pago
        if not r.desde_cache:                                           # una respuesta de la caché de evaluación NO fue una llamada al proveedor
            registrar_llamada(self.ruta_log, timestamp=ts, proveedor=r.proveedor or self.proveedor, modelo=r.modelo, nivel=self.nivel, tokens_in=r.tokens_in,
                              tokens_out=r.tokens_out, latencia_ms=r.latencia_ms, costo_usd_real=real, costo_usd_referencia=referencia, intentos=r.intentos, exito=True)
        self._marcar_citadas(fuentes, r.citas)
        comunes = dict(fuentes=fuentes, mejor_similitud=round(mejor, 4), tokens_entrada=r.tokens_in, tokens_salida=r.tokens_out, costo_usd_real=real,
                       costo_usd_referencia=referencia, latencia_ms=round((time.perf_counter() - t0) * 1000, 1), modelo=r.modelo, proveedor=r.proveedor or self.proveedor,
                       advertencias_version=advertencias, desde_cache=r.desde_cache, timestamp=ts)
        if not r.contexto_suficiente:
            return ResultadoRAG(respuesta=" ".join(self.cfg.get("mensajes.abstencion").split()), abstuvo=True, motivo_abstencion=MOTIVO_LLM, **comunes)
        return ResultadoRAG(respuesta=r.respuesta, abstuvo=False, **comunes)


# ───────────────────────── punto de entrada único ─────────────────────────

_MOTORES: dict[str, MotorRAG] = {}


def obtener_motor(cfg: Config | None = None) -> MotorRAG:
    """El índice y el modelo se cargan UNA sola vez por proceso (carga perezosa con caché)."""
    cfg = cfg or cargar_config()
    clave = str(cfg.archivo)
    if clave not in _MOTORES:
        _MOTORES[clave] = MotorRAG.desde_config(cfg)
    return _MOTORES[clave]


def responder(pregunta: str, cfg: Config | None = None) -> ResultadoRAG:
    """Responde una pregunta. Nunca lanza por errores esperados: los devuelve en ``ResultadoRAG.error``."""
    t0, ts = time.perf_counter(), _ahora().isoformat(timespec="seconds")
    try:
        motor = obtener_motor(cfg)
    except (IndiceNoDisponible, ConfigError, ErrorEmbeddings, ErrorPrecio, FileNotFoundError) as exc:
        return ResultadoRAG(respuesta=None, error=str(exc), error_tipo="configuracion", latencia_ms=round((time.perf_counter() - t0) * 1000, 1), timestamp=ts)
    return motor.responder(pregunta)

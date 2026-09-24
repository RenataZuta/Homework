"""Métricas de RECUPERACIÓN (sin llamar al LLM): cuestan USD 0 y miden solo troceado+embeddings+índice+filtros,
no la calidad de la generación. Es el mismo principio que ``evaluation/metrics.py`` de la Tarea 1, adaptado:
aquí el acierto es que el ``ocid`` esperado esté entre los k resultados (no documento+página).

Recall@k = fracción de preguntas in_domain para las que ALGÚN resultado entre los k primeros tiene el
``ocid`` esperado. Mide la etapa de recuperación (embeddings + filtros), no la generación ni la compuerta
del umbral.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from evaluation.eval_set_radar import Pregunta


class _Recuperado(Protocol):
    ocid: str
    similitud: float


@dataclass
class ResultadoPregunta:
    id: str
    tipo: str
    estilo: str
    rango_acierto: int | None = None      # posición (1 = primero) del primer resultado con el ocid esperado
    mejor_similitud: float = 0.0
    n_candidatos: int = 0                 # cuántos procesos pasaron los filtros ANTES de calcular similitud
    recuperados: list[tuple[str, float]] = field(default_factory=list)


@dataclass
class Evaluacion:
    ks: tuple[int, ...]
    por_pregunta: list[ResultadoPregunta]

    def _en_dominio(self, filtro: Callable[[ResultadoPregunta], bool] | None = None) -> list[ResultadoPregunta]:
        return [r for r in self.por_pregunta if r.tipo == "in_domain" and (filtro is None or filtro(r))]

    def _fuera_dominio(self) -> list[ResultadoPregunta]:
        return [r for r in self.por_pregunta if r.tipo == "out_of_domain"]

    def recall(self, k: int, filtro: Callable[[ResultadoPregunta], bool] | None = None) -> float | None:
        r = self._en_dominio(filtro)
        return sum(x.rango_acierto is not None and x.rango_acierto <= k for x in r) / len(r) if r else None

    def mrr(self) -> float:
        r = self._en_dominio()
        return sum(1 / x.rango_acierto for x in r if x.rango_acierto) / len(r) if r else 0.0

    def resumen(self) -> dict:
        salida: dict = {f"recall@{k}": self.recall(k) for k in self.ks}
        salida["mrr"] = self.mrr()
        for etiqueta, filtro in (("coloquial", lambda x: x.estilo == "coloquial"), ("directa", lambda x: x.estilo == "directa")):
            for k in self.ks:
                salida[f"recall@{k}_{etiqueta}"] = self.recall(k, filtro)
        return salida

    def fallos(self, k: int) -> list[ResultadoPregunta]:
        return [x for x in self._en_dominio() if x.rango_acierto is None or x.rango_acierto > k]


def evaluar_recuperacion(preguntas: list[Pregunta], recuperar: Callable[[Pregunta, int], tuple[list[_Recuperado], int]],
                         ks: tuple[int, ...] = (1, 3, 5)) -> Evaluacion:
    """``recuperar(pregunta, k)`` -> (los k resultados más similares que pasan sus filtros, nº de candidatos que pasaron el filtro)."""
    k_max = max(ks)
    resultados = []
    for q in preguntas:
        rec, n_candidatos = recuperar(q, k_max)
        r = ResultadoPregunta(q.id, q.tipo, q.estilo, mejor_similitud=max((x.similitud for x in rec), default=0.0),
                              n_candidatos=n_candidatos, recuperados=[(x.ocid, round(x.similitud, 4)) for x in rec])
        if q.tipo == "in_domain":
            for pos, x in enumerate(rec, start=1):
                if x.ocid in q.ocids_esperados and r.rango_acierto is None:
                    r.rango_acierto = pos
        resultados.append(r)
    return Evaluacion(ks=tuple(ks), por_pregunta=resultados)


@dataclass
class ResumenAbstencion:
    umbral: float
    in_domain: int
    out_of_domain: int
    respondidas_correctas: int          # in_domain con mejor_similitud >= umbral (el motor SÍ intentaría responder)
    abstenciones_incorrectas: int       # in_domain con mejor_similitud < umbral (se abstendría debiendo responder)
    abstenciones_correctas: int         # out_of_domain con mejor_similitud < umbral
    indebidas: int                      # out_of_domain con mejor_similitud >= umbral (respondería algo que no debía)

    def como_dict(self) -> dict:
        return {"umbral": self.umbral, "in_domain": self.in_domain, "out_of_domain": self.out_of_domain,
                "respondidas_correctas": self.respondidas_correctas, "abstenciones_incorrectas": self.abstenciones_incorrectas,
                "abstenciones_correctas": self.abstenciones_correctas, "indebidas": self.indebidas}


def evaluar_abstencion(ev: Evaluacion, umbral: float) -> ResumenAbstencion:
    dentro, fuera = ev._en_dominio(), ev._fuera_dominio()
    return ResumenAbstencion(umbral=umbral, in_domain=len(dentro), out_of_domain=len(fuera),
                             respondidas_correctas=sum(1 for x in dentro if x.mejor_similitud >= umbral),
                             abstenciones_incorrectas=sum(1 for x in dentro if x.mejor_similitud < umbral),
                             abstenciones_correctas=sum(1 for x in fuera if x.mejor_similitud < umbral),
                             indebidas=sum(1 for x in fuera if x.mejor_similitud >= umbral))

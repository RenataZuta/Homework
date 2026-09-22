"""Métricas de RECUPERACIÓN (sin llamar al LLM). Las reutilizan compare_chunking, select_local_model y run_eval.

Recall@k = fracción de preguntas in_domain para las que ALGÚN fragmento entre los k primeros coincide en documento y página con
lo esperado. Mide la etapa de recuperación (troceado + embeddings + índice). No mide la generación ni la compuerta del umbral.
En las preguntas de versiones se mide además el Recall@k de la MODIFICATORIA: acierto solo si el fragmento del DS 001 está entre
los k primeros (traer solo el texto original desactualizado no cuenta).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

from evaluation.eval_set import Pregunta


class _Recuperado(Protocol):
    documento: str
    pagina: int
    similitud: float


@dataclass
class ResultadoPregunta:
    id: str
    tipo: str
    estilo: str
    modificada_2026: bool
    rango_acierto: int | None = None                # posición (1 = primero) del primer fragmento correcto
    rango_modificatoria: int | None = None
    mejor_similitud: float = 0.0
    recuperados: list[tuple[str, int, float]] = field(default_factory=list)


@dataclass
class Evaluacion:
    ks: tuple[int, ...]
    por_pregunta: list[ResultadoPregunta]

    def _en_dominio(self, filtro: Callable[[ResultadoPregunta], bool] | None = None) -> list[ResultadoPregunta]:
        return [r for r in self.por_pregunta if r.tipo == "in_domain" and (filtro is None or filtro(r))]

    def recall(self, k: int, filtro: Callable[[ResultadoPregunta], bool] | None = None) -> float | None:
        r = self._en_dominio(filtro)
        return sum(x.rango_acierto is not None and x.rango_acierto <= k for x in r) / len(r) if r else None

    def recall_modificatoria(self, k: int) -> float | None:
        r = self._en_dominio(lambda x: x.modificada_2026)
        return sum(x.rango_modificatoria is not None and x.rango_modificatoria <= k for x in r) / len(r) if r else None

    def mrr(self) -> float:
        r = self._en_dominio()
        return sum(1 / x.rango_acierto for x in r if x.rango_acierto) / len(r) if r else 0.0

    def resumen(self) -> dict:
        salida: dict = {f"recall@{k}": self.recall(k) for k in self.ks}
        salida["mrr"] = self.mrr()
        for etiqueta, filtro in (("coloquial", lambda x: x.estilo == "coloquial"), ("juridico", lambda x: x.estilo == "juridico")):
            for k in self.ks:
                salida[f"recall@{k}_{etiqueta}"] = self.recall(k, filtro)
        for k in self.ks:
            salida[f"recall@{k}_modificatoria"] = self.recall_modificatoria(k)
        return salida

    def fallos(self, k: int) -> list[ResultadoPregunta]:
        return [x for x in self._en_dominio() if x.rango_acierto is None or x.rango_acierto > k]


def evaluar_recuperacion(preguntas: list[Pregunta], recuperar: Callable[[str, int], list[_Recuperado]], ks: tuple[int, ...] = (1, 3, 5)) -> Evaluacion:
    """`recuperar(texto, k)` devuelve los k fragmentos más similares, de mayor a menor similitud."""
    k_max = max(ks)
    resultados = []
    for q in preguntas:
        rec = recuperar(q.pregunta, k_max)
        r = ResultadoPregunta(q.id, q.tipo, q.estilo, q.modificada_2026,
                              mejor_similitud=max((x.similitud for x in rec), default=0.0),           # el mayor COSENO (en BM25/híbrido el primero por orden puede no serlo)
                              recuperados=[(x.documento, x.pagina, round(x.similitud, 4)) for x in rec])
        if q.tipo == "in_domain":
            for pos, x in enumerate(rec, start=1):
                if (x.documento, x.pagina) in q.pares and r.rango_acierto is None:
                    r.rango_acierto = pos
                if q.modificada_2026 and x.documento == q.documento_modificatoria and x.pagina in q.esperados[x.documento] \
                        and r.rango_modificatoria is None:
                    r.rango_modificatoria = pos
        resultados.append(r)
    return Evaluacion(ks=tuple(ks), por_pregunta=resultados)

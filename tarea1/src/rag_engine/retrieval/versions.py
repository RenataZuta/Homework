"""Manejo de versiones: el Reglamento original (DS 009-2025-EF) y su modificatoria (DS 001-2026-EF).

Estrategia (probada en tests/test_versions.py):
  1. METADATOS: cada fragmento lleva ``version`` (reglamento_original_2025 / modificatoria_2026-01) y los artículos del Reglamento que
     menciona (``articulos_reglamento``). ``data/processed/articulos_modificados.json`` dice qué artículos cambia el DS 001 y en qué
     página lo hace.
  2. MARCADO: si un fragmento recuperado del Reglamento menciona un artículo modificado, se marca como POSIBLEMENTE DESACTUALIZADO y se
     genera una advertencia («El artículo X fue modificado por el DS 001-2026-EF (…)»).
  3. FORZADO: se agregan al contexto los fragmentos del DS 001 que modifican esos artículos aunque no hayan salido entre los más
     similares (un texto modificatorio suele hablar de «numeral 114.2» y no usar las palabras de la pregunta).
  4. PROMPT: cada fragmento va etiquetado con su versión y se ordena que ante un conflicto PREVALEZCA el DS 001-2026-EF.
Solo aplica al REGLAMENTO: la Ley y el Reglamento numeran sus artículos por separado, y el DS 001 solo modifica el Reglamento.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from rag_engine.retrieval.semantic import Recuperado

ETIQUETA_TIPO = {"modifica": "modificado", "incorpora": "incorporado"}


@dataclass(frozen=True)
class Cambio:
    articulo: int
    tipo: str
    detalle: str
    pagina_ds001: int | None


@dataclass
class Modificaciones:
    por_articulo: dict[int, list[Cambio]] = field(default_factory=dict)

    @classmethod
    def cargar(cls, ruta: Path) -> "Modificaciones":
        datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
        por: dict[int, list[Cambio]] = {}
        for c in datos["cambios"]:
            por.setdefault(c["articulo"], []).append(Cambio(c["articulo"], c["tipo"], c["detalle"], c.get("pagina_ds001")))
        return cls(por)

    def detalle(self, articulo: int) -> str:
        """Resumen legible: «numeral 114.2 (incorporado); artículo completo (modificado)»."""
        partes = dict.fromkeys(f"{c.detalle} ({ETIQUETA_TIPO.get(c.tipo, c.tipo)})" for c in self.por_articulo[articulo])
        return "; ".join(partes)


def articulos_de_metadato(valor: str | None) -> list[int]:
    """«,15,114,» -> [15, 114]."""
    return [int(x) for x in (valor or "").split(",") if x.strip().isdigit()]


def _norm(t: str) -> str:
    t = "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", t)).strip()


def parsear_encabezado(enc: str | None) -> tuple[int, str] | None:
    """«Artículo 114. Retención de pago» -> (114, «retencion de pago»)."""
    m = re.match(r"Art[ií]culo\s+(\d{1,3})\.\s*(.*)$", enc or "")
    return (int(m.group(1)), _norm(m.group(2))) if m else None


def _como_recuperado(id_, texto, meta, emb, vector, origen: str) -> Recuperado:
    sim = float(np.dot(np.asarray(emb, dtype=np.float32), vector))
    return Recuperado(id=id_, documento=meta["documento"], version=meta["version"], pagina=int(meta["pagina"]), similitud=sim, texto=texto,
                      metadatos={**meta, "origen": origen})


class GestorVersiones:
    """Aplica la estrategia de versiones en AMBAS direcciones (ver el docstring del módulo).

    * Original -> modificatoria: un fragmento del Reglamento que menciona un artículo modificado dispara el aviso y se fuerzan los
      fragmentos del DS 001 que lo modifican (``origen = "version"``).
    * Modificatoria -> original: un fragmento del DS 001 solo transcribe los numerales que cambian («(…)» marca lo omitido); presentarlo
      como la regla completa sería un error. Se avisa y se fuerza el texto ORIGINAL del mismo artículo (``origen = "original"``),
      enlazado por número de artículo o, si el OCR leyó mal el número, por el título.
    """

    def __init__(self, coleccion, modificaciones: Modificaciones, roles: dict[str, str], plantilla_aviso: str,
                 max_modificatoria: int, max_originales: int):
        self.col, self.mods, self.roles, self.plantilla = coleccion, modificaciones, roles, plantilla_aviso
        self.doc_mod = next((d for d, r in roles.items() if r == "modificatoria"), "")
        self.doc_orig = next((d for d, r in roles.items() if r == "reglamento"), "")
        self.max_mod, self.max_orig = max_modificatoria, max_originales
        self._por_numero: dict[int, list[str]] | None = None
        self._por_titulo: dict[str, list[str]] = {}

    def _indexar_originales(self) -> None:
        """Se construye la primera vez que hace falta: articulo/título -> ids de los fragmentos del Reglamento original."""
        self._por_numero, self._por_titulo = {}, {}
        r = self.col.get(where={"documento": self.doc_orig}, include=["metadatas"])
        for id_, meta in zip(r["ids"], r["metadatas"]):
            enc = parsear_encabezado(meta.get("encabezado"))
            if enc:
                self._por_numero.setdefault(enc[0], []).append(id_)
                self._por_titulo.setdefault(enc[1], []).append(id_)

    def _fragmentos(self, ids: list[str], vector: np.ndarray, origen: str) -> list[Recuperado]:
        if not ids:
            return []
        r = self.col.get(ids=ids, include=["documents", "metadatas", "embeddings"])
        return sorted((_como_recuperado(i, t, m, e, vector, origen) for i, t, m, e in zip(r["ids"], r["documents"], r["metadatas"], r["embeddings"])),
                      key=lambda x: -x.similitud)

    def procesar(self, vector: np.ndarray, recuperados: list[Recuperado]) -> tuple[list[Recuperado], list[str], list[int]]:
        """Devuelve (fragmentos_forzados, advertencias, artículos_marcados)."""
        marcados: list[int] = []
        titulos: dict[int, str] = {}
        con_modificatoria: set[int] = set()        # artículos cuyo texto modificatorio YA está entre los recuperados
        con_original: set[int] = set()
        for r in recuperados:
            rol = self.roles.get(r.documento)
            if rol == "reglamento":
                for a in articulos_de_metadato(r.metadatos.get("articulos_reglamento")):
                    if a in self.mods.por_articulo and a not in marcados:
                        marcados.append(a)
                enc = parsear_encabezado(r.metadatos.get("encabezado"))
                if enc:
                    con_original.add(enc[0])
            elif rol == "modificatoria":
                enc = parsear_encabezado(r.metadatos.get("encabezado"))          # el artículo que ESTE fragmento transcribe
                if enc and enc[0] in self.mods.por_articulo:
                    if enc[0] not in marcados:
                        marcados.append(enc[0])
                    titulos[enc[0]] = enc[1]
                    con_modificatoria.add(enc[0])
        advertencias = [self.plantilla.format(articulo=a, detalle=self.mods.detalle(a)) for a in marcados]
        vistos = {r.id for r in recuperados}
        forzados: list[Recuperado] = []

        # original -> modificatoria
        pendientes_mod = [a for a in marcados if a not in con_modificatoria]
        por_articulo: dict[int, list[Recuperado]] = {}
        for a in pendientes_mod:
            cand = []
            for pagina in sorted({c.pagina_ds001 for c in self.mods.por_articulo[a] if c.pagina_ds001}):
                r = self.col.get(where={"$and": [{"documento": self.doc_mod}, {"pagina": pagina}]}, include=["documents", "metadatas", "embeddings"])
                for i, t, m, e in zip(r["ids"], r["documents"], r["metadatas"], r["embeddings"]):
                    if a in articulos_de_metadato(m.get("articulos_reglamento")):
                        propio = int(str(m.get("encabezado", "")).startswith(f"Artículo {a}."))     # el fragmento que ES el artículo va primero
                        cand.append((propio, _como_recuperado(i, t, m, e, vector, "version")))
            por_articulo[a] = [x for _, x in sorted(cand, key=lambda t: (t[0], t[1].similitud), reverse=True)]
        n_mod = 0
        for _ in range(self.max_mod):
            for a in pendientes_mod:
                lista = [x for x in por_articulo.get(a, []) if x.id not in vistos]
                if lista and n_mod < self.max_mod:
                    forzados.append(lista[0])
                    vistos.add(lista[0].id)
                    n_mod += 1

        # modificatoria -> original
        n_orig = 0
        for a in [x for x in marcados if x in con_modificatoria and x not in con_original]:
            if n_orig >= self.max_orig:
                break
            if self._por_numero is None:
                self._indexar_originales()
            ids = list(dict.fromkeys(self._por_numero.get(a, []) + self._por_titulo.get(titulos.get(a, ""), [])))
            for r in [x for x in self._fragmentos([i for i in ids if i not in vistos], vector, "original")][: max(1, self.max_orig - n_orig)]:
                if n_orig >= self.max_orig:
                    break
                forzados.append(r)
                vistos.add(r.id)
                n_orig += 1
        return forzados, advertencias, marcados

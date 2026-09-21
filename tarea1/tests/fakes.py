"""Dobles de prueba compartidos. El embedder falso es determinista, rápido y algo "semántico": las palabras compartidas
entre consulta y fragmento suben la similitud (bolsa de palabras hasheada), lo que permite probar la recuperación sin modelos."""
import hashlib
import re
import unicodedata

import numpy as np

from rag_engine.embeddings.base import Embedder


def _palabras(t: str) -> list[str]:
    t = "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z0-9]{3,}", t)


class EmbedderFalso(Embedder):
    name = "falso/bolsa-de-palabras"
    max_tokens = 512

    def __init__(self, dim: int = 1024, batch: int = 8, normalizar: bool = True):     # 1024: con menos dimensiones las colisiones inflan la similitud
        super().__init__(batch, normalizar)
        self.dim = dim
        self.textos_embebidos: list[str] = []          # para comprobar QUÉ se volvió a embeber

    def contar_tokens(self, textos, es_consulta=False):
        return [len(_palabras(t)) for t in textos]

    def _codificar(self, textos, es_consulta):
        m = np.zeros((len(textos), self.dim), dtype=np.float32)
        for i, t in enumerate(textos):
            for w in _palabras(t):
                m[i, int(hashlib.md5(w.encode()).hexdigest(), 16) % self.dim] += 1.0
        if not es_consulta:
            self.textos_embebidos += list(textos)
        return m, sum(self.contar_tokens(textos)), 0.0


# ── índice y LLM de juguete para probar el motor sin modelos ni red ──
import copy
import json
from datetime import datetime, timedelta, timezone

from rag_engine.config import Config
from rag_engine.llm.anthropic_client import ErrorLLM, RespuestaLLM

LIMA = timezone(timedelta(hours=-5))


def cfg_con(base: Config, **cambios) -> Config:
    """Copia de la config con claves punteadas cambiadas: cfg_con(cfg, **{"retrieval.umbral_similitud": 0.5})."""
    datos = copy.deepcopy(base.datos)
    for ruta, valor in cambios.items():
        *padres, hoja = ruta.split(".")
        d = datos
        for p in padres:
            d = d[p]
        d[hoja] = valor
    return Config(datos=datos, archivo=base.archivo)


class LLMFalso:
    """Imita a ClienteAnthropic.generar: registra lo que recibe y devuelve lo configurado (o lanza un ErrorLLM)."""

    def __init__(self, respuesta="Respuesta [Ley 32069, p. 32].", citas=None, suficiente=True, tokens=(2000, 300), error: ErrorLLM | None = None,
                 momento: datetime | None = None):
        self.llamadas: list[dict] = []
        self._r = dict(respuesta=respuesta, citas=citas if citas is not None else [{"documento": "Ley 32069", "pagina": 32}], suficiente=suficiente)
        self.tokens, self.error = tokens, error
        self.momento = momento or datetime(2026, 9, 21, 12, 0, tzinfo=LIMA)

    def generar(self, sistema, usuario, herramienta):
        self.llamadas.append({"sistema": sistema, "usuario": usuario, "herramienta": herramienta})
        if self.error:
            raise self.error
        return RespuestaLLM(respuesta=self._r["respuesta"], citas=self._r["citas"], contexto_suficiente=self._r["suficiente"], tokens_in=self.tokens[0],
                            tokens_out=self.tokens[1], latencia_ms=420.0, modelo="claude-haiku-4-5-20251001", momento=self.momento)


def paginas_sinteticas():
    def pg(n, texto):
        return {"pagina": n, "texto": texto, "origen": "texto"}
    ley = [pg(32, "Artículo 67. Pagos\n\n67.3. El pago se realiza en un plazo máximo de diez días hábiles luego de otorgada la conformidad por el área usuaria.\n\n"
                  "67.5. En caso de retraso en el pago la entidad reconoce al contratista los intereses legales correspondientes.")]
    reg = [pg(30, "Artículo 114. Retención de pago\n\nLa retención de pago como garantía de fiel cumplimiento aplica a contrataciones de bienes y servicios. "
                  "Si el contratista califica como micro o pequeña empresa procede la retención con independencia del monto de la contratación."),
           pg(31, "Artículo 120. Penalidad por mora en la ejecución de la prestación\n\n120.1. En caso de retraso injustificado la entidad aplica una penalidad "
                  "por mora por cada día de atraso, calculada con la fórmula del reglamento.")]
    mod = [pg(14, "“Artículo 114. Retención de pago\n114.1. La retención de pago como garantía de fiel cumplimiento aplica a contrataciones de bienes y servicios.\n"
                  "114.2. La retención de pago debe efectuarse durante la primera mitad del número total de pagos y de forma prorrateada en cada pago.”")]
    return {"ley_32069": ley, "ds_009_2025_ef": reg, "ds_001_2026_ef": mod}


def escribir_modificaciones(ruta):
    ruta.write_text(json.dumps({"cambios": [{"articulo": 114, "tipo": "incorpora", "detalle": "numeral 114.2", "pagina_ds001": 14, "fuente": "Artículo 3"}]}), encoding="utf-8")

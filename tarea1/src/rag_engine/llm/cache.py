"""Caché en disco de respuestas del LLM, PARA LA EVALUACIÓN de punta a punta (no para el uso normal del motor).

Objetivo: no gastar cuota (ni tiempo) repitiendo llamadas idénticas. La clave es el hash de TODO lo que determina la respuesta: proveedor,
modelo, temperatura, max_tokens, prompt de sistema, prompt de usuario (pregunta + fragmentos) y esquema. Si cambia cualquiera de ellos
(otro prompt, otro umbral que traiga otros fragmentos, otro modelo) hay una clave nueva y se llama de verdad.
  * Solo se guardan respuestas EXITOSAS; un error nunca se cachea.
  * Una respuesta de la caché sale marcada ``desde_cache=True``: el motor no la registra en llm_calls.jsonl porque no fue una llamada.
  * El cliente real se crea al primer fallo de caché, así con todo en caché la evaluación funciona sin clave de API.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable

from rag_engine.llm.base import ClienteLLM, EsquemaSalida, RespuestaLLM


class ClienteConCache(ClienteLLM):
    def __init__(self, fabrica_cliente: Callable[[], ClienteLLM], directorio: Path, proveedor: str, modelo: str, temperatura: float | None, max_tokens: int):
        self._fabrica, self._cliente = fabrica_cliente, None
        self.directorio = Path(directorio)
        self.proveedor, self.modelo, self.temperatura, self.max_tokens = proveedor, modelo, temperatura, max_tokens
        self.aciertos = self.fallos = 0

    def clave(self, sistema: str, usuario: str, esquema: EsquemaSalida) -> str:
        huella = {"proveedor": self.proveedor, "modelo": self.modelo, "temperatura": self.temperatura, "max_tokens": self.max_tokens,
                  "sistema": sistema, "usuario": usuario, "esquema": esquema.json_schema(), "esquema_nombre": esquema.nombre}
        return hashlib.sha256(json.dumps(huella, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    def _leer(self, ruta: Path) -> RespuestaLLM | None:
        try:
            d = json.loads(ruta.read_text(encoding="utf-8"))
            d["momento"] = datetime.fromisoformat(d["momento"])
            return RespuestaLLM(**{**d, "desde_cache": True, "intentos": 0})
        except (OSError, ValueError, KeyError, TypeError):
            return None                                                     # archivo ausente o dañado: se trata como fallo de caché

    def generar(self, sistema: str, usuario: str, esquema: EsquemaSalida) -> RespuestaLLM:
        ruta = self.directorio / f"{self.clave(sistema, usuario, esquema)}.json"
        guardada = self._leer(ruta)
        if guardada is not None:
            self.aciertos += 1
            return guardada
        self.fallos += 1
        if self._cliente is None:
            self._cliente = self._fabrica()
        r = self._cliente.generar(sistema, usuario, esquema)                # un error se propaga y NO se guarda
        self.directorio.mkdir(parents=True, exist_ok=True)
        datos = {**asdict(r), "momento": r.momento.isoformat()}
        tmp = ruta.with_suffix(".tmp")
        tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, ruta)
        return r

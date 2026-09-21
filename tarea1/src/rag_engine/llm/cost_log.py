"""Registro de cada llamada al LLM en logs/llm_calls.jsonl: una línea por llamada, éxito o fallo.

Campos: timestamp (ISO con zona), modelo, tokens_in, tokens_out, latencia_ms, costo_usd, exito, error.
Los mensajes de error se sanean: nunca se escribe una clave de API en el log.
"""
from __future__ import annotations

import json
import re
import statistics
from pathlib import Path

CAMPOS = ("timestamp", "modelo", "tokens_in", "tokens_out", "latencia_ms", "costo_usd", "exito", "error")
_RE_CLAVES = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|\b\d{8,10}:[A-Za-z0-9_\-]{30,}|Bearer\s+\S+|x-api-key['\":\s]+\S+)", re.I)


def sanear(texto: str | None, maximo: int = 300) -> str | None:
    if texto is None:
        return None
    limpio = _RE_CLAVES.sub("[CLAVE-OCULTA]", " ".join(str(texto).split()))
    return limpio[:maximo]


def registrar_llamada(ruta: Path, *, timestamp: str, modelo: str, tokens_in: int, tokens_out: int, latencia_ms: float,
                      costo_usd: float, exito: bool, error: str | None = None) -> dict:
    registro = {"timestamp": timestamp, "modelo": modelo, "tokens_in": int(tokens_in), "tokens_out": int(tokens_out),
                "latencia_ms": round(float(latencia_ms), 1), "costo_usd": round(float(costo_usd), 8), "exito": bool(exito), "error": sanear(error)}
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")            # una sola escritura por línea
    return registro


def leer_registros(ruta: Path) -> list[dict]:
    """Todas las líneas válidas del log (una línea dañada se ignora, no rompe la lectura)."""
    if not Path(ruta).is_file():
        return []
    salida = []
    for linea in Path(ruta).read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(linea)
        except json.JSONDecodeError:
            continue
        if all(c in r for c in CAMPOS):
            salida.append(r)
    return salida


def resumen(registros: list[dict]) -> dict:
    ok = [r for r in registros if r["exito"]]
    return {"llamadas": len(registros), "exitosas": len(ok), "fallidas": len(registros) - len(ok),
            "tokens_in": sum(r["tokens_in"] for r in registros), "tokens_out": sum(r["tokens_out"] for r in registros),
            "costo_total_usd": round(sum(r["costo_usd"] for r in registros), 6),
            "costo_medio_por_consulta_usd": round(sum(r["costo_usd"] for r in ok) / len(ok), 6) if ok else None,
            "latencia_mediana_ms": round(statistics.median(r["latencia_ms"] for r in ok), 1) if ok else None}

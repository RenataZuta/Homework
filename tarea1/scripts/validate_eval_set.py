#!/usr/bin/env python3
"""validate_eval_set.py — valida eval/preguntas.csv contra el subconjunto procesado y eval/evidencia.yaml.

Sale con código 1 si hay errores. Uso (desde tarea1/):  python scripts/validate_eval_set.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from evaluation.eval_set import cargar_evidencia, cargar_preguntas, validar  # noqa: E402
from rag_engine.config import ConfigError, cargar_config  # noqa: E402


def main() -> int:
    try:
        cfg = cargar_config(cargar_env=False)
        manifiesto = json.loads(cfg.ruta("manifest").read_text(encoding="utf-8"))["documentos"]
        preguntas = cargar_preguntas(cfg.ruta("eval_preguntas"))
        evidencia = cargar_evidencia(cfg.ruta("eval_preguntas").with_name("evidencia.yaml"))
    except (ConfigError, FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    errores, stats = validar(preguntas, evidencia, {d["id"]: d for d in cfg.documentos}, cfg.ruta("processed"),
                             {k: v["paginas"] for k, v in manifiesto.items()}, cfg.get("eval.requisitos_set"))
    print("Set de evaluación:", ", ".join(f"{k}={v}" for k, v in stats.items()))
    for e in errores:
        print(f"  ERROR {e}", file=sys.stderr)
    print("RESULTADO:", "válido" if not errores else f"{len(errores)} error(es)")
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())

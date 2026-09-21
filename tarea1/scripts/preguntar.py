#!/usr/bin/env python3
"""preguntar.py — hace una pregunta al motor desde la terminal y muestra el ResultadoRAG completo.

Uso (desde tarea1/):  python scripts/preguntar.py "¿Puedo pedir un adelanto para empezar a trabajar?"
Sirve para probar el motor sin ninguna interfaz. Las abstenciones por umbral NO necesitan ANTHROPIC_API_KEY; responder sí.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from rag_engine.engine import responder  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = (argv if argv is not None else sys.argv[1:])
    if not args:
        print('Uso: python scripts/preguntar.py "tu pregunta"', file=sys.stderr)
        return 2
    r = responder(" ".join(args))
    if r.error:
        print(f"ERROR: {r.error}")
        print(f"(mejor similitud {r.mejor_similitud:.3f}; latencia {r.latencia_ms:.0f} ms)")
        return 1
    estado = f"ABSTENCIÓN ({r.motivo_abstencion})" if r.abstuvo else "RESPUESTA"
    print(f"══ {estado} · mejor similitud {r.mejor_similitud:.3f} · {r.latencia_ms:.0f} ms")
    print(r.respuesta)
    for a in r.advertencias_version:
        print(f"⚠ {a}")
    print("\nFuentes:")
    for f in r.fuentes:
        marca = "★" if f.citada else " "
        print(f" {marca} {f.documento} p.{f.pagina} · {f.version} · sim {f.similitud:.3f} · {f.origen}")
    if r.modelo:
        print(f"\nModelo {r.modelo} · {r.tokens_entrada} tokens de entrada, {r.tokens_salida} de salida · costo USD {r.costo_usd:.6f}")
    else:
        print("\nSin llamada al modelo (costo USD 0).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

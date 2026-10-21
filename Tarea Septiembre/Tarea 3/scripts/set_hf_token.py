"""Guarda HF_TOKEN en .env pidiéndolo por teclado SIN mostrarlo.

Uso (desde Tarea 3/):  python scripts/set_hf_token.py
El valor no se imprime ni queda en el historial; .env está en .gitignore.
"""
from __future__ import annotations

import getpass
import os
import re
import stat
import sys
from pathlib import Path

RUTA_ENV = Path(__file__).resolve().parents[1] / ".env"


def main() -> int:
    valor = getpass.getpass("Pega tu token de Hugging Face (no se verá) y pulsa Enter: ").strip()
    if not valor or "\n" in valor:
        print("No se guardó nada: valor vacío o inválido.", file=sys.stderr)
        return 1
    if not valor.startswith("hf_"):
        print("AVISO: los tokens de Hugging Face suelen empezar con 'hf_'. Se guarda igual.")
    texto = RUTA_ENV.read_text(encoding="utf-8") if RUTA_ENV.exists() else ""
    linea = f"HF_TOKEN={valor}"
    if re.search(r"^HF_TOKEN=.*$", texto, flags=re.M):
        texto = re.sub(r"^HF_TOKEN=.*$", lambda _m: linea, texto, count=1, flags=re.M)
    else:
        texto += ("" if not texto or texto.endswith("\n") else "\n") + linea + "\n"
    tmp = RUTA_ENV.with_name(".env.tmp")
    tmp.write_text(texto, encoding="utf-8")
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp, RUTA_ENV)
    print(f"Guardado HF_TOKEN en {RUTA_ENV.name} ({len(valor)} caracteres). No se mostró.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

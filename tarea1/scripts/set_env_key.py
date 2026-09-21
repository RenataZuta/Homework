"""Guarda una credencial en tarea1/.env pidiéndola por teclado SIN mostrarla.

Uso (desde tarea1/):
    python scripts/set_env_key.py ANTHROPIC_API_KEY
    python scripts/set_env_key.py OPENAI_API_KEY
    python scripts/set_env_key.py --estado        # qué variables están definidas (sí/no, nunca el valor)

El valor no se imprime, no queda en el historial del terminal ni pasa por el chat.
Solo se aceptan los nombres que figuran en .env.example.
"""
from __future__ import annotations

import argparse
import getpass
import os
import re
import stat
import sys
from pathlib import Path

DIRECTORIO = Path(__file__).resolve().parents[1]
RUTA_ENV = DIRECTORIO / ".env"
RUTA_EJEMPLO = DIRECTORIO / ".env.example"

# Prefijos habituales, solo para AVISAR si parece un valor equivocado (no bloquea).
PREFIJOS = {"ANTHROPIC_API_KEY": "sk-ant-", "OPENAI_API_KEY": "sk-"}


def nombres_permitidos(ruta_ejemplo: Path = RUTA_EJEMPLO) -> list[str]:
    """Nombres de variables declarados en .env.example (la única fuente de verdad)."""
    return re.findall(r"^([A-Z][A-Z0-9_]*)=", ruta_ejemplo.read_text(encoding="utf-8"), flags=re.M)


def actualizar_env(texto: str, nombre: str, valor: str) -> str:
    """Devuelve el contenido de .env con ``nombre=valor`` (reemplaza la línea existente o la añade)."""
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", nombre):
        raise ValueError(f"Nombre de variable inválido: {nombre!r}")
    if "\n" in valor or "\r" in valor:
        raise ValueError("El valor no puede contener saltos de línea.")
    linea = f"{nombre}={valor}"
    patron = re.compile(rf"^{re.escape(nombre)}=.*$", flags=re.M)
    if patron.search(texto):
        return patron.sub(lambda _m: linea, texto, count=1)
    if texto and not texto.endswith("\n"):
        texto += "\n"
    return texto + linea + "\n"


def variables_definidas(texto: str) -> dict[str, bool]:
    """{nombre: True si tiene un valor no vacío}. Nunca devuelve los valores."""
    out: dict[str, bool] = {}
    for m in re.finditer(r"^([A-Z][A-Z0-9_]*)=(.*)$", texto, flags=re.M):
        out[m.group(1)] = bool(m.group(2).strip())
    return out


def _escribir_atomico(ruta: Path, texto: str) -> None:
    tmp = ruta.with_name(ruta.name + ".tmp")
    tmp.write_text(texto, encoding="utf-8")
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)          # solo tú puedes leerlo (en Windows se ignora)
    os.replace(tmp, ruta)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("nombre", nargs="?", help="Nombre de la variable (p. ej. ANTHROPIC_API_KEY)")
    ap.add_argument("--estado", action="store_true", help="Muestra qué variables están definidas, sin valores")
    args = ap.parse_args(argv)

    permitidos = nombres_permitidos()
    actual = RUTA_ENV.read_text(encoding="utf-8") if RUTA_ENV.exists() else ""

    if args.estado or not args.nombre:
        estado = variables_definidas(actual)
        for n in permitidos:
            print(f"  {n:<28} {'DEFINIDA' if estado.get(n) else 'vacía / ausente'}")
        return 0

    if args.nombre not in permitidos:
        print(f"ERROR: '{args.nombre}' no está en .env.example. Permitidas: {', '.join(permitidos)}", file=sys.stderr)
        return 2

    valor = getpass.getpass(f"Pega el valor de {args.nombre} (no se verá al escribir) y pulsa Enter: ").strip()
    if not valor:
        print("No se guardó nada: el valor estaba vacío.", file=sys.stderr)
        return 1
    prefijo = PREFIJOS.get(args.nombre)
    if prefijo and not valor.startswith(prefijo):
        print(f"AVISO: normalmente {args.nombre} empieza con '{prefijo}'. Se guarda igual; si falla, revísalo.")
    try:
        nuevo = actualizar_env(actual, args.nombre, valor)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    _escribir_atomico(RUTA_ENV, nuevo)
    print(f"Guardada {args.nombre} en {RUTA_ENV.name} ({len(valor)} caracteres). El valor no se mostró.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

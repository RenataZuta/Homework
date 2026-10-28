"""Copia los audios grabados a las carpetas audio/ de cada tarea.

  entrevista_*  ->  tasks/task1_interview/audio/
  llamada_*     ->  tasks/task2_sales/audio/

Acepta también nombres como "Entrevista 1.m4a" o "Llamada 01.m4a" (mayúsculas, espacio o guion)
y los copia normalizados: entrevista_01.m4a, llamada_01.m4a. Los originales no se tocan.

Los audios no se commitean (tasks/*/audio/ está en el .gitignore del repo).

Uso:  python scripts/organize_audio.py <carpeta_con_los_audios>
"""
import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # Tarea 4/
AUDIO_EXTS = {".wav", ".mp3", ".ogg", ".opus", ".m4a", ".flac"}
DESTINOS = {
    "entrevista_": ROOT / "tasks" / "task1_interview" / "audio",
    "llamada_": ROOT / "tasks" / "task2_sales" / "audio",
}
NOMBRE = re.compile(r"^(entrevista|llamada)[ _-]*(\d+)", re.IGNORECASE)
ESPERADOS = 5  # por tarea: 5 entrevistas y 5 llamadas


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("carpeta", type=Path, help="carpeta con los 10 audios")
    carpeta = parser.parse_args().carpeta

    if not carpeta.is_dir():
        sys.exit(f"Error: '{carpeta}' no es una carpeta.")

    copiados = {prefijo: 0 for prefijo in DESTINOS}
    ignorados = []
    for archivo in sorted(carpeta.iterdir()):
        if not archivo.is_file() or archivo.name.startswith("."):
            continue
        m = NOMBRE.match(archivo.name)
        if m is None or archivo.suffix.lower() not in AUDIO_EXTS:
            ignorados.append(archivo.name)
            continue
        prefijo = m.group(1).lower() + "_"
        nombre = f"{prefijo}{int(m.group(2)):02d}{archivo.suffix.lower()}"
        DESTINOS[prefijo].mkdir(parents=True, exist_ok=True)
        shutil.copy2(archivo, DESTINOS[prefijo] / nombre)
        copiados[prefijo] += 1

    for prefijo, destino in DESTINOS.items():
        print(f"{copiados[prefijo]} archivo(s) {prefijo}* copiados a {destino.relative_to(ROOT)}/")
        if copiados[prefijo] != ESPERADOS:
            print(f"  Aviso: se esperaban {ESPERADOS}.")
    if ignorados:
        print(f"Ignorados (no son entrevista_/llamada_ de audio): {', '.join(ignorados)}")


if __name__ == "__main__":
    main()

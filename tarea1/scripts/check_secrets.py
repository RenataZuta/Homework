#!/usr/bin/env python3
"""check_secrets.py — busca claves y tokens en el árbol de trabajo y en el historial de git.

Uso (desde cualquier carpeta del repo):
    python tarea1/scripts/check_secrets.py                  # árbol + historial completo
    python tarea1/scripts/check_secrets.py --arbol          # solo archivos actuales
    python tarea1/scripts/check_secrets.py --historial      # solo git log -p
    python tarea1/scripts/check_secrets.py --desde origin/main   # historial de origin/main..HEAD

Códigos de salida: 0 = limpio, 1 = se encontraron posibles secretos, 2 = error de ejecución.

Qué busca: claves de Anthropic (sk-ant-), de OpenAI (sk-), tokens de bots de Telegram
(número:cadena), tokens de GitHub y Hugging Face, claves de AWS, claves privadas,
asignaciones tipo NOMBRE_API_KEY=valor, y archivos .env versionados.

Nunca imprime un secreto completo: solo los primeros caracteres y la longitud, para que
ejecutar este chequeo (o pegar su salida) no filtre lo que intenta proteger.
En el historial solo se examinan las líneas AÑADIDAS de cada commit: ahí aparece por primera vez
cualquier secreto, aunque un commit posterior lo haya borrado.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

PATRONES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("anthropic_api_key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("google_api_key", re.compile(r"(?<![A-Za-z0-9_\-])AIza[0-9A-Za-z_\-]{35}(?![0-9A-Za-z_\-])")),
    ("openai_api_key", re.compile(r"(?<![A-Za-z0-9_])sk-(?!ant-)(?:proj-|svcacct-)?[A-Za-z0-9_\-]{20,}")),
    ("telegram_bot_token", re.compile(r"(?<![0-9])[0-9]{8,10}:[A-Za-z0-9_\-]{35}(?![A-Za-z0-9_\-])")),
    ("github_token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,}")),
    ("huggingface_token", re.compile(r"(?<![A-Za-z0-9_])hf_[A-Za-z0-9]{30,}")),
    ("aws_access_key", re.compile(r"(?<![A-Z0-9])AKIA[0-9A-Z]{16}(?![A-Z0-9])")),
    ("clave_privada", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")),
)

# NOMBRE_EN_MAYÚSCULAS_CON_KEY/TOKEN/SECRET/PASSWORD = valor (estilo .env, YAML o código)
ASIGNACION = re.compile(
    r"^\s*(?:export\s+)?[\"']?([A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*)[\"']?"
    r"\s*[=:]\s*[\"']?([^\s\"'#]{12,})"
)
MARCADORES_DE_RELLENO = (
    "<", "...", "xxx", "changeme", "example", "tu_", "your", "dummy", "fake", "placeholder",
    "${", "$(", "os.environ", "getenv", "secrets.", "env.", "none", "null",
)

EXTENSIONES_BINARIAS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip", ".gz", ".whl", ".pyc",
    ".xlsx", ".xls", ".docx", ".parquet", ".sqlite", ".db", ".bin", ".onnx", ".pt", ".safetensors",
}
TAMANO_MAXIMO_BYTES = 5_000_000
MARCA_COMMIT = "COMMIT_CHECK_SECRETS"


@dataclass(frozen=True)
class Hallazgo:
    origen: str        # "arbol" | "historial"
    patron: str
    ubicacion: str     # ruta[:línea]
    muestra: str       # valor ENMASCARADO
    commit: str = ""


def enmascarar(valor: str) -> str:
    return f"{valor[:6]}...({len(valor)} caracteres)"


def _es_relleno(valor: str) -> bool:
    bajo = valor.lower()
    return bajo.startswith("$") or any(m in bajo for m in MARCADORES_DE_RELLENO) or len(set(valor)) <= 2


def buscar_en_linea(linea: str) -> list[tuple[str, str]]:
    """Devuelve [(patrón, valor_completo)]; el valor solo se usa para enmascararlo."""
    encontrados: list[tuple[str, str]] = []
    for nombre, patron in PATRONES:
        for m in patron.finditer(linea):
            encontrados.append((nombre, m.group(0)))
    m = ASIGNACION.match(linea)
    if m and not _es_relleno(m.group(2)) and not any(v == m.group(2) for _, v in encontrados):
        encontrados.append((f"asignacion:{m.group(1)}", m.group(2)))
    return encontrados


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(repo), "-c", "core.quotepath=false", *args],
                          capture_output=True, check=True)


def raiz_del_repo(inicio: Path) -> Path:
    salida = _git(inicio, "rev-parse", "--show-toplevel").stdout.decode().strip()
    return Path(salida)


def _es_env_versionado(ruta: str) -> bool:
    nombre = Path(ruta).name
    return nombre == ".env" or (nombre.startswith(".env.") and nombre != ".env.example")


def escanear_arbol(repo: Path) -> tuple[list[Hallazgo], int]:
    """Archivos versionados y sin ignorar (lo que un `git add` subiría)."""
    listado = _git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard").stdout
    hallazgos: list[Hallazgo] = []
    revisados = 0
    for bruto in listado.split(b"\0"):
        if not bruto:
            continue
        ruta = bruto.decode("utf-8", errors="replace")
        if _es_env_versionado(ruta):
            hallazgos.append(Hallazgo("arbol", "archivo_env_versionado", ruta, "(archivo completo)"))
        archivo = repo / ruta
        if archivo.suffix.lower() in EXTENSIONES_BINARIAS or not archivo.is_file():
            continue
        try:
            if archivo.stat().st_size > TAMANO_MAXIMO_BYTES:
                continue
            contenido = archivo.read_bytes()
        except OSError:
            continue
        if b"\0" in contenido[:8000]:
            continue  # binario
        revisados += 1
        for n, linea in enumerate(contenido.decode("utf-8", errors="ignore").splitlines(), start=1):
            for patron, valor in buscar_en_linea(linea):
                hallazgos.append(Hallazgo("arbol", patron, f"{ruta}:{n}", enmascarar(valor)))
    return hallazgos, revisados


def _lineas_añadidas(repo: Path, desde: str | None) -> Iterator[tuple[str, str, str, int, str]]:
    """Genera (commit, fecha, ruta, nº_línea, texto) por cada línea añadida en el historial."""
    rango = [f"{desde}..HEAD"] if desde else ["--all"]
    cmd = ["git", "-C", str(repo), "-c", "core.quotepath=false", "log", "-p", "-U0", "--no-color",
           f"--format={MARCA_COMMIT} %H %ad", "--date=short", *rango]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    commit = fecha = ruta = ""
    n = 0
    assert proc.stdout is not None
    for bruto in proc.stdout:
        linea = bruto.decode("utf-8", errors="replace").rstrip("\n")
        if linea.startswith(MARCA_COMMIT):
            _, commit, fecha = linea.split(" ", 2)
        elif linea.startswith("+++ b/"):
            ruta = linea[6:].rstrip("\t")
        elif linea.startswith("+++ /dev/null"):
            ruta = ""
        elif linea.startswith("@@"):
            m = re.search(r"\+(\d+)", linea)
            n = int(m.group(1)) if m else 0
        elif linea.startswith("+") and ruta:
            yield commit, fecha, ruta, n, linea[1:]
            n += 1
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.read().decode("utf-8", errors="replace").strip() or "git log falló")


def escanear_historial(repo: Path, desde: str | None = None) -> tuple[list[Hallazgo], int, int]:
    hallazgos: list[Hallazgo] = []
    lineas = 0
    for commit, fecha, ruta, n, texto in _lineas_añadidas(repo, desde):
        lineas += 1
        for patron, valor in buscar_en_linea(texto):
            hallazgos.append(Hallazgo("historial", patron, f"{ruta}:{n}", enmascarar(valor), f"{commit[:8]} ({fecha})"))
        if _es_env_versionado(ruta) and n <= 1:
            hallazgos.append(Hallazgo("historial", "archivo_env_versionado", ruta, "(archivo completo)", f"{commit[:8]} ({fecha})"))
    conteo = _git(repo, "rev-list", "--count", f"{desde}..HEAD" if desde else "--all").stdout.decode().strip()
    return hallazgos, int(conteo or 0), lineas


def _mostrar(titulo: str, hallazgos: list[Hallazgo]) -> None:
    for h in hallazgos:
        donde = f" en commit {h.commit}" if h.commit else ""
        print(f"  [{titulo}] {h.patron}: {h.ubicacion}{donde} -> {h.muestra}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="Busca claves y tokens en el árbol y en el historial de git.")
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent, help="carpeta dentro del repo (por defecto, la del script)")
    ap.add_argument("--arbol", action="store_true", help="revisar solo los archivos actuales")
    ap.add_argument("--historial", action="store_true", help="revisar solo git log -p")
    ap.add_argument("--desde", metavar="REV", help="limitar el historial a REV..HEAD (p. ej. origin/main)")
    args = ap.parse_args(argv)
    hacer_arbol = args.arbol or not args.historial
    hacer_historial = args.historial or not args.arbol

    try:
        repo = raiz_del_repo(args.repo)
        todos: list[Hallazgo] = []
        print(f"check_secrets: repo {repo}")
        if hacer_arbol:
            hallazgos, revisados = escanear_arbol(repo)
            todos += hallazgos
            print(f"  árbol: {revisados} archivos de texto revisados, {len(hallazgos)} hallazgos")
            _mostrar("ARBOL", hallazgos)
        if hacer_historial:
            hallazgos, commits, lineas = escanear_historial(repo, args.desde)
            todos += hallazgos
            alcance = f"{args.desde}..HEAD" if args.desde else "todas las ramas"
            print(f"  historial ({alcance}): {commits} commits, {lineas} líneas añadidas revisadas, {len(hallazgos)} hallazgos")
            _mostrar("HISTORIAL", hallazgos)
    except (subprocess.CalledProcessError, RuntimeError, FileNotFoundError) as exc:
        detalle = exc.stderr.decode(errors="replace") if isinstance(exc, subprocess.CalledProcessError) and exc.stderr else exc
        print(f"check_secrets: ERROR de ejecución: {detalle}", file=sys.stderr)
        return 2

    if todos:
        print(f"\nRESULTADO: {len(todos)} posibles secretos. Revísalos; si son reales, rota la clave (borrar el commit no basta).")
        return 1
    print("\nRESULTADO: limpio, sin claves ni tokens.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

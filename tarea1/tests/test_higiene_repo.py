"""Reglas de higiene del repositorio: se verifican como tests para que el CI las vigile."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

TAREA1 = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = TAREA1 / ".env.example"
MOTOR = TAREA1 / "src" / "rag_engine"

VARIABLES_ESPERADAS = {
    "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USER_IDS",
    "TELEGRAM_WEBHOOK_SECRET", "BACKEND_INTERNAL_KEY", "TESSERACT_CMD",
}
# Es el mismo patrón que el README manda a ejecutar (Select-String / grep -rnE).
PATRON_UI = re.compile(r"streamlit|telegram|fastapi|flask|gradio", re.IGNORECASE)


def test_env_example_tiene_solo_nombres_y_ningun_valor():
    lineas = [l.strip() for l in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()]
    asignaciones = [l for l in lineas if l and not l.startswith("#")]
    nombres = set()
    for linea in asignaciones:
        assert re.fullmatch(r"[A-Z][A-Z0-9_]*=", linea), f".env.example no debe traer valores: {linea!r}"
        nombres.add(linea[:-1])
    assert nombres == VARIABLES_ESPERADAS


@pytest.mark.skipif(shutil.which("git") is None, reason="git no disponible")
def test_env_real_esta_ignorado_y_el_ejemplo_no():
    def ignorado(nombre: str) -> bool:
        return subprocess.run(["git", "-C", str(TAREA1), "check-ignore", "-q", nombre],
                              capture_output=True).returncode == 0
    inicio = subprocess.run(["git", "-C", str(TAREA1), "rev-parse", "--is-inside-work-tree"],
                            capture_output=True, text=True)
    if inicio.returncode != 0:
        pytest.skip("no estamos dentro de un repositorio git")
    assert ignorado(".env"), ".env NO está en .gitignore"
    assert not ignorado(".env.example"), ".env.example no debe ignorarse"


def test_el_motor_no_menciona_librerias_de_interfaz():
    """Regla global 3: 0 coincidencias en todo src/rag_engine (subpaquetes incluidos)."""
    coincidencias = []
    for archivo in sorted(MOTOR.rglob("*.py")):
        for n, linea in enumerate(archivo.read_text(encoding="utf-8").splitlines(), start=1):
            if PATRON_UI.search(linea):
                coincidencias.append(f"{archivo.relative_to(TAREA1)}:{n}: {linea.strip()}")
    assert not coincidencias, "El motor no debe conocer las interfaces:\n" + "\n".join(coincidencias)

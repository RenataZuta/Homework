"""Pruebas de scripts/check_secrets.py. Los secretos falsos se arman al vuelo para que este
archivo no contenga ninguno."""
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

RUTA_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_secrets.py"
spec = importlib.util.spec_from_file_location("check_secrets", RUTA_SCRIPT)
cs = importlib.util.module_from_spec(spec)
sys.modules["check_secrets"] = cs  # los @dataclass lo necesitan
spec.loader.exec_module(cs)

# ── secretos falsos (con la forma real, sin serlo) ──
FALSA_ANTHROPIC = "sk-" + "ant-" + "a1" * 20
FALSA_OPENAI = "sk-" + "proj-" + "b2" * 20
FALSO_TELEGRAM = "123456789" + ":" + "AAH" + "x" * 32
FALSO_GITHUB = "ghp_" + "c3" * 20
FALSO_HF = "hf_" + "d4" * 20
FALSA_CLAVE_PRIVADA = "-----BEGIN " + "RSA PRIVATE KEY-----"


def _nombres(linea: str) -> list[str]:
    return [n for n, _ in cs.buscar_en_linea(linea)]


# ── detección por línea ──

@pytest.mark.parametrize("linea, esperado", [
    (f"clave = '{FALSA_ANTHROPIC}'", "anthropic_api_key"),
    (f"clave = '{FALSA_OPENAI}'", "openai_api_key"),
    (f"bot: {FALSO_TELEGRAM}", "telegram_bot_token"),
    (f"token {FALSO_GITHUB}", "github_token"),
    (f"HF {FALSO_HF}", "huggingface_token"),
    (FALSA_CLAVE_PRIVADA, "clave_privada"),
])
def test_detecta_cada_tipo_de_secreto(linea, esperado):
    assert esperado in _nombres(linea)


def test_una_clave_anthropic_no_se_reporta_ademas_como_openai():
    assert _nombres(FALSA_ANTHROPIC) == ["anthropic_api_key"]


def test_asignacion_con_valor_real_se_detecta():
    hallazgos = _nombres("OPENAI_API_KEY=" + "Zq8fK2mX9vLp4RtY7wNc")
    assert any(h.startswith("asignacion:OPENAI_API_KEY") for h in hallazgos)


@pytest.mark.parametrize("linea", [
    "OPENAI_API_KEY=",                                    # .env.example: solo el nombre
    "ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}",  # GitHub Actions
    'TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]',
    "API_KEY=<tu_clave_aqui>",
    "max_tokens: 1024",
    "modelo: claude-haiku-4-5-20251001",
    "sha256: " + "ab12" * 16,
    "#  Copia este archivo a .env y completa los valores",
    "task-based-planning-with-very-long-descriptive-name",
])
def test_no_marca_falsos_positivos_comunes(linea):
    assert cs.buscar_en_linea(linea) == []


def test_el_enmascarado_no_deja_ver_el_secreto_completo():
    m = cs.enmascarar(FALSA_ANTHROPIC)
    assert FALSA_ANTHROPIC not in m and FALSA_ANTHROPIC[:6] in m and str(len(FALSA_ANTHROPIC)) in m


def test_el_propio_script_no_se_marca_a_si_mismo():
    for n, linea in enumerate(RUTA_SCRIPT.read_text(encoding="utf-8").splitlines(), start=1):
        assert cs.buscar_en_linea(linea) == [], f"check_secrets.py línea {n} se marca a sí mismo"


# ── integración con un repositorio git temporal ──

pytestmark_git = pytest.mark.skipif(shutil.which("git") is None, reason="git no disponible")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com",
                    "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    return tmp_path


def _commit(repo: Path, nombre: str, contenido: str, mensaje: str) -> None:
    archivo = repo / nombre
    archivo.parent.mkdir(parents=True, exist_ok=True)
    archivo.write_text(contenido, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", mensaje)


@pytestmark_git
def test_repo_limpio_sale_con_0(repo, capsys):
    _commit(repo, "a.py", "print('hola')\n", "limpio")
    assert cs.main(["--repo", str(repo)]) == 0
    assert "limpio" in capsys.readouterr().out


@pytestmark_git
def test_secreto_en_el_arbol_sale_con_1_y_no_se_imprime_completo(repo, capsys):
    _commit(repo, "config con espacios/x.py", f"K = '{FALSA_ANTHROPIC}'\n", "malo")
    assert cs.main(["--repo", str(repo), "--arbol"]) == 1
    salida = capsys.readouterr().out
    assert "anthropic_api_key" in salida and "config con espacios/x.py:1" in salida
    assert FALSA_ANTHROPIC not in salida


@pytestmark_git
def test_secreto_borrado_despues_sigue_apareciendo_en_el_historial(repo, capsys):
    _commit(repo, "x.py", f"K = '{FALSO_TELEGRAM}'\n", "sube el token")
    _commit(repo, "x.py", "K = None\n", "lo borra")
    assert cs.main(["--repo", str(repo), "--arbol"]) == 0        # el árbol ya está limpio...
    capsys.readouterr()
    assert cs.main(["--repo", str(repo), "--historial"]) == 1    # ...pero el historial lo recuerda
    salida = capsys.readouterr().out
    assert "telegram_bot_token" in salida and "x.py:1" in salida
    assert FALSO_TELEGRAM not in salida


@pytestmark_git
def test_desde_limita_el_historial_a_los_commits_nuevos(repo):
    _commit(repo, "x.py", f"K = '{FALSA_OPENAI}'\n", "viejo con secreto")
    _git(repo, "tag", "base")
    _commit(repo, "y.py", "print(1)\n", "nuevo limpio")
    assert cs.main(["--repo", str(repo), "--historial"]) == 1
    assert cs.main(["--repo", str(repo), "--historial", "--desde", "base"]) == 0


@pytestmark_git
def test_archivo_env_versionado_se_marca(repo, capsys):
    _commit(repo, ".env", "ANTHROPIC_API_KEY=\n", "sube el .env vacío")
    assert cs.main(["--repo", str(repo), "--arbol"]) == 1
    assert "archivo_env_versionado" in capsys.readouterr().out


@pytestmark_git
def test_env_example_con_solo_nombres_no_se_marca(repo):
    _commit(repo, ".env.example", "ANTHROPIC_API_KEY=\nTELEGRAM_BOT_TOKEN=\n", "ejemplo")
    assert cs.main(["--repo", str(repo)]) == 0


@pytestmark_git
def test_los_binarios_se_ignoran(repo):
    (repo / "dato.bin").write_bytes(b"\0\0\0" + FALSA_ANTHROPIC.encode())
    (repo / "a.txt").write_text("hola\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "binario")
    assert cs.main(["--repo", str(repo), "--arbol"]) == 0


def test_fuera_de_un_repo_sale_con_2(tmp_path, capsys):
    assert cs.main(["--repo", str(tmp_path)]) == 2
    assert "ERROR" in capsys.readouterr().err

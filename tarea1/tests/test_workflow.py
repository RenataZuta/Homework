"""El workflow de GitHub Actions cumple lo pedido: sin secretos, compuerta de Recall@3, sin OCR, con artefacto; y el mínimo tiene sentido frente al resultado real."""
import json
from pathlib import Path

import pytest
import yaml

from rag_engine.config import cargar_config

RAIZ = Path(__file__).resolve().parents[1]
WORKFLOW = RAIZ.parent / ".github" / "workflows" / "eval.yml"
pytestmark = pytest.mark.skipif(not WORKFLOW.is_file(), reason="el repositorio no incluye .github/workflows/eval.yml en este entorno")


@pytest.fixture(scope="module")
def wf():
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def pasos(wf):
    return wf["jobs"]["recall-gate"]["steps"]


def _texto():
    return WORKFLOW.read_text(encoding="utf-8")


def test_corre_en_cada_push_y_pull_request(wf):
    disparadores = wf.get("on", wf.get(True))                    # PyYAML interpreta «on» como True
    assert "push" in disparadores and "pull_request" in disparadores


def test_no_pide_ningun_secreto_ni_variable_de_credenciales():
    t = _texto()
    assert "secrets." not in t and "${{ secrets" not in t
    for nombre in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "TELEGRAM_BOT_TOKEN", "BACKEND_INTERNAL_KEY"):
        assert nombre not in t


def test_permisos_minimos_de_solo_lectura(wf):
    assert wf["permissions"] == {"contents": "read"}


def test_instala_pytorch_cpu_con_el_indice_oficial_y_las_dependencias_livianas(pasos):
    comandos = "\n".join(p.get("run", "") for p in pasos)
    assert "pip install torch --index-url https://download.pytorch.org/whl/cpu" in comandos and "pip install -r requirements-ci.txt" in comandos
    assert comandos.index("torch") < comandos.index("requirements-ci.txt")             # PyTorch CPU ANTES que el resto


def test_cachea_pip_y_el_modelo_de_embeddings(pasos):
    usos = [p.get("uses", "") for p in pasos]
    assert any(u.startswith("actions/cache@") for u in usos)
    py = next(p for p in pasos if p.get("uses", "").startswith("actions/setup-python@"))
    assert py["with"]["cache"] == "pip" and py["with"]["python-version"] == "3.12"


def test_arma_el_indice_desde_lo_procesado_y_ejecuta_run_eval_sin_ocr(pasos):
    comandos = [p.get("run", "") for p in pasos]
    unidos = "\n".join(comandos)
    assert "python scripts/build_index.py" in unidos and "python -m evaluation.run_eval" in unidos
    assert unidos.index("build_index.py") < unidos.index("evaluation.run_eval")
    assert "run_extraction" not in unidos and "tesseract" not in unidos.lower() and "apt" not in unidos           # el OCR NO corre en CI
    assert "eval_end_to_end" not in unidos and "preguntar" not in unidos                                        # nada que llame al LLM


def test_sube_eval_results_como_artefacto_aunque_falle(pasos):
    p = next(p for p in pasos if p.get("uses", "").startswith("actions/upload-artifact@"))
    assert p["if"] == "always()" and p["with"]["path"].rstrip("/") == "tarea1/eval/results"


def test_corre_desde_tarea1_con_pythonpath(wf):
    job = wf["jobs"]["recall-gate"]
    assert job["defaults"]["run"]["working-directory"] == "tarea1" and job["env"]["PYTHONPATH"] == "src"


def test_el_texto_procesado_esta_versionado_porque_el_ci_no_hace_ocr():
    assert (RAIZ / "data" / "processed" / "ds_009_2025_ef" / "_plan_ocr.json").is_file()
    assert len(list((RAIZ / "data" / "processed" / "ds_009_2025_ef").glob("p0*.json"))) >= 75


# ── el mínimo está justificado con el resultado real ──

def test_el_minimo_de_recall_3_tiene_margen_pero_no_es_trivial():
    cfg = cargar_config(cargar_env=False)
    real = json.loads((RAIZ / "eval" / "results" / "run_eval.json").read_text(encoding="utf-8"))["recuperacion"]["recall@3"]
    minimo = cfg.get("eval.min_recall_at_3")
    una_pregunta = 1 / 21
    assert minimo <= real, "el CI fallaría hoy mismo"
    assert minimo >= real - 2 * una_pregunta and minimo > 0.5, "el mínimo es demasiado flojo: no detectaría una regresión de 2 preguntas"


def test_el_workflow_no_tiene_pasos_que_dependan_de_un_umbral_escrito_a_mano():
    assert "0.85" not in _texto() and "min-recall" not in _texto()          # el mínimo vive SOLO en config.yaml


def test_requirements_ci_no_arrastra_torch_pesado_de_mas_por_fastapi():
    lineas = (RAIZ / "requirements-ci.txt").read_text(encoding="utf-8").splitlines()
    paquetes = "\n".join(l.split("#", 1)[0] for l in lineas if l.strip() and not l.strip().startswith("#")).lower()
    assert "fastapi" in paquetes and "httpx" in paquetes
    assert "torch" not in paquetes                                       # PyTorch se instala aparte en el workflow (índice CPU), no aquí


def test_requirements_txt_no_quedo_truncado_y_trae_todo_lo_que_usa_el_proyecto():
    """Hallazgo real (Fase 13): una corrupción del disco (iCloud) truncó requirements.txt a 26 líneas, cortando a media
    palabra el comentario de tzdata y borrando streamlit/pandas/fastapi/uvicorn/httpx/matplotlib SIN que ningún commit
    ni prueba lo notara. Esta prueba existe para que un accidente así nunca vuelva a pasar inadvertido."""
    texto = (RAIZ / "requirements.txt").read_text(encoding="utf-8")
    assert texto.rstrip().endswith(")")                                   # el archivo termina en un comentario completo, no a media palabra
    lineas = [l.split("==")[0].strip().lower() for l in texto.splitlines() if l.strip() and not l.strip().startswith("#")]
    esperados = {"pyyaml", "python-dotenv", "pymupdf", "pillow", "pytesseract", "numpy", "sentence-transformers", "chromadb",
                "openai", "requests", "anthropic", "tzdata", "streamlit", "pandas", "fastapi", "uvicorn", "httpx", "matplotlib"}
    assert esperados <= set(lineas), f"faltan en requirements.txt: {esperados - set(lineas)}"

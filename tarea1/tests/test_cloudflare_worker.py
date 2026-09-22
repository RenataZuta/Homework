"""Revisión estática del Worker de Cloudflare y del Dockerfile: NO se pudo instalar node/wrangler/docker en este entorno
(ver PROGRESO.md, Fase 11), así que estas pruebas leen los archivos como texto y verifican invariantes concretas —no
sustituyen a `wrangler dev`/`docker build`, que la persona debe correr antes de desplegar."""
import re
from pathlib import Path

import pytest

from rag_engine.config import cargar_config

RAIZ = Path(__file__).resolve().parents[1]
WORKER = RAIZ / "cloudflare_worker" / "src" / "index.js"
WRANGLER = RAIZ / "cloudflare_worker" / "wrangler.toml"
DOCKERFILE = RAIZ / "Dockerfile"
pytestmark = pytest.mark.skipif(not WORKER.is_file(), reason="cloudflare_worker/ no está en este checkout")

BASE = cargar_config(cargar_env=False)


@pytest.fixture(scope="module")
def js():
    return WORKER.read_text(encoding="utf-8")


def test_el_mensaje_de_despertando_coincide_letra_por_letra_con_config_yaml(js):
    m = re.search(r'const MENSAJE_DESPERTANDO = "((?:[^"\\]|\\.)*)"', js)
    assert m, "no se encontró la constante MENSAJE_DESPERTANDO en el Worker"
    assert m.group(1) == BASE.get("mensajes.bot.backend_despertando")


def test_valida_el_secreto_de_telegram_antes_de_reenviar_nada():
    js_texto = WORKER.read_text(encoding="utf-8")
    pos_check = js_texto.index("X-Telegram-Bot-Api-Secret-Token")
    pos_forward = js_texto.index("ctx.waitUntil")
    assert pos_check < pos_forward, "el Worker debe validar el secreto ANTES de reenviar al backend"
    assert "TELEGRAM_WEBHOOK_SECRET" in js_texto and "403" in js_texto


def test_responde_200_de_inmediato_sin_esperar_al_backend(js):
    pos_ok = js.index('new Response("OK"')
    pos_wait_until = js.index("ctx.waitUntil")
    assert pos_wait_until < pos_ok, "ctx.waitUntil debe dispararse SIN esperarlo (sin await) antes del 200 a Telegram"
    assert "await ctx.waitUntil" not in js


def test_reenvia_con_la_clave_interna_al_backend_configurado_por_secreto(js):
    assert "env.BACKEND_URL" in js and "env.BACKEND_INTERNAL_KEY" in js and "X-Internal-Key" in js
    assert "/telegram/webhook" not in js.split("BACKEND_URL")[0]           # la ruta se arma con la URL del secreto, no está fija


def test_maneja_errores_del_backend_sin_dejar_una_promesa_sin_capturar(js):
    assert js.count("try {") >= 3 and js.count("catch") >= 3


def test_el_token_del_bot_solo_se_usa_para_avisar_que_esta_despertando_no_para_responder_la_pregunta(js):
    usos = [m.start() for m in re.finditer(r"TELEGRAM_BOT_TOKEN", js)]
    assert usos, "si no se usa, sobra declararlo como secreto"
    assert "sendMessage" in js and "avisarDespertando" in js


def test_no_hay_secretos_ni_urls_reales_escritos_en_el_worker(js):
    assert not re.search(r"AIza[0-9A-Za-z_\-]{20,}", js) and not re.search(r"sk-[A-Za-z0-9_\-]{20,}", js)
    assert not re.search(r"\d{8,10}:[A-Za-z0-9_\-]{30,}", js)             # nada que parezca un token real de Telegram
    assert not re.search(r"https://[a-z0-9-]+\.(workers\.dev|onrender\.com)", js)   # ninguna URL real de despliegue, solo `env.*`


def test_wrangler_toml_tiene_los_campos_minimos_y_ningun_secreto():
    t = WRANGLER.read_text(encoding="utf-8")
    assert 'name = "contrataciones-telegram-webhook"' in t and 'main = "src/index.js"' in t
    assert re.search(r'(?m)^compatibility_date = "\d{4}-\d{2}-\d{2}"', t)
    lineas_de_codigo = [l for l in t.splitlines() if l.strip() and not l.strip().startswith("#")]
    for nombre in ("TELEGRAM_WEBHOOK_SECRET", "BACKEND_INTERNAL_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USER_IDS"):
        assert not any(re.match(rf"{nombre}\s*=", l) for l in lineas_de_codigo), f"{nombre} no debe asignarse en wrangler.toml (usa wrangler secret put)"
    assert "[vars]" not in t                                              # ningún valor (sensible o no) vive aquí: todo es secreto


# ── Dockerfile ──

@pytest.fixture(scope="module")
def dockerfile():
    return DOCKERFILE.read_text(encoding="utf-8")


def test_el_dockerfile_construye_el_indice_y_descarga_el_modelo_en_el_build_no_al_arrancar(dockerfile):
    assert "scripts/build_index.py" in dockerfile and "SentenceTransformer" in dockerfile
    assert re.search(r"^CMD ", dockerfile, re.M), "el arranque (CMD) no debe reconstruir nada, solo levantar uvicorn"
    cmd = next(l for l in dockerfile.splitlines() if l.startswith("CMD "))
    assert "build_index" not in cmd and "SentenceTransformer" not in cmd


def test_el_dockerfile_escucha_en_el_puerto_que_fija_render(dockerfile):
    cmd = next(l for l in dockerfile.splitlines() if l.startswith("CMD "))
    assert "${PORT" in cmd and "0.0.0.0" in cmd


def test_el_dockerfile_no_incluye_pdfs_ocr_ni_el_cliente_de_anthropic(dockerfile):
    assert "data/raw" not in dockerfile and "pytesseract" not in dockerfile.lower()
    assert "requirements-backend.txt" in dockerfile and "requirements.txt " not in dockerfile


def test_el_dockerfile_no_corre_como_root(dockerfile):
    assert "USER app" in dockerfile


def test_requirements_backend_no_trae_anthropic_ni_paquetes_de_ocr_o_graficos():
    lineas = (RAIZ / "requirements-backend.txt").read_text(encoding="utf-8").splitlines()
    r = "\n".join(l for l in lineas if l.strip() and not l.strip().startswith("#")).lower()
    for paquete in ("anthropic", "pymupdf", "pillow", "pytesseract", "matplotlib", "openai", "streamlit"):
        assert paquete not in r
    for paquete in ("fastapi", "uvicorn", "chromadb", "sentence-transformers", "pyyaml", "requests"):
        assert paquete in r

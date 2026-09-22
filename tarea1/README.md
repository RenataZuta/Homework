# Tarea 1 — RAG normativo de contrataciones públicas del Perú

Asistente que responde preguntas sobre la **Ley 32069**, su **Reglamento (DS 009-2025-EF, subconjunto con OCR)** y la **modificatoria DS 001-2026-EF**,
citando documento y página. Repositorio: `RenataZuta/Homework`, rama `tarea1-rag`, carpeta `tarea1/`.

> **Estado:** en desarrollo por fases; el estado exacto y las decisiones están en [`PROGRESO.md`](PROGRESO.md). Este README se completa en la Fase 13
> (diagrama Mermaid del pipeline, pasos de instalación en Windows PowerShell, notas del video). Lo que ya está aquí describe **proveedores, costos, límites y privacidad**.

## Puesta en marcha en Windows (PowerShell)

> Los pasos se probaron con sus equivalentes en macOS (entorno virtual limpio, instalación desde `requirements.txt`, tests y apertura de la app). **Los comandos de PowerShell no se pudieron
> ejecutar en la máquina de desarrollo** (macOS): si alguno falla, revisa primero rutas y versiones, y avísame.

**Requisitos:** Windows 10/11, **Python 3.12** (`py -3.12 --version`; con Python 3.13+ pueden no existir ruedas de PyTorch o ChromaDB), Git y ~3 GB libres (PyTorch CPU + modelo de embeddings).

```powershell
# 1. Clonar y entrar a la carpeta del proyecto
git clone https://github.com/RenataZuta/Homework.git
cd Homework
git checkout tarea1-rag
cd tarea1

# 2. Entorno virtual con Python 3.12
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
#   Si PowerShell bloquea el script:  Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
python -m pip install --upgrade pip

# 3. PyTorch SOLO CPU, ANTES del resto (evita bajar la versión con CUDA, ~2 GB)
pip install torch --index-url https://download.pytorch.org/whl/cpu

# 4. Dependencias del proyecto
pip install -r requirements.txt

# 5. Credenciales: copia la plantilla y completa GEMINI_API_KEY (clave gratuita: https://aistudio.google.com/apikey)
Copy-Item .env.example .env
python scripts\set_env_key.py GEMINI_API_KEY      # pide la clave con entrada oculta y la guarda en .env (no la muestra)
python scripts\set_env_key.py --estado            # comprueba qué variables están definidas (nunca muestra valores)
```

### Tesseract (solo si vas a repetir la extracción con OCR)
`data\processed\` ya viene en el repositorio, así que **la app no necesita Tesseract**. Para rehacer el OCR del Reglamento (75 páginas escaneadas):

1. Instala Tesseract 5 para Windows (compilación de UB Mannheim, <https://github.com/UB-Mannheim/tesseract/wiki>) y marca el idioma **Spanish** en el instalador.
2. Comprueba el idioma: `& "C:\Program Files\Tesseract-OCR\tesseract.exe" --list-langs` debe listar `spa`.
3. En `.env` escribe la ruta: `TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe`

### Orden de ejecución
**Ruta rápida (lo mínimo para usar la app):** el índice no se versiona (se regenera), así que se construye una vez. La primera vez descarga el modelo de embeddings (~470 MB).

```powershell
python scripts\build_index.py            # idempotente y reanudable (Ctrl+C es seguro)
streamlit run app.py                      # abre http://localhost:8501; NO reconstruye el índice
```

**Ruta completa (reproducir todo):**

```powershell
$env:PYTHONPATH = "src"                   # para los módulos de src\evaluation (solo en esta sesión)
python scripts\download_pdfs.py           # 1. descarga los PDFs oficiales y escribe data\raw\MANIFEST.json
python scripts\run_extraction.py          # 2. PDF -> una entrada JSON por página (OCR solo en el subconjunto configurado)
python scripts\validate_eval_set.py       # 3. evaluación previa: el set apunta a páginas procesadas
python -m evaluation.select_local_model   #    (opcional) compara modelos de embeddings locales: descarga varios candidatos, ~6 GB
python -m evaluation.compare_chunking     #    (opcional) compara configuraciones de troceado
python scripts\build_index.py             # 4. índice persistente en data\index
python -m evaluation.run_eval             # 5. Recall@k y abstención, sin llamar al LLM (código de salida 1 si Recall@3 < eval.min_recall_at_3)
python -m evaluation.eval_end_to_end --umbral 0   #    evaluación con el LLM real (usa la cuota gratuita; ~27 llamadas)
python -m evaluation.sweep_threshold_e2e  #    umbral a partir de esa evaluación
streamlit run app.py                      # 6. interfaz
```

Los scripts se ejecutan **desde la carpeta `tarea1`**. En Linux/macOS: `source .venv/bin/activate`, `cp .env.example .env` y `PYTHONPATH=src python -m evaluation.run_eval`.

### Pruebas y verificación de la arquitectura
```powershell
pip install pytest
python -m pytest                                          # toda la suite (~30 s, sin red ni claves)
python scripts\check_secrets.py                           # sin claves ni tokens en el árbol ni en el historial de git
# El motor NO importa librerías de interfaz: debe dar 0 coincidencias
Select-String -Path src\rag_engine\*.py,src\rag_engine\*\*.py -Pattern "streamlit|telegram|fastapi|flask|gradio"
```
Equivalente en Linux/CI: `grep -rnE "streamlit|telegram|fastapi|flask|gradio" src/rag_engine` (0 coincidencias).

### La interfaz (`app.py`)
Carga el índice existente **una sola vez** (`@st.cache_resource`) y **nunca lo reconstruye** al iniciar; si falta, muestra un error con el comando para construirlo. Solo llama a `MotorRAG.responder(pregunta)`.
Pestañas: **Consulta** (respuesta, indicador de abstención, avisos de versión, fragmentos citados con documento/página/similitud/texto, y costo, tokens y latencia de la consulta),
**Calidad de extracción**, **Evaluación** (Recall@k, abstención, barrido de umbral, embeddings, troceado, BM25) y **Costos** (agregado de `logs/llm_calls.jsonl`). Los errores salen con `st.error`.

## Proveedores y costo (decisión del 2026-09-21: sin pagos adicionales)

| Etapa | Proveedor activo | Costo real | Cómo cambiarlo |
|---|---|---|---|
| Generación (LLM) | **Google Gemini `gemini-3.5-flash-lite`, capa gratuita** | **USD 0** | `llm.provider` y `llm.proveedores.*` en `config.yaml` |
| Embeddings del índice | **Local** `intfloat/multilingual-e5-small` (CPU) | USD 0 | `embeddings.proveedor` |
| Comparación de embeddings por API | OpenAI `text-embedding-3-small` y Gemini `gemini-embedding-2` | ver más abajo | `embeddings.comparar` |

El cliente de **Anthropic se conserva pero no se usa** (`llm.provider: anthropic` exigiría `llm.nivel: pago`; la configuración lo valida).

### Costo real y costo de referencia
Cada llamada al LLM se registra en `logs/llm_calls.jsonl` con **`costo_usd_real`** (lo que se cobra: 0 en la capa gratuita) y **`costo_usd_referencia`**
(lo que costaría con el precio de **pago** del modelo, de `pricing.yaml`, con fuente y fecha de verificación). Sirve para dimensionar el gasto si algún
día se pasara a un plan de pago. Los precios se conservan por **ventanas horarias**
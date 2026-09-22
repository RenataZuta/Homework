# Tarea 1 — RAG normativo de contrataciones públicas del Perú

[![eval](https://github.com/RenataZuta/Homework/actions/workflows/eval.yml/badge.svg?branch=tarea1-rag)](https://github.com/RenataZuta/Homework/actions/workflows/eval.yml)

Asistente que responde preguntas sobre la **Ley 32069**, su **Reglamento (DS 009-2025-EF, subconjunto con OCR)** y la **modificatoria DS 001-2026-EF**,
citando documento y página. Repositorio: `RenataZuta/Homework`, rama `tarea1-rag`, carpeta `tarea1/`.

> **Estado:** en desarrollo por fases; el estado exacto y las decisiones están en [`PROGRESO.md`](PROGRESO.md). Este README se completa en la Fase 13
> (diagrama Mermaid del pipeline, pasos de instalación en Windows PowerShell, notas del video). Lo que ya está aquí describe **proveedores, costos, límites y privacidad**.

## Bot 24/7 con Cloudflare Worker + backend (Fase 11)

Un Worker de Cloudflare **no puede** ejecutar el motor: su runtime no corre `sentence-transformers` (necesita PyTorch) ni ChromaDB.
Por eso hay dos piezas, no una:

```mermaid
flowchart LR
    T[Usuario en Telegram] --> W["Worker de Cloudflare<br/>(cloudflare_worker/)<br/>valida el secreto, responde 200<br/>de inmediato, reenvía con ctx.waitUntil"]
    W -- "X-Internal-Key" --> B["Backend FastAPI<br/>(interfaces/api_server.py)<br/>SIEMPRE encendido: tiene el motor"]
    B -- responder&#40;pregunta&#41; --> M[rag_engine.engine]
    B -- sendMessage --> T
    W -. "si el backend tarda<br/>(arranque en frío)" .-> T
```

- **Worker** (`cloudflare_worker/`): valida `X-Telegram-Bot-Api-Secret-Token`, responde `200` a Telegram de inmediato (para que no
  reintente) y reenvía el update al backend con `ctx.waitUntil(...)`. Si el backend no contesta a tiempo (el plan gratuito de
  Render duerme tras 15 min sin tráfico y tarda en despertar), el propio Worker le avisa al usuario y reintenta una vez más.
- **Backend** (`interfaces/api_server.py`, FastAPI): `GET /health` sin autenticación; `POST /telegram/webhook` exige la cabecera
  `X-Internal-Key` (un secreto que solo conocen el Worker y el backend — **no** es el token de Telegram) y procesa el update
  con los mismos `interfaces/telegram_handlers` de la Fase 10, en segundo plano.
- **Host elegido: Render, plan gratuito.** Verificado el 2026-09-22: sin tarjeta, admite Docker, dan 750 horas gratis al mes.
  Duerme tras 15 min sin tráfico y tarda ~1 minuto en despertar (documentado oficialmente); el Worker está pensado para ese
  arranque en frío, no para evitarlo. **Se descartó Hugging Face Spaces con Docker**: su documentación oficial dice ahora que
  crear un Space Docker en una cuenta personal **requiere el plan PRO de pago** (antes era gratis); Google Cloud Run se
  descartó porque exige asociar una tarjeta a una cuenta de facturación. **Riesgo sin confirmar:** no encontré con una fuente
  oficial la RAM exacta del plan gratuito de Render; si el modelo + el índice no caben, hay que achicar la imagen o cambiar de host.
- **El índice y el modelo se preparan en el `Dockerfile` durante el `build`, nunca al arrancar** (`RUN` descarga el modelo y
  construye el índice a partir de `data/processed/`, que sí está en git; `data/index/` no lo está, igual que en el CI de la
  Fase 9). `requirements-backend.txt` es más chico que `requirements.txt`: sin OCR, sin gráficos, sin el cliente de Anthropic.
- **Desviación del plan original:** el Worker usa un 4.º secreto, `TELEGRAM_BOT_TOKEN` (el plan solo mencionaba
  `TELEGRAM_WEBHOOK_SECRET`, `BACKEND_URL` y `BACKEND_INTERNAL_KEY`). Sin él, el Worker no podría enviar el aviso de «me estoy
  despertando» cuando el backend tarda: esa llamada a Telegram la hace directamente el propio Worker.
- **No se pudo probar de punta a punta ni ejecutar `docker build`/`wrangler deploy`**: esta máquina de desarrollo no tiene
  `docker`, `node` ni `wrangler` instalados. El código se revisó con pruebas estáticas (`tests/test_cloudflare_worker.py`, que
  lee el `Dockerfile` y el Worker como texto) y con `interfaces/api_server.py` probado de verdad (`fastapi.testclient`,
  711 pruebas en total). Los pasos [MANUAL] de cuentas y despliegue están en `docs/despliegue_backend.md`.

## Despliegue público de la app (Fase 12)

**Estado: código y pruebas listos; el despliegue real es un paso [MANUAL], ver `docs/despliegue_app_publica.md`.** Cuando la
persona lo haga, el enlace público queda aquí.

- **Plataforma: Streamlit Community Cloud** (gratis, sin tarjeta). Se descartó Hugging Face Spaces por el mismo motivo que en
  la Fase 11 (ahora exige plan PRO para Spaces con cómputo en cuenta personal).
- **Memoria medida en local (dato real):** cargar el modelo de embeddings local ya usa **883 MB** de RSS, antes de sumar el
  propio servidor de Streamlit. La cifra que más se cita para el límite gratuito de Streamlit Cloud es 1 GB (sin confirmación
  oficial textual hoy): es un riesgo real. La salida ya está lista y probada: cambiar `embeddings.proveedor: gemini` en
  `config.yaml` quita PyTorch y el modelo local por completo.
- **El índice va en el repositorio** (`data/index/`, 11 MB): la app pública no tiene un paso de "build" propio, así que
  nunca puede reconstruirlo al iniciar sesión (regla no negociable de la fase).
- **Protección de costo (la app usa la clave de la persona):** `deploy.topes.consultas_por_sesion` y
  `deploy.topes.consultas_globales_por_dia` en `config.yaml`. Se revisan ANTES de llamar al motor (cero costo si ya se
  alcanzaron); el tope de sesión usa el estado de la sesión de Streamlit, el global lee `logs/llm_calls.jsonl` de hoy (en
  `deploy.zona_horaria`) — sin base de datos nueva. Solo cuentan las llamadas que de verdad llegaron al LLM: una abstención
  por umbral no gasta cupo.
- La clave (`GEMINI_API_KEY`) va en los *Secrets* de Streamlit Cloud, nunca en el repositorio.

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

## Integración continua: compuerta de Recall@3 (Fase 9)

`.github/workflows/eval.yml` corre en cada push y pull request que toque `tarea1/`: instala Python 3.12 con caché de pip, **PyTorch solo CPU** desde el índice oficial de CPU y las dependencias livianas
(`requirements-ci.txt`), cachea el modelo de embeddings, ejecuta las pruebas, **arma el índice a partir de `data/processed/`** (el OCR **no** corre en CI: el texto procesado está versionado) y ejecuta
`python -m evaluation.run_eval`, que **falla (código 1) si Recall@3 < `eval.min_recall_at_3`** de `config.yaml`. Sube `eval/results/` como artefacto aunque falle. **No requiere ningún secreto**: no llama a ningún LLM ni a ninguna API
(hay una prueba que lo verifica).

**Por qué 0,85.** El Recall@3 real es 0,905 (19 de 21 preguntas). Con 21 preguntas cada una pesa 0,048: un mínimo de 0,85 exige 18 de 21, es decir, **tolera una pregunta más fallida** (17/21 = 0,810 falla, 18/21 = 0,857 pasa) y detecta
regresiones reales del troceado, del modelo o del índice sin dar falsas alarmas por una diferencia numérica mínima entre entornos. Es provisional hasta validar el set (Fase 3). Cambiarlo es editar una línea de `config.yaml`.

Se probó localmente en un clon limpio con un entorno virtual nuevo, sin `.env`, Tesseract ni Streamlit (610 pruebas, `build_index`, `run_eval` en verde). La corrida roja demostrada en GitHub está en `docs/ci_rojo.md` cuando se ejecute.

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
día se pasara a un plan de pago. Los precios se conservan por **ventanas horarias** (`pricing.yaml`, `llm/pricing.py`): hoy Google publica un único precio por modelo,
y la estructura está probada con una tabla ficticia de horas pico y valle. Las respuestas que salen de la caché de la evaluación **no** son llamadas y no se registran.

### Conseguir y guardar la clave (gratis, sin tarjeta)
1. Crea una clave en **Google AI Studio**: <https://aistudio.google.com/apikey>.
2. Guárdala **sin mostrarla** (pide el valor con entrada oculta y escribe `tarea1/.env`, que git ignora):
   ```
   python scripts/set_env_key.py GEMINI_API_KEY
   python scripts/set_env_key.py --estado        # qué variables están definidas (nunca muestra valores)
   ```
Nunca pegues una clave en el chat, en `config.yaml` ni en el repositorio. Si se filtra, revócala en AI Studio y crea otra.

## Límites de uso: throttle, reintentos y cuota

La capa gratuita tiene límites por proyecto (RPM, TPM, RPD). Los números **no figuran en la documentación pública**: se consultan en
<https://aistudio.google.com/rate-limit>. El proyecto los respeta así (`llm.limites` y `embeddings.limites` en `config.yaml`):

- **Throttle por RPM** (`rpm`): ventana deslizante de 60 s; nunca envía más de `rpm` peticiones por minuto. El valor por defecto (10 para el LLM, 20 para embeddings) es un
  **valor de diseño conservador, no el límite de Google**: ajústalo a lo que muestre tu AI Studio.
- **Reintentos con backoff exponencial** ante 429 por tasa, 5xx y errores de red: esperas de 4, 8, 16, 32 s (tope 60 s) con jitter, respetando el `retryDelay` que sugiera Google.
  **No** se reintentan clave inválida, formato malformado, bloqueo de contenido ni la **cuota diaria** agotada (esperar segundos no sirve).
- **Cuota agotada = error estructurado.** Si el límite persiste tras los reintentos, o se agota la cuota diaria, `responder()` devuelve `respuesta=None`, `error` con
  el mensaje y `error_tipo="cuota_agotada"`. **Nunca** una respuesta normal ni una abstención disfrazada. La interfaz muestra `mensajes.error_cuota`.
- **Caché de la evaluación de punta a punta** (`eval.cache_llm`, carpeta `eval/cache_llm/`, ignorada por git): la clave es el hash de proveedor, modelo, temperatura, `max_tokens`,
  prompt de sistema, prompt de usuario (pregunta + fragmentos) y esquema. Repetir la evaluación no repite llamadas ni gasta cuota; si cambia cualquiera de esos elementos, se llama de nuevo.
  Si la cuota se agota a mitad de la evaluación, se corta con un informe «EVALUACIÓN INCOMPLETA», y al repetirla continúa donde quedó. `--sin-cache` fuerza llamadas reales.

## BM25 frente a búsqueda semántica (Fase 8)

`src/rag_engine/retrieval/` tiene tres modos, elegibles con `retrieval.modo`: `semantico` (embeddings, coseno exacto), `bm25` (léxico, implementado aquí con minúsculas, sin tildes, stopwords y,
opcionalmente, un stemmer ligero de plurales) e `hibrido` (Reciprocal Rank Fusion de ambas listas). Los tres trabajan sobre **los mismos 1674 fragmentos**. Comparación completa, por pregunta y con
la lista de dónde gana cada método: [`eval/results/retrievers_comparacion.md`](eval/results/retrievers_comparacion.md) (`PYTHONPATH=src python -m evaluation.compare_retrievers`).

Set de evaluación (21 preguntas del dominio; **PROVISIONAL** hasta validar el set):

| Variante | R@1 | R@3 | R@5 | MRR | R@3 coloquial | R@3 jurídico | R@3 modificatoria |
|---|---|---|---|---|---|---|---|
| **semántico** | **0,762** | **0,905** | **0,905** | **0,825** | **0,818** | 1,000 | 0,800 |
| BM25 | 0,571 | 0,714 | 0,762 | 0,647 | 0,455 | 1,000 | 0,800 |
| BM25 + stemming | 0,619 | 0,762 | 0,810 | 0,694 | 0,545 | 1,000 | 0,800 |
| híbrido (RRF) | 0,714 | 0,810 | 0,810 | 0,754 | 0,636 | 1,000 | 0,800 |
| híbrido (RRF) + stemming | 0,714 | 0,905 | 0,905 | 0,802 | 0,818 | 1,000 | 0,800 |

Sonda sintética de **números de artículo** (96 consultas «artículo N de la Ley», generadas a partir del propio índice; no es parte del set porque el set no tiene ninguna pregunta con cifras):

| Variante | R@1 | R@3 | R@5 |
|---|---|---|---|
| semántico | 0,271 | 0,448 | 0,542 |
| **BM25** (con encabezado) | **0,521** | **0,844** | **0,938** |
| BM25 sin encabezado | 0,302 | 0,698 | 0,833 |
| híbrido (RRF) | 0,500 | 0,771 | 0,823 |

**Qué gana en las preguntas coloquiales, y por qué.** Gana el **semántico** (R@3 0,818 frente a 0,455 de BM25, 0,545 con stemming). La persona que pregunta no usa el vocabulario de la ley: «¿Puedo venderle al Estado si mi empresa
recién abrió?» (q01), «si la entidad se demora en pagarme…» (q02) o «cuánto me pueden cobrar por cada día que entrego tarde» (q10) hablan de *proveedor*, *inscripción*, *intereses legales* y *penalidad por mora* con otras palabras.
BM25 solo puntúa términos compartidos con el fragmento, así que no encuentra en el top-3 ninguna de las cinco preguntas que el semántico acierta y BM25 no (q01, q02, q03, q09, q10); el embedding sí relaciona significados. En las
preguntas de estilo jurídico ambos aciertan todo (R@3 1,000): el vocabulario ya coincide.

**Dónde acierta BM25.** (1) En la **búsqueda por número de artículo** y términos exactos: en la sonda, R@3 0,844 frente a 0,448 del semántico, porque «114» o «artículo 66» son términos exactos y los embeddings casi no
distinguen cifras; indexar el encabezado («Artículo 66. Adelantos») pesa mucho (sin él, 0,698). (2) En **q07** («ofertas con el **mismo puntaje**»): BM25 pone el fragmento correcto en el puesto 1 y el semántico en el 166, porque
la regla de desempate usa literalmente «puntaje» mientras que la pregunta coloquial se parece más a otros fragmentos sobre puntajes. q04 («hasta qué monto me pueden comprar sin hacer una licitación», que la ley llama *contratos
menores*) falla en ambos (puestos 51 y 58): es la brecha de vocabulario que ninguno cierra.

**Híbrido.** Con RRF y stemming iguala al semántico en R@3 y R@5 del set (0,905) pero con menor R@1 y MRR, y mejora mucho la búsqueda por número de artículo (R@3 0,771). **No recupera q07** aunque BM25 la tenga primera, porque RRF solo mira posiciones
y el fragmento está fuera de los primeros 50 del semántico. No es un problema de ajuste: con 100 o 200 candidatos y `rrf_k` 10 o 60 el resultado del set no cambia (q04 y q07 siguen fallando).

**Decisión: `retrieval.modo: semantico`.** Es el mejor en R@1, R@3, R@5 y MRR sobre el set, y también de punta a punta con el LLM real (evaluación con umbral 0, una corrida de cada modo): **semántico 18/21 respondidas con cita correcta y 1
respuesta indebida; híbrido con stemming 17/21 y 2 indebidas** (`eval/results/e2e_hibrido_stem_umbral_0.000.md`). Con 21 preguntas y una sola corrida de un LLM con temperatura por defecto, una pregunta de diferencia no es concluyente; lo que sí
es claro es que el híbrido **no mejora** el set. Si el uso esperado incluye muchas consultas por número de artículo, `retrieval.modo: hibrido` con `retrieval.bm25.stemming: true` es la opción respaldada por la sonda
(`python -m evaluation.compare_retrievers --aplicar hibrido_rrf_stem`).

**Umbral de abstención con BM25 o híbrido.** Los puntajes de BM25 y de RRF **no son cosenos**, así que el umbral **nunca** se compara con ellos: cada fragmento devuelto conserva su **coseno exacto** con la consulta (`similitud`) y la compuerta del
motor abstiene según el **mayor coseno entre los recuperados**, sea cual sea el modo que ordenó. Por eso el umbral calibrado (0,835) sigue significando lo mismo en los tres modos (tests: la compuerta compara cosenos, no
puntajes; sin coincidencias léxicas BM25 devuelve vacío y el motor se abstiene sin llamar al LLM).

## Recuperación exacta

`retrieval.busqueda: exacta` calcula el coseno contra todos los vectores del índice (menos de 1 ms con ~1 700 fragmentos). La búsqueda aproximada HNSW de Chroma daba resultados
distintos entre ejecuciones en este corpus (para la pregunta `o01`, 2 de 3 procesos), lo que hacía irreproducibles las respuestas; la exacta es determinista y el Recall no cambia.

## Privacidad

> **En la capa gratuita, Google puede usar el contenido enviado para mejorar sus productos.** La página oficial de precios lo indica en la fila
> «Used to improve our products» (Sí en el nivel gratuito, No en el de pago; verificado el 2026-09-21: <https://ai.google.dev/gemini-api/docs/pricing>).

Por eso el motor **solo envía al proveedor la pregunta y fragmentos de normas públicas** (Ley, Reglamento y modificatoria, publicados oficialmente), dentro de las plantillas de
`config.yaml` (`prompts.sistema` y `prompts.usuario`). No envía claves, variables de entorno, rutas locales ni datos de otros usuarios; hay un test que lo verifica
(`test_al_proveedor_solo_llegan_la_pregunta_y_fragmentos_de_normas`). Aun así:

- **No escribas datos personales ni información confidencial en las preguntas**; la aplicación muestra este aviso (`mensajes.aviso_privacidad`).
- Si necesitas privacidad total, usa el nivel de pago (`llm.nivel: pago`, en el que Google indica que no usa el contenido para mejorar sus productos) o un proveedor local.
- Los embeddings del índice se calculan **localmente**: el texto de las normas y las preguntas no salen de tu máquina para la recuperación. Solo la generación, y la comparación
  opcional de embeddings por API (que envía fragmentos de normas públicas), usan la red.

## Embeddings por API: desviación respecto al plan original

El plan comparaba el modelo local con `text-embedding-3-small` de OpenAI. Como **no se cargará crédito**, se aplicó esta regla (`evaluation/compare_embeddings.py`):

1. Se intenta OpenAI **sin cargar crédito**. Si la API responde `insufficient_quota` (cuenta sin saldo), la fila queda **«no ejecutada por costo»**, sin cifras inventadas.
   Sin `OPENAI_API_KEY`, la fila queda «pendiente».
2. Como segunda implementación por API se agregó **`gemini-embedding-2`** (capa gratuita «Free of charge», verificado el 2026-09-21; el preview `gemini-embedding-2-preview` se retiró el 2026-08-10),
   de 768 dimensiones (la guía recomienda 768, 1536 o 3072). Este modelo no usa `task_type`: la tarea va en el texto con las plantillas de la guía oficial
   (`task: search result | query: …` y `title: none | text: …`, en `config.yaml`).
3. **Cuota gratuita: 1000 textos por día y por modelo** (cada texto cuenta; medido en la respuesta 429 de Google). El corpus tiene 1674 fragmentos, así que la fila de Gemini se
   completa en **dos días**: `compare_embeddings.py` conserva el índice de los modelos por API y **reanuda** donde quedó al volver a ejecutarlo.
4. Su respuesta **no informa tokens**, así que la fila lo declara («no informado por la API») en vez de estimar un costo.

Resultados: [`eval/results/embeddings_comparacion.md`](eval/results/embeddings_comparacion.md). Todo dato provisional se marca hasta validar el set de evaluación (Fase 3).

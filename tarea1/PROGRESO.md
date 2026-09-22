# PROGRESO — Tarea 1: RAG normativo de contrataciones públicas

> Archivo de retoma: si se pierde el contexto, continuar desde la primera fase sin `[x]`. Leyenda: `[x]` hecha y verificada · `[~]` trabajo técnico hecho, **falta confirmación `[MANUAL]`** de la persona.
> Issue: https://github.com/d2cml-ai/Data-Science-Python/issues/187 · Fecha límite: **miércoles 23-sep-2026**.
> Rama de trabajo: `tarea1-rag` · Repo: `RenataZuta/Homework` (público) · Carpeta: `tarea1/`.

## Fases

- [x] **Fase 0** — Preparación: estructura, `.gitignore`, `.env.example`, `config.yaml`, `config.py`, `check_secrets.py`
- [x] **Fase 1** — Descarga de PDFs oficiales + `MANIFEST.json`
- [x] **Fase 2** — Extracción por página, OCR (75 págs del DS 009-2025-EF), limpieza, reporte de calidad (revisión manual confirmada por la persona el 2026-09-21)
- [~] **Fase 3** — Set de evaluación (`eval/preguntas.csv`) `[MANUAL pendiente: validar CADA paginas_esperadas con docs/eval_revision_manual.md; no empezar la Fase 4 hasta confirmarlo]`
- [x] **Fase 4** — Chunking, embeddings, índice idempotente y reanudable (técnica completa; las **métricas de Recall son PROVISIONALES** hasta que se valide el set de la Fase 3)
- [x] **Fase 5** — Motor RAG: umbral, versiones, costo (llamadas reales con `gemini-3.5-flash-lite` verificadas el 2026-09-21; las métricas son **PROVISIONALES** hasta validar el set de la Fase 3)
- [~] **Fase 6** — Evaluación y comparación de embeddings local vs API `[pendiente: repetir mañana `PYTHONPATH=src python -m evaluation.compare_embeddings` (Gemini: 960/1674 fragmentos indexados, la cuota gratuita es de 1000 textos/día); OPENAI_API_KEY opcional]` (`run_eval` y la fila local están medidos)
- [x] **Fase 7** — Interfaz Streamlit (`app.py`; probada sin navegador con `AppTest` y abierta en un venv limpio; **no se revisó visualmente en un navegador** ni se ejecutó PowerShell, ver hallazgos 33-35)
- [x] **Fase 8** — Innovación A: BM25 vs semántica (modo final: `semantico`, con evidencia; `bm25` e `hibrido` disponibles)
- [x] **Fase 9** — Innovación B: GitHub Actions con umbral de Recall@3 (verde y rojo demostrados en GitHub, ver «Auditoría final»; `[MANUAL: decidir si/cuándo fusionar tarea1-rag a main]`)
- [~] **Fase 10** — Innovación C: bot de Telegram `[MANUAL pendiente: crea el bot con @BotFather y pon TELEGRAM_BOT_TOKEN y TELEGRAM_ALLOWED_USER_IDS en tu .env; ver docs/telegram_bot.md]` (código y pruebas completos, sin probar con Telegram real)
- [~] **Fase 11** — Innovación D: bot 24/7 con Cloudflare Worker `[MANUAL pendiente: cuentas de Render y Cloudflare, wrangler login/deploy, cargar secretos, prueba con la laptop apagada; ver docs/despliegue_backend.md]` (código, Dockerfile y Worker completos; no se pudo compilar ni desplegar en este entorno: sin docker/node/wrangler)
- [~] **Fase 12** — Innovación E: despliegue público de la app `[MANUAL pendiente: crear la app en share.streamlit.io, cargar GEMINI_API_KEY en sus secrets, verificar y pasarme la URL; ver docs/despliegue_app_publica.md]` (topes de gasto activos y probados; índice versionado; sin desplegar de verdad)
- [x] **Fase 13** — Cierre: README, notas de video, auditoría final, costo real

Tarea 2 (`tarea2/`): pendiente, se hará después; importará `rag_engine`.

## Entorno de desarrollo (medido el 2026-09-21)

| Ítem | Valor |
|---|---|
| Máquina | macOS (Darwin 23.4, arm64), 8 GB RAM, ~16 GB de disco libres |
| Python del sistema | 3.14 (anaconda) y 3.9 (Apple) → **no se usan** (las ruedas de PyTorch/ChromaDB tardan en llegar a versiones nuevas) |
| Entorno del proyecto | `conda` env `tarea1` con **Python 3.12** |
| No instalado | Tesseract, Homebrew, `gh`, Node/wrangler, Docker |
| Sistema objetivo del README | Windows (PowerShell). Los pasos de Windows se documentan pero **no se ejecutan aquí**. |

## Revisión de fuentes (preliminar, medida el 2026-09-21; el reporte formal por página es de la Fase 2)

| Documento | Páginas | Con texto | Sin texto | Car./pág. (media) | ¿Usable tal cual? |
|---|---:|---:|---:|---:|---|
| `ley_32069` (compendio OECE, al 19.07.2026) | 63 | 63 | 0 | ~3 490 | Sí |
| `ds_001_2026_ef` (El Peruano, 08/01/2026) | 16 | 16 | 0 | ~7 036 | Sí |
| `ds_009_2025_ef` (Reglamento) | 196 | 0 | **196** | 0 | **No: escaneo completo, exige OCR** |

## Resultados de la Fase 2 (medidos el 2026-09-21)

| Ítem | Resultado |
|---|---|
| Ley 32069 | 63 págs con texto, 215 269 car., 0 páginas a OCR |
| DS 001-2026-EF | 16 págs con texto, 103 454 car.; la p. 16 traía 141 líneas de OTRAS normas (recortadas por la regla R3) |
| DS 009-2025-EF | 196 págs escaneadas a 96 DPI nativos → **75 procesadas con OCR** (529 118 car.); 121 excluidas (98 formularios/tablas + 23 de menor prioridad) |
| OCR | Tesseract 5.5.2 `spa`, 200 DPI: 4,5 s/pág (mediana 4,5; máx 5,0), confianza media 88,9, 88,2 % de palabras en el vocabulario de referencia |
| Reanudación | Ctrl+C real tras 6 páginas → exit 130; relanzado procesó 69 y reutilizó 6; 3.ª corrida: **0 OCR, 75 desde caché en 0,3 s** |
| Orden de lectura | 3 páginas de 2 columnas revisadas: 1 salto de columna cada una (ideal); 1 desorden local en un título justificado |
| Versiones | DS 001 modifica 96 y incorpora 15 (105 artículos distintos); **98 de 105** tienen su texto original en el corpus (verificado sobre el OCR) |
| Tests | 175 pasan |

## Resultados de la Fase 3 (borrador; 2026-09-21)

| Ítem | Resultado |
|---|---|
| Preguntas | **27**: 21 in_domain (11 coloquiales, 10 jurídicas, 5 sobre artículos modificados por el DS 001) y 6 out_of_domain |
| Páginas esperadas | 34 evidencias en 29 páginas distintas, **todas dentro del subconjunto procesado** (lo comprueba `validate_eval_set.py`) |
| Verificación contra el PDF | Los 34 recortes de imagen se revisaron uno a uno (`docs/eval_evidencia/`); el ancla no se tomó del texto extraído sino que se comparó con la imagen |
| Fuera de dominio | tributación (o01), contratación privada (o02), Colombia (o03), ceviche (o04), **fórmula de la capacidad máxima de contratación (o05, art. 28, p. 8 del DS 009, excluida del índice)**, valor de la UIT (o06) |
| Tests | 192 pasan (17 nuevos del set de evaluación) |

## Resultados de la Fase 4 (medidos el 2026-09-21; Recall provisional)

| Ítem | Resultado |
|---|---|
| Índice definitivo | **1 674 fragmentos** (Ley 427, DS 009 1 042, DS 001 205) en 51 s; colección `normas_c750_o100_30b1cd`; 0 fragmentos truncados (el más largo, 236 tokens de 512) |
| Idempotencia (proceso real) | 2.ª corrida: `existentes=1674 nuevos=0` |
| Reanudación (Ctrl+C real) | interrumpido tras 6 lotes → 384 guardados, exit 130; al relanzar: 384 reutilizados + 1 290 nuevos = 1 674; 3.ª corrida: 0 nuevos |
| Agregar un documento | solo la Ley (427) y luego los tres: `existentes=427 nuevos=1247`; el índice final es idéntico al definitivo (mismos IDs y hashes) |
| Modelo local | `multilingual-e5-small` (118 M): R@3 0,810 · R@5 0,857 · 60 s de indexación · 22 ms/consulta |
| Troceado | `c750_o100`: R@1 0,762 · **R@3 0,905** · R@5 0,905 |
| Tests | 264 pasan (incluye 3 mutaciones que rompen la idempotencia, el aislamiento y la reanudación) |

## Resultados de la Fase 5 hasta el punto manual (medidos el 2026-09-21; PROVISIONALES hasta validar el set)

| Ítem | Resultado |
|---|---|
| Contrato | `responder(pregunta) -> ResultadoRAG` con todos los campos pedidos; errores en `error` (respuesta `None`), abstención en `abstuvo` + `motivo_abstencion` |
| Umbral (primera versión, solo recuperación) | 0,865 (máximo F-β con β = 0,5): 16 respuestas correctas, 1 indebida, 5 abstenciones incorrectas, F-β 0,899. **Reemplazado por 0,835** tras la evaluación real de punta a punta (ver la sección siguiente). Similitudes: in_domain 0,837–0,931 vs fuera de dominio 0,795–0,893 (se solapan casi por completo) |
| Abstención por umbral (proceso real) | «¿Cómo se prepara un buen ceviche?» → `abstuvo=True`, motivo `umbral`, costo 0, **ninguna** línea en `llm_calls.jsonl` |
| Error como error (proceso real) | pregunta del dominio sin `ANTHROPIC_API_KEY` → `error` con instrucciones, `respuesta=None`; tampoco se registra como llamada |
| Versiones | en las dos direcciones, con datos reales (`docs/ejemplo_versiones.md`): las 5 preguntas de versiones producen aviso; `q05` fuerza el texto original de la p. 29 enlazado por título aunque el OCR leyó `143` por `113` |
| Precios | Haiku 4.5: USD 1 / 5 por millón (verificado 2026-09-21, precio único a todas horas); estructura por ventanas probada con tabla ficticia pico/valle |
| Tests | 367 pasan (las mutaciones de umbral, abstención, errores y hora de facturación rompen tests) |

## Resultados de la Fase 5 con llamadas reales (medidos el 2026-09-21; PROVISIONALES hasta validar el set)

Modelo `gemini-3.5-flash-lite`, capa gratuita, `retrieval.busqueda: exacta`, umbral **0,835**.

| Ítem | Resultado |
|---|---|
| Clave | `GEMINI_API_KEY` definida (verificada con una llamada real; nunca se muestra) |
| Primera llamada real | Con `gemini-2.5-flash-lite` la API respondió que **«ya no está disponible para usuarios nuevos»** (la documentación lo listaba como estable): se cambió a `gemini-3.5-flash-lite`. El fallo quedó como primera línea de `logs/llm_calls.jsonl` (es una llamada real) |
| Evaluación de punta a punta (27 preguntas, umbral 0, todas pasan por el LLM) | **In_domain: 18 de 21 respondidas y las 18 citan una página esperada**; 3 abstenciones del LLM (q04, q07, q10). **Fuera de dominio: 5 de 6 rechazadas por el propio LLM**, 1 respuesta parcial fundamentada en la Ley p. 17 (`o05`). 0 errores |
| Umbral | **0,835** (antes 0,865). Con el LLM real, 0,865 daba 16 correctas y 5 abstenciones incorrectas; 0,835 da 18 correctas y 3 abstenciones incorrectas, y ahorra 2 llamadas (o04, o06). Ver `eval/results/umbral_e2e_resumen.md` |
| Costo | Real **USD 0**. De referencia (precio de pago): USD 0,000745 por consulta (USD 0,0216 por 29 llamadas exitosas; 38 343 tokens de entrada y 4 045 de salida) → proyección de referencia ≈ USD 0,75 por cada 1000 consultas |
| Latencia | Mediana de la llamada al LLM **1,95 s** (log real) |
| Log | `logs/llm_calls.jsonl`: 30 líneas reales (29 éxitos, 1 rechazo de modelo), cero reintentos |
| Determinismo | La búsqueda exacta da el mismo resultado en 4 procesos distintos (con HNSW, `o01` cambiaba en 2 de 3) |
| Tests | **553 pasan** |

## Auditoría final y costo real (Fase 13, 2026-09-22)

### Auditoría (ejecutada y verificada en este entorno)

| Comprobación | Resultado |
|---|---|
| Motor sin imports de UI | `grep -rnE "streamlit\|telegram\|fastapi\|flask\|gradio" src/rag_engine` → **0 coincidencias** |
| `check_secrets.py` (árbol + `git log -p`) | **0 hallazgos**, 413 archivos y 40 commits revisados |
| Build del índice DOS VECES (idempotencia) | 1.ª y 2.ª corrida: `nuevos=0 actualizados=0 eliminados=0`, 1674 fragmentos ambas veces |
| `run_eval.py` | `OK: Recall@3 = 0.905 >= mínimo 0.85` (código de salida 0) |
| Todos los tests | **717 pasan** |
| Instalación limpia siguiendo el README | Clon fresco + venv nuevo + `pip install torch` + `pip install -r requirements.txt` (código 0) + 717 tests + `run_eval` en verde + `streamlit run app.py` responde `HTTP 200` y `/_stcore/health` = `ok` |
| Workflow verde en `tarea1-rag` | [run 35677918111](https://github.com/RenataZuta/Homework/actions/runs/35677918111) |
| Workflow rojo demostrado (rama `demo-ci-rojo`, `min_recall_at_3: 0.99`) | [run 35730766798](https://github.com/RenataZuta/Homework/actions/runs/35730766798) → **failure**; rama eliminada tras capturar el enlace; `tarea1-rag` nunca tuvo el valor incorrecto |

**Hallazgo real y serio de esta auditoría:** `requirements.txt` estaba truncado desde el commit de la Fase 7 (la misma corrupción de iCloud que truncó el
README en su momento) — faltaban `streamlit`, `pandas`, `fastapi`, `uvicorn`, `httpx` y `matplotlib`, y ningún test lo detectó porque ninguno ejecuta
`pip install`. Se corrigió y se agregó una prueba dedicada (ver hallazgo 49).

### Costo real de todo el proyecto

| Ítem | Valor |
|---|---|
| Llamadas reales al LLM (`logs/llm_calls.jsonl`) | 110 (109 exitosas, 1 rechazo por `gemini-2.5-flash-lite` retirado) |
| Costo REAL | **USD 0** (capa gratuita de Gemini) |
| Costo de REFERENCIA (precio de pago) | USD 0,075933 en total = **USD 0,000697 por consulta** |
| Tokens | 161 726 de entrada + 10 966 de salida |
| Latencia mediana | 1,92 s |
| Embeddings por API (comparación, Fase 6) | USD 0 gastado: OpenAI nunca se probó (sin clave, sin cargar crédito); Gemini está en capa gratuita (960/1674 fragmentos, cuota diaria de 1000 textos aún no alcanzó para completarlo en dos intentos) |
| **Costo real total del proyecto hasta hoy** | **USD 0** |

## Resultados de la Fase 12 hasta el punto manual (2026-09-22)

| Ítem | Resultado |
|---|---|
| Memoria medida en local (dato real, no estimado) | Cargar el modelo de embeddings local ya usa **883 MB** de RSS (antes de sumar el propio servidor de Streamlit). Es el dato que pedía el enunciado antes de elegir plataforma |
| Plataforma | **Streamlit Community Cloud** (gratis, sin tarjeta). Se descartó Hugging Face Spaces: su documentación ahora exige plan PRO para Spaces con cómputo en cuenta personal (mismo hallazgo de la Fase 11) |
| Riesgo aceptado y con salida documentada | La RAM gratuita de Streamlit Cloud se cita ampliamente en 1 GB, sin confirmación oficial textual hoy; 883 MB + Streamlit puede superarla. Salida ya lista: `embeddings.proveedor: gemini` (sin PyTorch) es un cambio de una línea, ya implementado y probado desde la Fase 6 |
| Índice versionado | `data/index/` (11 MB) se agregó al repositorio — se cambió el `.gitignore` a propósito: la app pública no tiene un paso de "build" propio, así que nunca puede reconstruirlo al iniciar sesión |
| Topes de gasto | `deploy.topes` en `config.yaml`; se revisan ANTES de llamar al motor (cero costo si ya se alcanzaron). El de sesión usa `st.session_state`; el global lee `logs/llm_calls.jsonl` de HOY (en `deploy.zona_horaria`) — sin base de datos nueva. Solo cuentan llamadas que de verdad llegaron al LLM (`r.modelo is not None`): una abstención por umbral no gasta cupo |
| Hallazgo real durante las pruebas | El tope global de esta MISMA sesión de desarrollo (100/día) ya se había superado (101 líneas reales en `logs/llm_calls.jsonl` de hoy) y bloqueaba pruebas de `app.py` que no lo estaban probando a propósito. Se corrigió aislando esas pruebas con un log de costos vacío por defecto; en producción el archivo empieza vacío |
| Secretos | `GEMINI_API_KEY` va en los *Secrets* de Streamlit Cloud; verificado que Streamlit expone las claves de nivel superior también como variables de entorno normales, así que `config.py` las lee sin cambios |
| Tests | **716 pasan** (5 mutaciones de los topes de gasto detectadas 5/5) |
| Sin hacer | El despliegue real (crear la app, cargar el secreto, verificar la URL pública) |

## Resultados de la Fase 11 hasta el punto manual (2026-09-22)

| Ítem | Resultado |
|---|---|
| Backend | `interfaces/api_server.py` (FastAPI): `GET /health` sin auth; `POST /telegram/webhook` exige `X-Internal-Key`, procesa en segundo plano con los handlers de la Fase 10 |
| Bug real encontrado por las pruebas | `BackgroundTasks` despacha las funciones síncronas a un hilo del *pool*; reusar una única `sqlite3.Connection` creada en el hilo del arranque revienta con «objects created in a thread…». Se corrigió: cada tarea en segundo plano abre y cierra su propia conexión |
| Host elegido | **Render, plan gratuito** (decisión de la persona tras verificar que Hugging Face Spaces Docker ahora exige plan PRO para cuentas personales — cambio real de política, no estaba en el plan original) |
| Descartados | Hugging Face Spaces Docker (requiere PRO de pago); Google Cloud Run (exige tarjeta / cuenta de facturación); Fly.io (ya no ofrece capa gratuita real) |
| Dockerfile | `python:3.12-slim`; el modelo de embeddings se descarga y el índice se **construye** durante el `build` (a partir de `data/processed/`, versionado); `requirements-backend.txt` más chico que el de desarrollo (sin OCR, sin gráficos, sin Anthropic); escucha en `0.0.0.0:$PORT`; usuario sin privilegios (`USER app`) |
| Worker | `cloudflare_worker/src/index.js`: valida `X-Telegram-Bot-Api-Secret-Token`, responde 200 de inmediato, reenvía con `ctx.waitUntil`, avisa «despertando» y reintenta si el backend tarda |
| Desviación documentada | El Worker necesita un 4.º secreto, `TELEGRAM_BOT_TOKEN` (el plan original solo mencionaba tres), para poder avisar «despertando» por su cuenta sin depender del backend |
| Verificado en la documentación oficial (2026-09-22) | Límites del plan gratuito de Workers (100 000 peticiones/día, `ctx.waitUntil` hasta 30 s); Render sin tarjeta, Docker, 750 h/mes gratis, duerme a los 15 min, despierta en ~1 min; HF Spaces Docker ahora exige PRO |
| Pruebas | `interfaces/api_server.py` probado de verdad con `fastapi.testclient` (sin red); `Dockerfile`, `wrangler.toml` y el Worker revisados con pruebas ESTÁTICAS (leen los archivos como texto: no se pudieron compilar ni ejecutar — sin docker/node/wrangler en este entorno) |
| Tests | **712 pasan** |
| Sin probar | Todo el despliegue real: `docker build`, `wrangler deploy`, el webhook registrado y la prueba de punta a punta con la laptop apagada |

## Resultados de la Fase 10 hasta el punto manual (2026-09-21)

| Ítem | Resultado |
|---|---|
| Handlers | `interfaces/telegram_handlers.py`: solo importa `rag_engine.engine.responder`; `procesar_update()` es el punto de entrada único que también usará el webhook de la Fase 11 |
| Autorización | `TELEGRAM_ALLOWED_USER_IDS` (denegar por defecto: vacío = nadie); un usuario no autorizado nunca llega a `responder()` |
| Límite diario | SQLite (`data/bot.db`, ignorada por git), por usuario y por fecha en `bot.zona_horaria_limite` (no la del sistema); al superarlo, aviso y CERO llamadas al motor |
| Comandos | `/ayuda`, `/fuente` (documento, página, similitud y fragmento de la última consulta), `/costo` (última consulta + acumulado del día); ninguno cuenta para el límite |
| Feedback | Botones 👍/👎 con el ID de la consulta en `callback_data` (`fb:<id>:1|-1`); un segundo voto actualiza, no duplica; no se puede calificar la consulta de otro usuario ni sin estar autorizado |
| Privacidad de errores | Los mensajes al usuario final son los de `config.yaml` (nunca el texto técnico de `r.error`, que puede traer rutas o detalles del proveedor) |
| Cliente de la Bot API | `interfaces/telegram_api.py`: llamadas REST directas (reutiliza `llm/transporte.py`); el token nunca se registra ni aparece en un mensaje de error (se reusa el saneador de `cost_log`) |
| Modo desarrollo | `scripts/run_telegram_bot.py` (polling, con reintentos ante fallos de red de Telegram) |
| Feedback en Streamlit | `evaluation/feedback_summary.py` + pestaña Costos de `app.py` |
| Verificado (sin límites de Telegram reales) | Límites de la Bot API confirmados en la referencia oficial: `sendMessage` 1-4096 caracteres, `callback_data` 1-64 bytes, `answerCallbackQuery.text` 0-200, `secret_token` 1-256 `[A-Za-z0-9_-]` en la cabecera `X-Telegram-Bot-Api-Secret-Token` |
| Tests | **685 pasan**; 8 mutaciones de seguridad del bot (autorización, límite, mensaje de error crudo, feedback ajeno, botón en error, avisos repetidos, UNIQUE del feedback, token vacío) → **8/8 detectadas** |
| Pendiente | **No se probó con un bot ni un chat de Telegram reales** (no hay token todavía): falta la aceptación de la fase (consulta con citas, rechazo, límite, comandos y feedback funcionando de verdad) |

## Resultados de la Fase 9 hasta el punto de push (2026-09-21)

| Ítem | Resultado |
|---|---|
| Workflow | `.github/workflows/eval.yml`: en cada push y pull request que toque `tarea1/**`; Python 3.12 con caché de pip; **PyTorch CPU** desde el índice oficial de CPU; `requirements-ci.txt` (versiones fijadas); caché del modelo de embeddings; pruebas; índice desde `data/processed` (sin OCR); `run_eval`; sube `eval/results/` como artefacto (`if: always()`); permisos de solo lectura; **cero secretos** |
| Mínimo | `eval.min_recall_at_3 = 0,85` (real 0,905 = 19/21; 0,85 exige 18/21 y tolera **una** pregunta más fallida). Vive solo en `config.yaml`; el workflow no repite el número |
| Acciones | Últimos mayores verificados con `git ls-remote --tags`: `checkout@v7`, `setup-python@v7`, `cache@v6`, `upload-artifact@v7` |
| Simulación del CI | Clon limpio del commit + `venv` nuevo + `pip install torch` + `requirements-ci.txt`, sin `.env`, sin Tesseract ni Streamlit: **610 pruebas pasan (2 se omiten a propósito: Streamlit y Tesseract)**, `build_index` OK, `run_eval` → **OK: Recall@3 = 0,905 ≥ 0,85** (código 0) |
| Fallo simulado | `run_eval --min-recall-3 0.99` → código de salida 1 (Fase 6); falta la corrida roja real en GitHub |
| Pruebas del workflow | 11 pruebas (sin secretos, orden de pasos, PyTorch antes que el resto, sin OCR ni LLM, artefacto, mínimo con margen frente al resultado real) + 4 mutaciones del workflow detectadas 4/4 |

## Resultados de la Fase 8 (medidos el 2026-09-21; PROVISIONALES hasta validar el set)

| Ítem | Resultado |
|---|---|
| Módulos | `retrieval/bm25.py` (Okapi/Lucene propio, sin dependencia; minúsculas, sin tildes, stopwords, stemmer ligero opcional), `retrieval/hybrid.py` (RRF), `retrieval/modos.py` (despacho por `retrieval.modo`) y `evaluation/compare_retrievers.py` |
| Set (21 preguntas) | Semántico R@1/3/5 = 0,762 / 0,905 / 0,905, MRR 0,825, coloquial R@3 0,818. BM25: 0,571 / 0,714 / 0,762 (coloquial 0,455; con stemming 0,762 / 0,545). Híbrido + stemming: 0,714 / 0,905 / 0,905, MRR 0,802. En jurídico y en modificatoria todos igualan |
| Sonda de números de artículo (96 consultas sintéticas) | R@3: **BM25 0,844**, híbrido 0,771, semántico 0,448 |
| Punta a punta (LLM real, umbral 0) | Semántico 18/21 con cita correcta y 1 indebida; híbrido + stemming 17/21 y 2 indebidas (26 llamadas nuevas; ver hallazgo 38) |
| Sensibilidad del híbrido | Candidatos 50/100/200 × `rrf_k` 10/60: el set no cambia (q04 y q07 siguen fallando) |
| Decisión | `retrieval.modo: semantico` |
| Compuerta | Compara SIEMPRE cosenos: el mayor coseno entre los recuperados (el motor y `evaluar_recuperacion`); BM25/RRF solo ordenan |
| Tests | **615 pasan**; 8 mutaciones de BM25/RRF/compuerta detectadas 8/8 |

## Resultados de la Fase 7 (medidos el 2026-09-21)

| Ítem | Resultado |
|---|---|
| `app.py` | Cuatro pestañas: **Consulta** (respuesta, indicador de abstención por el campo `abstuvo`, avisos de versión agrupados y sin repetidos, fragmentos citados con documento/página/similitud/texto y origen —recuperado, modificatoria forzada, original forzado—, tokens, costo real y de referencia, latencia), **Calidad de extracción**, **Evaluación** (Recall@k, abstención, barrido de umbral con gráfico, embeddings, troceado, BM25 «pendiente Fase 8») y **Costos** (agregado de `llm_calls.jsonl`) |
| Índice | Se carga UNA vez con `@st.cache_resource` y **nunca se reconstruye**: si falta, `st.error` con el comando. Tests: el contenido de todas las colecciones (nombre, conteo, hash de textos) es idéntico antes y después de abrir la app con el índice real; la app no importa `indexing`/`extraction` |
| Errores | `st.error`; la cuota agotada muestra `mensajes.error_cuota` y el detalle técnico |
| Datos de las pestañas | `src/reporting/datos.py` (sin dependencias de interfaz, 14 tests): si falta un archivo lo dice, nunca inventa cifras |
| Pruebas | 15 tests de `AppTest` + 7 mutaciones de la app (error como markdown, abstención inferida del texto, sin caché del motor, importar indexación, avisos repetidos, sin agrupar citadas, costo real = referencia) → **7/7 detectadas** |
| Entorno limpio | `venv` nuevo (Python 3.12.13, macOS), `pip install -r requirements.txt` + pytest → **581 tests pasan** y la app abre; `requirements.txt` quedó **fijado** con esas versiones. `streamlit run app.py` arranca (HTTP 200, `/_stcore/health` = ok) |
| Tests totales | **583 pasan** (~42 s) |

## Resultados de la Fase 6 hasta el punto manual (medidos el 2026-09-21; PROVISIONALES hasta validar el set)

| Ítem | Resultado |
|---|---|
| `evaluation/run_eval.py` | Sin LLM ni costo. Recall@1/3/5 = **0,762 / 0,905 / 0,905**; R@3 de la modificatoria 0,80; abstenciones correctas 5/6, incorrectas 5/21. Código de salida 0 con `--min-recall-3 0` y **1** con `--min-recall-3 0.99` (verificado en proceso real); es la base del gate de la Fase 9 |
| Local (`multilingual-e5-small`) | 384 dim, 2,45 MB de vectores, 52,6 s para indexar 1674 fragmentos, 17,2 ms/consulta, USD 0 |
| API (`text-embedding-3-small`) | **PENDIENTE** (falta `OPENAI_API_KEY`). Precio verificado: USD 0,02 / M tokens; estimación previa con tiktoken: 282 884 tokens → **USD 0,0057** por indexar todo el corpus (estimación, no medición) |
| Documentación | `docs/metricas_evaluacion.md`: qué mide cada métrica, qué no dice y por qué la evaluación a USD 0 permite correrla en cada cambio |
| Tests | 380 pasan |

## Cambio de proveedor de generación (2026-09-21): de Anthropic a Google Gemini, capa gratuita

Petición de la persona: **no pagar nada adicional a su suscripción**; ninguna acción que genere cargos sin preguntar. Todo lo siguiente está hecho y probado **sin claves** (la primera llamada real necesita `GEMINI_API_KEY`).

| Ítem | Resultado |
|---|---|
| Modelo elegido | **`gemini-2.5-flash-lite`** (Flash-Lite estable). Motivos en la tabla de decisiones |
| Verificación | Páginas oficiales de Google (precios, modelos, deprecaciones, embeddings, límites) leídas el 2026-09-21; los IDs, los precios de referencia y la existencia de capa gratuita salen de ahí |
| Abstracción | `llm.provider` en `config.yaml`; interfaz `ClienteLLM` (`llm/base.py`) con un cliente por proveedor (`gemini_client.py`, `anthropic_client.py` conservado sin usar); `factory.py` compone todo con throttle + reintentos |
| Costo | El log registra `costo_usd_real` (0 en la capa gratuita) y `costo_usd_referencia` (precio de pago de `pricing.yaml`, con fuente y fecha). Ventanas horarias y su test se conservan (también para Gemini) |
| Límites | Throttle por RPM (ventana deslizante), backoff exponencial con jitter ante 429/5xx/red, respeta `retryDelay`; cuota diaria o límite persistente → `error_tipo="cuota_agotada"` en `ResultadoRAG.error`, jamás una respuesta normal |
| Caché e2e | `llm/cache.py`, `eval.cache_llm`: hash de todo lo que determina la respuesta; no cachea errores; con todo en caché no pide clave; la cuota agotada corta la evaluación con informe «INCOMPLETA» y se puede reanudar |
| Privacidad | Solo pregunta + fragmentos de normas públicas (test que lo verifica); aviso en `config.yaml` (`mensajes.aviso_privacidad`) y en el README |
| Embeddings por API | OpenAI se intenta **sin crédito**: `insufficient_quota` → fila «no ejecutada por costo»; segunda implementación con `gemini-embedding-2` (capa gratuita). Sin claves ambas filas quedan «pendiente» |
| Sonda real (sin costo) | Llamada a la API real con clave **inválida**: HTTP 400 «API key not valid» → clasificado `autenticacion` en el LLM y en embeddings. Confirma URL, transporte y formato de error |
| Tests | **531 pasan** (nuevos: límites, cliente Gemini, embeddings Gemini, caché, fábrica, precios, config, secretos) |
| Mutaciones | 13 mutaciones deliberadas (throttle, backoff, reintento de errores permanentes, conversión a `cuota_agotada`, `retryDelay`, cuota diaria, clave en cabecera, tokens de razonamiento, costo real, log de caché, clave de caché, intentos, prefijos) → **13/13 detectadas** por los tests |

## Decisiones registradas

| Fase | Decisión | Evidencia / fuente | Fecha |
|---|---|---|---|
| 0 | LLM de generación: `claude-haiku-4-5-20251001` (alias `claude-haiku-4-5`), USD 1 / 5 por millón de tokens (entrada / salida) | https://platform.claude.com/docs/en/about-claude/pricing y `/models/overview` (Haiku 4.5 es el más barato vigente; Sonnet 5 cuesta USD 2 / 10) | 2026-09-21 |
| 0 | La documentación oficial de Anthropic **no publica precios distintos por hora**: un solo precio por modelo | Misma página de precios, sin mención de tarifas horarias | 2026-09-21 |
| 1 | El PDF de la Ley es el **compendio "versión actualizada" del OECE (fuente base SPIJ) al 19.07.2026**: es lo único que ofrece la colección oficial del OECE. No es el texto original de El Peruano. Se etiqueta `ley_vigente` y se declara en el README | Nota de la propia página del OECE | 2026-09-21 |
| 1 | Enlace directo al PDF del DS 001-2026-EF: aparece en el HTML de la ficha de El Peruano (`/api/archivo/file/…/2474920-3.PDF`); no hubo bloqueo, así que no se necesitó descarga manual | Descarga real, 3,56 MB, 16 págs | 2026-09-21 |
| 1 | Tamaños: 0,52 / 18,68 / 3,56 MB; ninguno se acerca a los 90 MB de aviso → no se necesita Git LFS | `data/raw/MANIFEST.json` | 2026-09-21 |
| 2 | Motor de OCR: **Tesseract `spa` a 200 DPI** (no EasyOCR, no 96/150/300 DPI) | `eval/results/ocr_benchmark.md`: 620 palabras correctas/pág frente a 276 (EasyOCR), 6,7× más rápido; 150 DPI da mejor porcentaje pero omite ~20 % del texto | 2026-09-21 |
| 2 | Umbral de OCR = 100 caracteres útiles **y** imagen a página completa | Páginas con texto: mín 946; escaneadas: 0 | 2026-09-21 |
| 2 | Cabecera de páginas escaneadas: regla por **posición** (banda superior 10 %), no por texto | El OCR lee la cabecera de forma impredecible (`Miércoses 22 48 enero…`) | 2026-09-21 |
| 2 | Página pública = índice del PDF (base 1), que coincide con el nº impreso del DS 009 | Verificado en las págs. 10 y 60 | 2026-09-21 |
| 2 | Subconjunto de OCR: 75 págs = 33 por cobertura de estructura + resto por artículos modificados y relevancia MYPE; criterio de página de texto = ≥ 4 500 car. **y** confianza ≥ 80 | `docs/ocr_subset.md`; separa exactamente las 98 págs normativas de los formularios del anexo | 2026-09-21 |
| 3 | Formato del CSV: varios documentos con `\|` y varias páginas de un documento con `;` (`ds_001_2026_ef\|ds_009_2025_ef` / `8;9\|47`); en las preguntas de versiones el primer documento es siempre el DS 001 | Permite medir aparte si el recuperador trae el texto vigente y no solo el original | 2026-09-21 |
| 3 | Las evidencias (ancla + dato de cada página) van en `eval/evidencia.yaml`, no en el CSV, para no romper las columnas pedidas | `scripts/eval_evidence.py` recorta la imagen del PDF | 2026-09-21 |
| 3 | 27 preguntas en lugar de 20: más out_of_domain cercanas (o02, o03, o05, o06) para que el barrido de umbral no se calibre solo con casos fáciles | Limitación: se calibra con el mismo set | 2026-09-21 |
| 4 | Modelo de embeddings local: **`intfloat/multilingual-e5-small`** (prefijos `query: `/`passage: `, 512 tokens; tarjeta verificada) | Empata con bge-m3 en R@3/R@5 con 5× menos parámetros, 8× menos tiempo de indexación y 6× menos latencia; e5-base recupera peor; MiniLM trunca el 91,6 % de los fragmentos (`docs/modelos_embeddings.md`, `eval/results/modelos_locales.md`) | 2026-09-21 |
| 4 | Troceado: **750 caracteres con solape de 100** | Mayor Recall@3 de 6 configuraciones (`eval/results/chunking_comparacion.md`); diferencia de 1–2 preguntas sobre 21 → provisional | 2026-09-21 |
| 4 | **Encabezado de contexto activado sin evidencia de mejora**: ayuda en una pregunta con 750 y perjudica en otra con 1000 (neto ≈ 0). Se mantiene por el diseño (encabezados huérfanos) y se reevaluará con el set validado | Ablación en `chunking_por_pregunta.csv` | 2026-09-21 |
| 4 | Vector store: **ChromaDB persistente** con distancia coseno | Guarda vector + texto + metadatos (para citar), upsert por ID (base de la idempotencia), filtros por metadatos, sin servidor. FAISS sería más rápido pero no guarda metadatos y el corpus (~1 700 fragmentos) no lo necesita | 2026-09-21 |
| 4 | ID de fragmento `documento:version:pNNNN:cNNN:hash-de-config`; se omite un ID existente solo si también coincide el hash del contenido | Si una página se reprocesa, sus fragmentos se re-embeben y los obsoletos del mismo documento se borran | 2026-09-21 |
| 4 | Menciones de artículos guardadas por norma (`articulos_ley` / `articulos_reglamento`), descartando números fuera de rango (Ley ≤ 100, Reglamento ≤ 389) y otras normas | Cierra el riesgo de los hallazgos 6 y 10: 0 fragmentos con el «artículo 399» fantasma | 2026-09-21 |
| 4 | La carga del modelo intenta primero solo desde el disco (`local_files_only`) | sentence-transformers hacía peticiones a Hugging Face en cada arranque; sin internet esperaba ~30 s de reintentos | 2026-09-21 |
| 5 | Criterio del umbral: **F-β con β = 0,5** (la precisión pesa el doble que la cobertura) | «Responder mal es peor que no responder»; elige el centro de la meseta de máximo | 2026-09-21 |
| 5 | Versiones **bidireccionales**: si se recupera el original se fuerza el DS 001; si se recupera el DS 001 se fuerza el texto original (enlace por número o por título) | Con un solo sentido, 4 de las 5 preguntas de versiones quedaban sin aviso y el modelo veía solo los numerales modificados como si fueran la regla completa | 2026-09-21 |
| 5 | `llm.temperatura` es opcional (`null` = no se envía) | La referencia oficial dice que los modelos posteriores a Opus 4.6 rechazan `temperature` distinto de 1.0; el SDK 1.7 ya no lo tipa (se envía por `extra_body`) | 2026-09-21 |
| 5 | Una llamada que falla ANTES de salir al proveedor (falta la clave) no se registra en `llm_calls.jsonl` | El log es un entregable: solo debe contener llamadas reales | 2026-09-21 |
| 5 | **Cambio de proveedor de LLM: Anthropic → Google Gemini (capa gratuita)** | Restricción de la persona: sin pagos adicionales. Anthropic no tiene capa gratuita; su cliente se conserva sin usar y la config lo valida (`nivel: gratuito` es inválido con Anthropic) | 2026-09-21 |
| 5 | **Modelo `gemini-2.5-flash-lite`** | En la página de precios figura con «Free of charge»; **estable**, sin fecha de retiro anunciada; su ficha declara *function calling* y *structured outputs*; es el más barato de los que tienen nivel gratuito (referencia USD 0,10 / 0,40 por millón), así que el costo de referencia es una cota baja realista. Descartados: `gemini-3.1-flash-lite` (retiro anunciado el 2027-05-07), `gemini-2.5-flash` (USD 0,30 / 2,50), `gemini-3.5-flash-lite` (más nuevo, USD 0,30 / 2,50; queda como alternativa configurable si la calidad de 2.5 no alcanza). La calidad de generación se medirá con la evaluación e2e; se puede cambiar el modelo editando una línea | 2026-09-21 |
| 5 | Costo **real** frente a **referencia** en el log y en `ResultadoRAG` | En la capa gratuita el gasto es 0, pero conviene saber cuánto costaría de pago (dimensionar un despliegue público, Tarea 2). La referencia usa el precio de pago verificado; con `nivel: pago`, real = referencia | 2026-09-21 |
| 5 | Throttle por ventana deslizante de 60 s y `rpm` conservador (10 LLM / 20 embeddings) | Google no publica los límites de la capa gratuita en la documentación (remite a AI Studio); el valor es de diseño, no un dato de Google, y se ajusta en `config.yaml` | 2026-09-21 |
| 5 | Solo se reintentan 429 «por tasa», 5xx y red; la cuota **diaria** y los demás errores fallan de inmediato | Reintentar una cuota diaria agotada solo pierde tiempo; la recomendación oficial es reintentar 429/408/5xx con backoff exponencial y jitter. Tras agotar los reintentos el error final es `cuota_agotada` | 2026-09-21 |
| 5 | Caché **solo** en la evaluación de punta a punta, no en el motor | El motor debe registrar cada llamada real; la caché reutiliza respuestas idénticas sin ensuciar el log de costos y sin exigir clave si todo está cacheado | 2026-09-21 |
| 6 | Embeddings por API: OpenAI sin crédito → si `insufficient_quota`, «no ejecutada por costo»; segunda implementación `gemini-embedding-2` de 768 dimensiones | «Free of charge» en la página de precios; el preview `gemini-embedding-2-preview` se retiró el 2026-08-10, por eso se usa el ID estable; la guía recomienda 768/1536/3072 y este modelo no usa `task_type` (plantillas en el texto) | 2026-09-21 |
| 6 | Cada texto en su propia petición dentro de `batchEmbedContents` | La guía advierte que varias `parts` en un mismo `content` producen UN solo vector agregado | 2026-09-21 |
| 5 | **Modelo corregido a `gemini-3.5-flash-lite`** (sustituye a `gemini-2.5-flash-lite`) | La API rechazó el 2.5 en esta cuenta («no longer available to new users»). El 3.5 Flash-Lite: «Free of charge», estable, sin retiro anunciado, *structured outputs*; referencia USD 0,30 / 2,50 por millón (salida incluye tokens de razonamiento). Razona por defecto en nivel «minimal» | 2026-09-21 |
| 5 | `temperatura: null` para Gemini (se anula `llm.temperatura`) | La guía de Gemini 3 recomienda dejar 1.0 y advierte que bajarla puede causar bucles o degradación. La reproducibilidad de la evaluación la da la caché de respuestas, no la temperatura | 2026-09-21 |
| 5 | **Búsqueda exacta** (`retrieval.busqueda: exacta`) en lugar de la aproximada HNSW de Chroma | Con HNSW, la pregunta `o01` devolvía un top-5 distinto al exacto en 2 de 3 procesos (faltaba el fragmento p. 96, el más parecido). Con ~1 700 vectores la exacta cuesta <1 ms y es determinista. Recall no cambia (0,762 / 0,905 / 0,905). Test de equivalencia con fuerza bruta y mutaciones | 2026-09-21 |
| 5 | **Umbral 0,835** calibrado con el LLM real (antes 0,865) | Con el LLM como segunda defensa, F-β es plano hasta 0,840; se toma el tope de la meseta menos un margen de 0,005. El 0,865 descartaba 2 respuestas buenas (q01, q08) sin evitar ninguna mala. La compuerta se conserva por costo y latencia | 2026-09-21 |
| 6 | La comparación de embeddings por API **reanuda** en vez de reiniciar | La cuota gratuita de embeddings es de **1000 solicitudes por día y por modelo** (cuenta cada texto; medido con el cuerpo del 429), y el corpus tiene 1674 fragmentos: se completa en 2 días conservando lo ya indexado | 2026-09-21 |
| 7 | Lectura de reportes en un módulo aparte (`src/reporting/datos.py`), sin pandas ni Streamlit | Se prueba sin interfaz y no obliga al CI ligero a instalar Streamlit; la app solo pinta | 2026-09-21 |
| 7 | Pruebas con `streamlit.testing.AppTest` (sin navegador) | Permiten comprobar de forma automática qué se muestra en cada caso (respuesta, abstención, error, cuota) | 2026-09-21 |
| 7 | `requirements.txt` con versiones exactas de los paquetes directos, sacadas de un venv limpio | Lo pide la fase y evita que una versión nueva rompa la instalación del corrector | 2026-09-21 |
| 7 | **Copia de trabajo fuera de iCloud: `~/dev/Homework`** (la de `~/Documents/Github/Homework` queda intacta, con los mismos commits) | Con la carpeta en iCloud, macOS «desmaterializaba» archivos y los tests/`git commit` daban `Operation timed out` o se colgaban (hasta 5 min por corrida). Copia de seguridad adicional: `~/Homework_tarea1-rag.bundle` (`git bundle` de `main` y `tarea1-rag`) | 2026-09-21 |
| 8 | **Modo final `semantico`** | Mejor en R@1/3/5 y MRR del set y de punta a punta; el híbrido solo gana en la sonda de números de artículo (y no recupera q07: el fragmento está fuera de los 50 primeros del semántico). Opción documentada para uso por número de artículo | 2026-09-21 |
| 8 | BM25 implementado a mano, no `rank_bm25` | ~60 líneas, sin dependencia nueva y sin el IDF negativo de algunas implementaciones; comprobado contra la fórmula a mano | 2026-09-21 |
| 8 | La compuerta usa el **mayor coseno recuperado**, no el puntaje de BM25/RRF ni la similitud del primer lugar | Los puntajes de BM25/RRF no son cosenos; así el umbral calibrado sirve en los tres modos | 2026-09-21 |
| 11 | Host del backend: **Render** (plan gratuito) | Sin tarjeta, admite Docker; Hugging Face Spaces Docker pasó a exigir PRO para cuentas personales (verificado en la documentación oficial); Google Cloud Run exige tarjeta. Decisión de la persona tras vérselo planteado | 2026-09-22 |
| 11 | Cada tarea en segundo plano del backend abre su PROPIA conexión SQLite | `sqlite3.Connection` no se puede compartir entre hilos; `BackgroundTasks` corre las funciones síncronas en un hilo del *pool*, distinto del que abrió la conexión en el arranque. Lo encontró una prueba real (`fastapi.testclient`), no una revisión de código | 2026-09-22 |
| 11 | El Worker usa 4 secretos, no 3 (agrega `TELEGRAM_BOT_TOKEN`) | Sin el token, el Worker no podría enviar el aviso de «despertando» cuando el backend tarda; esa llamada a Telegram la hace el propio Worker, no el backend | 2026-09-22 |
| 11 | `requirements-backend.txt` separado de `requirements.txt` | El backend no hace OCR, no dibuja gráficos y no usa Anthropic: una imagen más chica arranca más rápido en un plan gratuito que ya duerme | 2026-09-22 |
| 11 | El índice se CONSTRUYE en el `Dockerfile` (no se copia un `data/index/` ya armado) | `data/index/` no está versionado (igual que en el CI de la Fase 9); construirlo en el build es la única forma de tenerlo en la imagen sin cambiar esa regla | 2026-09-22 |
| 12 | Plataforma: **Streamlit Community Cloud** | Gratis, sin tarjeta, hecha específicamente para apps Streamlit; HF Spaces quedó descartado (exige PRO). Riesgo de RAM aceptado con una salida de una línea ya lista (`embeddings.proveedor: gemini`) | 2026-09-22 |
| 12 | `data/index/` pasa a estar versionado (antes, deliberadamente no) | La app pública no tiene un paso de build propio: es la única forma de que nunca reconstruya el índice al iniciar sesión, como exige la fase | 2026-09-22 |
| 12 | El tope global lee `logs/llm_calls.jsonl` en vez de una base de datos nueva | Ya es la fuente de verdad del costo real; una llamada que no llegó al LLM (abstención por umbral) tampoco aparece ahí, así que no gasta cupo — coherente con que el tope protege el COSTO, no el uso general | 2026-09-22 |
| 0 | README completo en `tarea1/README.md`; el README de la raíz solo recibe una sección con enlace | El repo aloja varias tareas; no se sobrescribe lo existente | 2026-09-21 |
| 0 | Los módulos se crean en la fase que los necesita (sin archivos vacíos de relleno) | Historial de commits refleja el trabajo real | 2026-09-21 |

## Hallazgos del issue que afectan el plan

1. **El Reglamento no es parte del índice obligatorio.** El issue pide Ley 32069 + DS 001-2026-EF, y el documento opcional debe ser *una norma que modifica la ley o su reglamento*. El DS 009-2025-EF es el Reglamento mismo y además es un escaneo. Se incluye por decisión propia (subconjunto con OCR); hay que documentarlo y conservar en la evaluación al menos una pregunta `out_of_domain` que solo responda una página **no** procesada del Reglamento (requisito 3.4 del issue).
2. **Plazo:** el issue fija el 23-sep; el trabajo real empezó el 21-sep. El historial de esta rama será necesariamente reciente; no se altera ninguna fecha de commit.
3. **La "Ley" ya incorpora modificatorias posteriores.** El compendio integra, entre otras, el DL 1715 (04/02/2026) y la Ley 32515. Además, la modificación de la Ley 32732 (19/07/2026) entra en vigencia recién al día siguiente de la publicación de la modificación del Reglamento (aviso de OECE en la misma página). Consecuencia: `ley_vigente` significa "texto consolidado por OECE a esa fecha", no "texto original".
4. **Documentos oficiales relacionados que NO se incluyen** (se declaran como limitación en el README): la **fe de erratas del DS 009-2025-EF** (gob.pe) y el **Reglamento consolidado del OECE al 09.01.2026**. Este último no se descargó ni se verificó; además fusiona el DS 001-2026-EF con el texto original, lo que borraría la distinción de versiones que el proyecto necesita mostrar. Solo se consideraría como verificación cruzada, nunca como parte del índice.
5. **El anexo del DS 009 son formularios** (págs. 105–196): trámites del RNP, instituciones arbitrales, cuadros de experiencia. Se excluyen del corpus: OCR ilegible a 96 DPI (confianza ≈ 55) y sin normativa consultable. La p. 100 no es el Anexo I sino las Disposiciones Complementarias Transitorias.
6. **Errores de carácter en números del OCR** (`Articulo 399` por 99, `598.2` por 98.2, `CAPITULO 111`): la extracción de `articulos_mencionados` (Fase 4) debe descartar números > 389 y apoyarse en el rango de artículos de la página. El OCR suele leer coma en vez de punto tras el número de artículo.
7. **Siete artículos modificados sin texto original en el corpus**: `46, 88, 94, 113, 198, 218, 318` (página excluida o número mal leído). Para ellos el motor solo tendrá el texto del DS 001.
8. **Trabajo pendiente para la Fase 4:** `easyocr` y `torch` quedaron instalados en el entorno `tarea1` solo por el benchmark; `requirements.txt` los deja comentados.
9. **El compendio de la Ley trae versiones dentro de la propia página.** En la p. 36 el art. 73.2 aparece en cursiva (0,5 %, tope 50 UIT) y una nota `(*)` reproduce el texto vigente desde 2025 (Ley 32187: 3 % en general); el 67.8 está derogado por la Ley 32103. El prompt de la Fase 5 debe tratar «(*) … cuyo texto es el siguiente» como el texto que prevalece.
10. **Ley y Reglamento numeran sus artículos por separado** (el art. 98 de la Ley es «Retiro temporal del registro»; el 98 del Reglamento es sobre la comparación de precios). Al extraer `articulos_mencionados` hay que registrar a qué norma remite cada mención («artículo 61 **de la Ley**»), y el aviso de versión solo aplica a fragmentos del Reglamento.
11. **Encabezados huérfanos:** el título de un artículo puede quedar al final de una página y su contenido en la siguiente (arts. 89 y 93 de la Ley). Las páginas esperadas son siempre las del contenido. Idea para la Fase 4: guardar el último encabezado de la página anterior como metadato del primer fragmento.
12. **El OCR falla en cifras:** el art. 114 original dice «S/ 480 000» y el OCR leyó `430 000` (la imagen y el DS 001, que tiene capa de texto, confirman 480 000). Toda respuesta con cifras del Reglamento original merece cautela. El DS 001 marca en **negrita** lo nuevo de cada numeral, y el art. 25.7 se invierte: el original dice que los ejecutores de obra **no pueden** acreditar experiencia de una reorganización societaria y el DS 001 dice que **pueden** (esa página del original, la 8, está fuera del índice).

13. **Brecha de vocabulario coloquial↔legal:** `q04` («¿hasta qué monto me pueden comprar sin hacer una licitación?» → «contratos menores… ocho UIT») y `q07` («ofertas con el mismo puntaje» → «criterios en caso de empate») fallan en las 6 configuraciones aunque el fragmento correcto SÍ está en el índice. Es el caso que evaluará la Fase 8 (BM25 / híbrido).
14. **Los puntajes de E5 están comprimidos:** para esas dos preguntas los 4 primeros vecinos (irrelevantes) tienen similitud 0,854–0,864. El barrido de umbral de la Fase 5 tendrá un margen estrecho; conviene barrer entre 0,70 y 0,95 con paso fino además del barrido 0–1.
15. **`config.yaml` quedó vacío una vez** al editarlo con un script (causa no determinada; disco al 95 %). Se restauró desde git y desde entonces toda edición de la config usa escritura atómica y comprueba que el resultado no quede vacío. Conviene mantener disco libre.
16. **El equipo perdió la resolución DNS durante la fase.** Los modelos ya estaban en caché, por eso todo siguió funcionando. La Fase 6 (OpenAI) y la 5 (Anthropic) necesitan red: si vuelve a fallar hay que resolverlo antes.

17. **El umbral por similitud separa poco:** con estas similitudes comprimidas, el criterio F-β 0,5 elige 0,865 y pierde tres respuestas que sí se recuperaron bien (`q01`, `q08`, `q10`, entre 0,836 y 0,860), incluida la pregunta emblemática de la MYPE nueva. Como el LLM es una **segunda línea de defensa** (`contexto_suficiente`), quizá convenga un umbral más permisivo: se decidirá con `evaluation/eval_end_to_end.py` (unos 27 llamadas, ~centavos) cuando exista la clave.
18. **Los avisos de versión pueden ser varios:** un fragmento del DS 001 que transcribe un solo artículo dispara su aviso, pero varios fragmentos recuperados de la modificatoria disparan varios (hasta 4 en `q18`). Es correcto, pero la interfaz debería agruparlos.
19. **`tzdata` es necesario en Windows** (Python no trae base de zonas horarias del sistema): añadido a `requirements.txt`.

20. **Los límites de la capa gratuita (RPM/TPM/RPD) no son públicos en la documentación:** la página de límites dice que se ven en Google AI Studio (https://aistudio.google.com/rate-limit) y que «no están garantizados». El `rpm` de `config.yaml` es un valor de diseño; **conviene que la persona lo ajuste a lo que muestre su cuenta**.
21. **El contrato REST de Gemini se implementó contra la documentación, no contra una respuesta real exitosa:** solo se verificó con clave inválida (400). Riesgo principal: `responseJsonSchema` frente a `responseSchema` (configurable en `llm.proveedores.gemini.campo_esquema`). La primera llamada real lo confirma; un rechazo saldría como `error_tipo="solicitud"` con el mensaje de Google.
22. **Las páginas de Google se leyeron con una herramienta que resume el contenido** (no con el HTML crudo). Las cifras (USD 0,10 / 0,40; «Free of charge»; «Used to improve our products: Yes/No»; fechas de retiro) coinciden entre varias consultas, pero la persona debería contrastar la capa gratuita y los límites en su propio AI Studio antes de fiarse de ellos.
23. **La ficha de modelos y la de deprecaciones no coinciden en el ID de embeddings** (`gemini-embedding-2-preview` frente a `gemini-embedding-2`); la de deprecaciones dice que el preview se retiró el 2026-08-10, así que se usa `gemini-embedding-2`.
24. **Los precios de Gemini 3.6/3.7/3.8 Flash cambian por fecha** (31-dic-2026 → 1-ene-2027). La estructura de `pricing.yaml` es por hora del día, no por fecha: si se pasara a esos modelos habría que ampliarla. No afecta a `gemini-2.5-flash-lite`.
25. **Un test dependiente de red se colgó una vez** (`tiktoken` descarga su vocabulario): ahora usa un doble sin red. La suite completa corre en ~40 s sin conexión.
26. **En la capa gratuita Google puede usar lo enviado para mejorar sus productos.** Mitigación: solo se envían pregunta y normas públicas, hay aviso al usuario y los embeddings del índice son locales.
27. **La documentación de Google no es una fuente fiable de disponibilidad por cuenta:** la ficha decía «estable, sin retiro» para `gemini-2.5-flash-lite` y la API lo rechazó. Regla: **verificar con una llamada real** antes de fijar un modelo.
28. **La búsqueda aproximada de Chroma (HNSW) no era determinista con este corpus:** ver decisión de la búsqueda exacta. Las métricas de Recall ya publicadas no cambian, pero las respuestas podían variar entre ejecuciones.
29. **El 0,865 de la Fase 5 estaba mal calibrado para uso real:** se calibró viendo solo similitudes; con el LLM real descartaba respuestas correctas. Lección: calibrar umbrales con el pipeline completo.
30. **`o05` (etiquetada fuera de dominio) recibe una respuesta parcial y fundamentada** (Ley p. 17 y Reglamento p. 97 hablan de la capacidad máxima de contratación). No es una invención; es un problema de etiquetado del set. **Conviene que la persona revise `o05` en la validación de la Fase 3** (¿realmente está fuera del corpus indexado?).
31. **Cuota gratuita de embeddings de Gemini: 1000 solicitudes/día por modelo, cada texto cuenta** (cuerpo del 429: `EmbedContentRequestsPerDayPerProjectPerModel-FreeTier`, `quotaValue: 1000`). Indexar 1674 fragmentos + 21 consultas no cabe en un día: la comparación reanuda (960/1674 hoy). El 429 diario incluye un `retryDelay` de ~23 s pero no basta esperar segundos.
32. **El repo dentro de `~/Documents` (iCloud) vuelve a «desmaterializar» archivos** aunque haya 9,9 GB libres (303 archivos, incluidos objetos de `.git`), y entonces `check_secrets.py` y `git commit` se cuelgan. Se re-materializan con `find … -flags +dataless | xargs cat`. **Recomendación: mover el repo fuera de iCloud.** Se liberaron 6,17 GB borrando los blobs de modelos candidatos de Hugging Face (se conservó `multilingual-e5-small`, comprobado offline).
33. **Trabajo ahora en `~/dev/Homework`** (fuera de iCloud). La carpeta original `~/Documents/Github/Homework` conserva los mismos commits y el mismo árbol de trabajo hasta el commit `297dfbf`; **conviene borrarla o dejarla como respaldo para no editar dos copias**. Los 3 archivos del índice temporal `data/index_cmp` de Gemini (960/1674 fragmentos ya pagados con cuota) no se pudieron descargar de iCloud: si no se recuperan, mañana la comparación de Gemini reindexa desde cero (1000 textos/día).
34. **La interfaz no se ha visto en un navegador real** (no hay herramienta de captura en este entorno): se verificó con `AppTest`, con el servidor arrancando y con el contenido de cada elemento. Conviene que la persona la abra (`streamlit run app.py`) y revise el aspecto.
35. **Los pasos de PowerShell del README no se ejecutaron** (la máquina es macOS): se probaron sus equivalentes (venv limpio, instalación, tests, apertura). La URL del instalador de Tesseract para Windows y el ajuste `Set-ExecutionPolicy` se dan de memoria: verificarlos.
36. **El set de evaluación no tiene ninguna pregunta con cifras** (0 de 21), así que no puede medir la búsqueda por número de artículo, que es donde BM25 se espera fuerte. Se añadió una sonda sintética de 96 consultas generadas del índice (claramente separada del set). Conviene que la persona añada 3-5 preguntas con número de artículo o monto al validar el set.
37. **q04 y q07 son la brecha de vocabulario que nadie cierra:** q07 tiene el fragmento en el puesto 1 de BM25 pero en el 166 del semántico; q04 en los puestos 51 (semántico) y 58 (BM25). Una reescritura de la consulta con el LLM («contratos menores», «criterios de desempate») sería el siguiente paso, fuera del alcance de la fase.
38. **La generación con temperatura por defecto no es determinista:** la diferencia semántico/híbrido de punta a punta (18 frente a 17) es de una pregunta y una sola corrida por modo; no es concluyente. Las respuestas del semántico quedan en la caché (`eval/cache_llm/`, ignorada por git) para poder repetir sin gastar cuota.
39. **La simulación del CI encontró un fallo real que mi entorno ocultaba:** una prueba de la fábrica de LLM construía el cliente de Anthropic y exigía tener instalado el SDK (`anthropic`), que el CI no instala. Se corrigió con un doble del módulo. Lección: probar en un clon limpio con solo `requirements-ci.txt`.
40. **Las fechas de las páginas de releases de las acciones que devolvió la herramienta de lectura no son fiables** (daba 2024 para versiones que no existían entonces); por eso los mayores se verificaron con las etiquetas reales del repositorio (`git ls-remote`).
41. **El workflow solo se dispara con cambios en `tarea1/**` o en él mismo:** el repositorio aloja otras tareas y no deben gastar minutos de CI. El badge apunta a la rama `tarea1-rag` (en `main` no existe el workflow hasta hacer el merge).
42. **El workflow de la Fase 9 corrió en GitHub y salió verde a la primera** (`run 35677918111`, disparado por el push de las Fases 5-9): confirma que la simulación local del CI representaba bien el entorno real.
43. **La Fase 10 quedó completa en código y pruebas, pero SIN probarse con Telegram real:** falta el token. Un fallo posible que las pruebas no cubren: el formato exacto de un `Update` real de Telegram (aquí se construyó a mano según la documentación). La primera prueba con `scripts/run_telegram_bot.py` lo confirma.
44. **Hugging Face Spaces cambió su política de precios entre el plan original y hoy:** su documentación oficial dice ahora que crear un Space Docker en una cuenta personal exige el plan PRO (de pago); antes de este hallazgo, HF Spaces era la opción «obvia» que sugería el propio enunciado de la fase. Se le planteó a la persona y decidió Render.
45. **No hay `docker`, `node` ni `wrangler` en esta Mac de desarrollo** (ya se sabía por proyectos previos; confirmado de nuevo aquí). El `Dockerfile` y el Worker de Cloudflare se escribieron y se revisaron con pruebas ESTÁTICAS en Python (leen los archivos como texto, verifican invariantes concretas), pero **nunca se compilaron ni se ejecutaron**. La persona debe correr `docker build` y `wrangler dev`/`deploy` ella misma antes de confiar en que funcionan de verdad.
46. **No pude verificar con una fuente oficial la RAM exacta del plan gratuito de Render** (la documentación pública que revisé no la publica). Es un riesgo real para una imagen con PyTorch + el modelo de embeddings + ChromaDB; si el despliegue falla por memoria, la salida es una imagen más liviana o cambiar de host.
47. **El propio desarrollo ya superó el tope diario que se está configurando (100/día):** un día de pruebas reales de este proyecto generó 101 líneas en `logs/llm_calls.jsonl`. Es una señal de que 100 es un número razonable para un uso real (no artificialmente alto), pero también de que hay que vigilar el archivo si se sigue desarrollando activamente sobre la misma app desplegada.
48. **No pude confirmar con una fuente oficial la RAM exacta de Streamlit Community Cloud** (igual que con Render en la Fase 11). Lo que sí es un dato real y medido: el modelo de embeddings local por sí solo ya ocupa 883 MB. Si el despliegue falla, la salida (cambiar a embeddings de Gemini) ya está implementada y probada, no es trabajo nuevo.
49. **`requirements.txt` estaba truncado desde la Fase 7** (26 líneas en vez de 43): la misma corrupción de iCloud que truncó el README en su momento (y se corrigió entonces) también cortó `requirements.txt` a media palabra, borrando `streamlit`, `pandas`, `fastapi`, `uvicorn`, `httpx` y `matplotlib` — **sin que ningún test lo notara**, porque ninguna prueba ejecuta `pip install -r requirements.txt`. Lo encontró la auditoría final de la Fase 13 (paso «instalación limpia siguiendo el README»), siguiendo el propio proceso que describe el enunciado. Se corrigió y se agregó una prueba (`test_requirements_txt_no_quedo_truncado_...`) para que no vuelva a pasar inadvertido. `requirements-ci.txt` y `requirements-backend.txt` SÍ estaban completos (son archivos separados, no los tocó la misma corrupción).

## Checklist final (Fase 13)

**Arquitectura**
- [x] Offline/online separados (el motor nunca abre un PDF; test `test_el_motor_no_abre_pdfs`).
- [x] Una función `responder()` (`rag_engine.engine.responder`), usada por `app.py`, el bot de Telegram y `interfaces/api_server.py`.
- [x] El motor sin imports de UI (`grep` → 0 coincidencias, verificado en la auditoría de arriba).
- [x] `config.yaml` (toda la configuración) y `.env` (solo credenciales, `.env.example` sin valores).
- [x] Log de costos (`logs/llm_calls.jsonl`, costo real y de referencia).
- [x] Diagrama Mermaid (offline vs online) en el README.

**Extracción y OCR**
- [x] 3 PDFs con fecha y hash (`data/raw/MANIFEST.json`).
- [x] Página como metadato desde el primer paso (un JSON por página).
- [x] OCR con motor justificado (Tesseract, 200 DPI, con datos de `eval/results/ocr_benchmark.md`).
- [x] Subconjunto de 60+ páginas documentado (75 páginas del Reglamento, `docs/ocr_subset.md`).
- [x] OCR reanudable (probado con una interrupción real, Ctrl+C).
- [x] Limpieza de encabezados (`docs/limpieza_encabezados.md`).
- [x] Reporte de calidad y orden de lectura (`docs/reading_order_check.md`, pestaña Calidad de extracción de la app).

**Índice**
- [x] 2+ configuraciones de troceado comparadas (6 configuraciones, `eval/results/chunking_comparacion.md`).
- [x] Metadatos completos por fragmento (documento, versión, página, encabezado, artículos mencionados, hash).
- [x] IDs estables e índice idempotente probado (build dos veces seguidas, `nuevos=0` la segunda vez).
- [x] Prefijos y longitud máxima reportados (`docs/modelos_embeddings.md`; 0 fragmentos truncados con la config activa).
- [x] Distribución de fragmentos por documento reportada (427 / 1042 / 205).

**Motor**
- [x] Abstención antes del LLM y umbral calibrado (0,835, con el LLM real).
- [x] Manejo de versiones (bidireccional, `docs/ejemplo_versiones.md`).
- [x] Citas (documento + página, verificadas contra las fuentes recuperadas).
- [x] `abstuvo` estructurado (nunca inferido del texto; test `test_una_respuesta_que_dice_no_se_pero_marca_suficiente_no_es_abstencion`).
- [x] Errores como errores (`error` + `error_tipo`, nunca una respuesta normal).
- [x] Precio por hora (estructura de ventanas horarias, probada con una tabla ficticia pico/valle).

**Evaluación**
- [~] 15+5 preguntas válidas: el set tiene 21 in_domain + 6 out_of_domain, pero **no está validado por la persona** (Fase 3, [MANUAL] pendiente).
- [x] Recall@1/3/5 y abstención sin LLM (`run_eval.py`, sin costo).
- [x] Comparación local vs API con recomendación (el modelo local, con RAM medida como su único costo real).

**Streamlit**
- [x] Corre en limpio en Windows *(sin probar en Windows real; sí en macOS, ver auditoría)* sin reconstruir el índice.
- [x] Muestra respuesta, citas, abstención, costo y paneles (Consulta, Calidad de extracción, Evaluación, Costos).

**Innovación**
- [~] Telegram: código y pruebas completos; **sin probar con un bot real** (falta el token, [MANUAL]).
- [~] Worker 24/7: código, Dockerfile y pruebas estáticas completos; **sin compilar ni desplegar** (sin docker/node/wrangler en esta máquina).
- [x] GitHub Actions con fallo demostrado (verde y rojo, enlaces arriba).
- [x] BM25 vs semántica (Fase 8, con sonda de números de artículo).
- [~] Despliegue público con topes: topes de gasto implementados y probados; **sin desplegar de verdad** ([MANUAL]).

**Entrega**
- [x] Repo público (`RenataZuta/Homework`), verificado desde la Fase 0.
- [x] Commits distribuidos por fase (más de 20 commits en `tarea1-rag`).
- [x] Sin credenciales en el historial (`check_secrets.py` sobre `git log -p`, 0 hallazgos).
- [ ] Registrar el repositorio en la hoja de cálculo del issue — lo hace la persona.

# Tarea 1 — RAG normativo de contrataciones públicas del Perú

Asistente que responde preguntas sobre la **Ley 32069**, su **Reglamento (DS 009-2025-EF, subconjunto con OCR)** y la **modificatoria DS 001-2026-EF**,
citando documento y página. Repositorio: `RenataZuta/Homework`, rama `tarea1-rag`, carpeta `tarea1/`.

> **Estado:** en desarrollo por fases; el estado exacto y las decisiones están en [`PROGRESO.md`](PROGRESO.md). Este README se completa en la Fase 13
> (diagrama Mermaid del pipeline, pasos de instalación en Windows PowerShell, notas del video). Lo que ya está aquí describe **proveedores, costos, límites y privacidad**.

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

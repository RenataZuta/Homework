# Notas para el video (Fase 13) — guion con los números reales del proyecto

Máximo 12 minutos. Regla: **pipeline antes que código** (mostrar qué hace el sistema y por qué, no leer líneas de código sin contexto). Todos los números de aquí
son reales, medidos, con su fuente — nunca inventados; están tomados de `PROGRESO.md` y `eval/results/`.

## Estructura sugerida (12 min)

### 1. El problema (1 min)
El dueño de una micro o pequeña empresa que quiere venderle al Estado tiene que leer tres documentos largos y en lenguaje jurídico: la Ley 32069, su Reglamento
(DS 009-2025-EF) y una modificatoria reciente (DS 001-2026-EF) que cambia 105 artículos del Reglamento. El asistente responde en su propio lenguaje, citando
documento y página, y **dice cuándo no sabe** en vez de inventar.

### 2. El pipeline de la Tarea 1 — SOLO el diagrama (1-2 min)
Mostrar el diagrama Mermaid del README (`## Arquitectura`) y explicar, sin código todavía:
- **Offline** (se corre a mano cuando cambian las normas): PDF → una página = un JSON (**la página es metadato desde el primer paso**, nunca texto unido y
  troceado después — si se hiciera al revés, se perdería para siempre qué página originó cada frase) → troceado → índice.
- **Online** (responde preguntas, nunca abre un PDF): pregunta → **compuerta del umbral** (¿el mejor coseno recuperado llega a 0,835? si no, se abstiene con
  costo 0, sin llamar al LLM) → si hay artículos modificados, se fuerza el texto de la modificatoria → LLM (Gemini, capa gratuita) → el LLM declara
  `contexto_suficiente` como un CAMPO, no como texto a interpretar → respuesta con citas, o segunda abstención.
- **Dónde exactamente el sistema decide no llamar al LLM:** dos puntos, no uno — la compuerta del umbral (antes de cualquier llamada) y el propio LLM (después,
  con el campo `contexto_suficiente`). Mostrar ambos con un ejemplo real: una pregunta ajena («¿cómo se prepara un ceviche?») que se abstiene en la compuerta
  (similitud 0,795, por debajo de 0,835, **cero líneas en `logs/llm_calls.jsonl`**) y una pregunta límite que pasa la compuerta pero el LLM abstiene igual.

### 3. Decisiones técnicas, con sus tablas (3-4 min)
No leer las tablas completas: decir la conclusión y el número que la sostiene. Todas están en el README («Resultados» y «Justificación»):
- **OCR:** Tesseract, no EasyOCR — 620 palabras correctas/página frente a 276, 6,7× más rápido (`eval/results/ocr_benchmark.md`).
- **Troceado:** `c750_o100` con contexto de encabezado — R@3 0,905 frente a 0,857 sin el contexto (el título del artículo heredado de la página anterior).
- **Modelo de embeddings:** local (`multilingual-e5-small`) — USD 0, pero **883 MB de RAM medidos** (el dato que llevó a elegir dónde desplegar la app pública).
- **Umbral:** 0,835, calibrado con el LLM real, no solo con similitudes (el primer umbral, 0,865, descartaba 2 respuestas buenas).
- **BM25 frente a semántica:** semántico gana en preguntas coloquiales (R@3 0,818 frente a 0,455) porque la gente no usa el vocabulario de la ley; BM25 gana
  en números de artículo (sonda sintética: R@3 0,844 frente a 0,448) porque «114» es un término exacto que un embedding casi no distingue.
- **Proveedor de LLM:** Gemini, capa gratuita — decisión de la persona («no pagar nada adicional»); `gemini-2.5-flash-lite` fue rechazado por la API real
  aunque la documentación lo decía «estable»: verificar con una llamada real, no solo leer la documentación.

### 4. Demo en vivo (2-3 min)
- Una pregunta del dominio → respuesta con citas, ver los fragmentos recuperados (documento, página, similitud) en la pestaña Consulta.
- Una pregunta ajena → el caso de abstención, mostrando `mejor_similitud` por debajo del umbral.
- Una pregunta sobre un artículo modificado por el DS 001 → el aviso de versión.
- (Si ya está desplegado) la app pública, el bot de Telegram, o ambos.

### 5. Código — solo 2 o 3 partes (2 min)
- `rag_engine/engine.py::responder()`: la ÚNICA función; recorrer las 5 líneas de la compuerta del umbral y mostrar que el campo `abstuvo` nunca se
  deduce del texto.
- `interfaces/telegram_handlers.py` o `app.py`: cómo una interfaz llama a esa misma función, sin importar nada del motor al revés (mostrar el comando
  `grep -rnE "streamlit|telegram|fastapi|flask|gradio" src/rag_engine` → 0 coincidencias).
- (Opcional) `retrieval/bm25.py` o `llm/limites.py`: una pieza que se sienta orgullosa, en 30 segundos.

### 6. Hallazgos, límites y costo real (2 min)
- **Hallazgo real más interesante:** `requirements.txt` estuvo truncado desde la Fase 7 por una corrupción de iCloud — nadie lo notó porque ningún test corre
  `pip install`. Lo encontró la propia auditoría final, siguiendo el README paso a paso. (Buena historia: "seguir tu propio proceso de verificación encontró
  un bug real que el código nunca iba a encontrar por sí solo".)
- **Costo real de todo el proyecto:** 110 llamadas al LLM, **USD 0 reales** (capa gratuita) — **USD 0,000697 por consulta** de referencia (lo que costaría de
  pago). Cómo se sabe: cada llamada se registra en `logs/llm_calls.jsonl` con su costo real y de referencia; nunca se infiere ni se estima.
- **Límites honestos:** el set de evaluación (21 preguntas) no está validado por la persona todavía; el Dockerfile y el Worker nunca se compilaron (sin
  docker/node/wrangler en la máquina de desarrollo); los pasos de Windows no se probaron en Windows.

---

## Qué mide cada métrica (para no confundirlas en el video)

- **Recall@k:** ¿la página esperada está entre los k fragmentos más parecidos? Mide SOLO la recuperación (troceado + embeddings + índice), nunca la calidad
  de la respuesta del LLM. Real: R@1/3/5 = 0,762 / 0,905 / 0,905.
- **Tasa de abstención:** ¿el sistema se calla cuando debería? Se mide en dos capas por separado: la compuerta del umbral (antes del LLM, gratis) y el LLM
  (con `contexto_suficiente`, después). Real: de punta a punta, 5/6 preguntas ajenas rechazadas, 18/21 del dominio respondidas.
- **Costo por consulta:** se sabe porque CADA llamada real al LLM se registra (nunca se estima): `costo_usd_real` (lo que se cobra, 0 en la capa gratuita) y
  `costo_usd_referencia` (lo que costaría de pago, con el precio verificado en la documentación oficial y su fecha).

## Fase 11: bot 24/7 con Cloudflare Worker + backend (nota técnica que puede ir en la sección 3 o 6)

**Realidad técnica que hay que explicar:** un Worker de Cloudflare **no puede** ejecutar el motor. Su runtime (V8, aislado, sin filesystem persistente) no
corre `sentence-transformers` (necesita PyTorch) ni ChromaDB. Por eso la arquitectura tiene dos piezas, no una:

```
Telegram → Worker de Cloudflare (gateway del webhook) → backend (FastAPI, siempre encendido, con el motor) → Telegram
```

El Worker es liviano y gratis (100 000 peticiones/día en el plan gratuito) y solo hace de portero: valida que la petición venga de verdad de Telegram
(`X-Telegram-Bot-Api-Secret-Token`), responde `200` de inmediato (para que Telegram no reintente) y reenvía el mensaje al backend con `ctx.waitUntil(...)`.
El backend es el que **reemplaza a la laptop**: tiene el índice y el modelo cargados y corre `responder()`, el mismo motor de todas las fases anteriores.

**Mostrar en el video (si ya está desplegado):**
1. El diagrama, explicado con las palabras de por qué el Worker no puede hacer el trabajo pesado.
2. `interfaces/api_server.py`: dos rutas nada más, `/health` (sin autenticación) y `/telegram/webhook` (exige `X-Internal-Key`, un secreto que SOLO conocen
   el Worker y el backend — no es el token del bot).
3. `cloudflare_worker/src/index.js`: la validación del secreto, el `ctx.waitUntil`, y el aviso de «me estoy despertando» cuando el backend tardó.
4. Un mensaje real llegando con la laptop apagada: la prueba de que el backend, no la máquina de desarrollo, es quien responde.
5. **Limitación honesta:** en este entorno de desarrollo no había `node`/`docker`/`wrangler` instalados, así que el `Dockerfile` y el Worker se escribieron y
   se revisaron con pruebas estáticas (en Python, leyendo los archivos), no se compilaron ni se desplegaron desde aquí. Decirlo así en el video, sin maquillarlo.

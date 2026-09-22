# Notas para el video (Fase 13, borrador que crece por fase)

Un lugar para anotar, fase por fase, qué mostrar y qué explicar en el video final. Se completa al terminar cada fase; el guion final se arma en la Fase 13.

## Fase 11: bot 24/7 con Cloudflare Worker + backend

**Realidad técnica que hay que explicar (no es un detalle menor, es la razón de ser de esta fase):** un Worker de Cloudflare **no puede** ejecutar el motor. Su runtime (V8, aislado, sin filesystem persistente) no corre `sentence-transformers` (necesita PyTorch) ni `ChromaDB`. Por eso la arquitectura tiene dos piezas, no una:

```
Telegram → Worker de Cloudflare (gateway del webhook) → backend (FastAPI, siempre encendido, con el motor) → Telegram
```

El Worker es liviano y gratis (100 000 peticiones/día en el plan gratuito) y solo hace de portero: valida que la petición venga de verdad de Telegram (`X-Telegram-Bot-Api-Secret-Token`), responde `200` de inmediato (para que Telegram no reintente) y reenvía el mensaje al backend con `ctx.waitUntil(...)`. El backend es el que **reemplaza a mi laptop**: tiene el índice y el modelo cargados y corre `responder()`, el mismo motor de todas las fases anteriores.

**Mostrar en el video:**
1. El diagrama de arriba, explicado con las palabras de por qué el Worker no puede hacer el trabajo pesado.
2. `interfaces/api_server.py`: dos rutas nada más, `/health` (sin autenticación, para que el host compruebe que sigue vivo) y `/telegram/webhook` (exige `X-Internal-Key`, un secreto que SOLO conocen el Worker y el backend — no es el token del bot).
3. `cloudflare_worker/src/index.js`: la validación del secreto, el `ctx.waitUntil`, y el aviso de «me estoy despertando» cuando el backend tardó (arranque en frío del plan gratuito de Render).
4. Un mensaje real llegando con la laptop apagada (o al menos sin `scripts/run_telegram_bot.py` corriendo): la prueba de que el backend, no mi máquina, es quien responde.
5. **Limitación honesta:** en este entorno de desarrollo no había `node`/`docker`/`wrangler` instalados, así que el `Dockerfile` y el Worker se escribieron y se revisaron con pruebas estáticas (en Python, leyendo los archivos), no se compilaron ni se desplegaron desde aquí. Decirlo así en el video, sin maquillarlo.

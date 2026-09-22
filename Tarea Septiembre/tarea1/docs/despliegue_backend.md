# Cómo desplegar el backend 24/7 y el Worker de Cloudflare (Fase 11) [MANUAL]

Todo esto necesita cuentas y comandos que **debes** ejecutar tú (Cloudflare, Render, `wrangler login`, `wrangler deploy`, y cargar los
secretos). Yo nunca te pido pegarme una credencial en el chat, y nunca las guardo en un archivo del repositorio.

## 0. Antes de empezar
- Ya tienes el bot funcionando por **polling** (Fase 10, `scripts/run_telegram_bot.py`) con tu `TELEGRAM_BOT_TOKEN` y
  `TELEGRAM_ALLOWED_USER_IDS` en `.env`.
- **No pude probar el `Dockerfile` ni el Worker en este entorno** (no hay `docker`, `node` ni `wrangler` instalados en esta Mac).
  Revísalos tú con los comandos de abajo antes de confiar en ellos.

## 1. Backend en Render (plan gratuito, sin tarjeta)
1. Crea una cuenta en <https://render.com> (gratis, sin tarjeta).
2. **New → Web Service**, conecta tu repositorio de GitHub, rama `main`, **Root Directory: `Tarea Septiembre/tarea1`**, entorno **Docker**
   (Render detecta el `Dockerfile`).
3. En **Environment**, agrega las variables (Render las guarda cifradas; nunca van al repositorio):
   `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_IDS`, y genera un valor al azar para `BACKEND_INTERNAL_KEY`
   (por ejemplo, en tu terminal: `python -c "import secrets; print(secrets.token_urlsafe(32))"`, pégalo aquí y **guárdalo
   también en tu propio `.env` local** con `python scripts/set_env_key.py BACKEND_INTERNAL_KEY`, porque el Worker de Cloudflare
   necesita el mismo valor).
4. Deploy. El build tarda varios minutos (instala PyTorch CPU, descarga el modelo de embeddings y construye el índice).
5. Verifica: `curl https://tu-servicio.onrender.com/health` debe responder `{"status":"ok"}`.
6. **Riesgo conocido:** no pude confirmar con una fuente oficial la RAM exacta del plan gratuito de Render. Si el build o el
   arranque fallan por falta de memoria, avísame: la alternativa es una imagen más liviana o un host con más memoria garantizada
   (ver PROGRESO.md, Fase 11, para las opciones que se descartaron y por qué).

## 2. Worker de Cloudflare
1. Crea una cuenta gratuita en <https://dash.cloudflare.com/sign-up> (el plan gratuito de Workers no pide tarjeta).
2. Instala Node.js (18+) y, desde `tarea1/cloudflare_worker/`:
   ```
   npm install -g wrangler
   wrangler login          # abre el navegador para autorizar
   ```
3. Carga los secretos UNO POR UNO (piden el valor por teclado; Cloudflare los guarda cifrados, nunca en un archivo):
   ```
   wrangler secret put TELEGRAM_WEBHOOK_SECRET
   wrangler secret put BACKEND_URL
   wrangler secret put BACKEND_INTERNAL_KEY
   wrangler secret put TELEGRAM_BOT_TOKEN
   ```
   - `TELEGRAM_WEBHOOK_SECRET`: invéntate una cadena al azar (1-256 caracteres, letras/números/`_`/`-`); Telegram la reenvía en
     cada petición y el Worker la valida.
   - `BACKEND_URL`: la URL de Render del paso 1 (sin `/telegram/webhook` al final, el Worker lo agrega).
   - `BACKEND_INTERNAL_KEY`: el mismo valor que pusiste en Render.
   - `TELEGRAM_BOT_TOKEN`: el mismo token del bot (lo necesita para avisar «me estoy despertando» — ver `PROGRESO.md`, es una
     desviación del plan original justificada ahí).
4. `wrangler deploy` — publica el Worker y te da su URL (`https://contrataciones-telegram-webhook.<tu-cuenta>.workers.dev`).

## 3. Registrar el webhook
```
python scripts/set_webhook.py https://contrataciones-telegram-webhook.<tu-cuenta>.workers.dev
```

## 4. Prueba de punta a punta con la laptop apagada
- [ ] Cierra `scripts/run_telegram_bot.py` si estaba corriendo (para que no compita con el webhook).
- [ ] **Apaga o desconecta esta laptop** (o al menos ciérrala) y, desde tu teléfono, escríbele al bot.
- [ ] Debe responder con citas (puede tardar hasta un minuto la primera vez, si Render estaba dormido; el Worker avisa
      «Estoy despertando el servicio…»).
- [ ] Una petición SIN el `secret_token` correcto a la URL del Worker debe dar 401 o 403 (pruébalo con `curl`, sin la cabecera).
- [ ] Vuelve a encender la laptop y avísame el resultado; actualizo `PROGRESO.md` con la evidencia real.

## Para volver a polling (desarrollo)
```
python scripts/set_webhook.py --borrar
python scripts/run_telegram_bot.py
```

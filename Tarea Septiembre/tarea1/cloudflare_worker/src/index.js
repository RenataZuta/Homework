/**
 * Worker de Cloudflare: gateway del webhook de Telegram (Fase 11).
 *
 * Telegram -> ESTE Worker -> backend (FastAPI, siempre encendido) -> responde al chat.
 * El Worker NO puede correr el motor (sentence-transformers + ChromaDB no funcionan en su runtime); solo hace de puerta:
 *   1. Valida la cabecera "X-Telegram-Bot-Api-Secret-Token" (la fija Telegram con el valor de scripts/set_webhook.py).
 *   2. Responde 200 a Telegram DE INMEDIATO (Telegram reintenta si no recibe 200 pronto: no hay que hacerlo esperar
 *      al backend, que puede tardar unos segundos en generar la respuesta o, si estaba dormido, hasta un minuto en despertar).
 *   3. Reenvía el update al backend con ctx.waitUntil(...) (sigue corriendo hasta 30 s después de responder, en el plan gratuito).
 *   4. Si el backend no contesta a tiempo (probable arranque en frío del plan gratuito de Render), el Worker mismo le avisa
 *      al usuario por Telegram y reintenta una vez más antes de rendirse.
 *
 * Secretos (nunca en este archivo): TELEGRAM_WEBHOOK_SECRET, BACKEND_URL, BACKEND_INTERNAL_KEY, TELEGRAM_BOT_TOKEN.
 * TELEGRAM_BOT_TOKEN es una desviación deliberada del plan original (que solo mencionaba los otros tres): sin él, el
 * Worker no podría enviar el aviso de "despertando" cuando el backend tarda (ver PROGRESO.md, Fase 11).
 */

// Debe decir EXACTAMENTE lo mismo que mensajes.bot.backend_despertando en config.yaml (una prueba en Python lo verifica:
// tests/test_cloudflare_worker.py). No hay forma de que este Worker (JavaScript) lea el YAML de Python.
const MENSAJE_DESPERTANDO = "Estoy despertando el servicio, puede tardar un momento. Te respondo apenas esté listo.";

export default {
  async fetch(request, env, ctx) {
    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405 });
    }
    if (request.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.TELEGRAM_WEBHOOK_SECRET) {
      return new Response("Forbidden", { status: 403 });
    }
    let update;
    try {
      update = await request.json();
    } catch (err) {
      return new Response("Bad Request", { status: 400 });
    }
    ctx.waitUntil(reenviarConAviso(update, env));
    return new Response("OK", { status: 200 });           // Telegram no espera al backend
  },
};

async function reenviarConAviso(update, env) {
  try {
    await reenviarAlBackend(update, env, 8000);
    return;                                               // el backend ya estaba despierto: nada más que hacer aquí
  } catch (primerError) {
    console.log(`Primer intento al backend falló (${primerError}); avisando y reintentando`);
  }
  await avisarDespertando(update, env);
  try {
    await reenviarAlBackend(update, env, 18000);
  } catch (segundoError) {
    console.log(`Segundo intento al backend también falló: ${segundoError}`);
    // Se agota el presupuesto de ctx.waitUntil (30 s en el plan gratuito): el mensaje del usuario queda sin responder
    // esta vez. Ya se le avisó que el servicio estaba despertando; puede reintentar en un minuto.
  }
}

async function reenviarAlBackend(update, env, timeoutMs) {
  const respuesta = await fetch(`${env.BACKEND_URL}/telegram/webhook`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Internal-Key": env.BACKEND_INTERNAL_KEY },
    body: JSON.stringify(update),
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!respuesta.ok) {
    throw new Error(`el backend respondió HTTP ${respuesta.status}`);
  }
}

function chatIdDe(update) {
  return update?.message?.chat?.id ?? update?.callback_query?.message?.chat?.id ?? null;
}

async function avisarDespertando(update, env) {
  const chatId = chatIdDe(update);
  if (!chatId) return;                                    // p. ej. un callback_query sin mensaje asociado: no hay a quién avisarle
  try {
    await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, text: MENSAJE_DESPERTANDO }),
      signal: AbortSignal.timeout(5000),
    });
  } catch (err) {
    console.log(`No se pudo avisar que el backend está despertando: ${err}`);
  }
}

"""api_server.py — backend FastAPI de la Fase 11: SIEMPRE encendido, reemplaza a la laptop.

Arquitectura (documentada también en el README): Telegram -> Worker de Cloudflare (valida el secreto del webhook, responde 200 de
inmediato) -> ESTE backend (valida una clave interna compartida solo con el Worker) -> ``interfaces.telegram_handlers`` (el mismo
código de la Fase 10) -> responde al chat llamando directamente a la Bot API. El Worker NO puede ejecutar el motor
(sentence-transformers + ChromaDB no corren en el runtime de Cloudflare); por eso existe este backend.

Dos rutas, nada más:
  * ``GET /health``: sin autenticación, no toca el motor ni la base de datos (una probe barata para el proveedor de hosting).
  * ``POST /telegram/webhook``: exige la cabecera ``X-Internal-Key`` (compartida solo con el Worker; NUNCA es el token de Telegram).
    Responde de inmediato y procesa el update en segundo plano (``BackgroundTasks``): el Worker ya le respondió 200 a Telegram,
    así que nada espera esta respuesta salvo el propio Worker, y no conviene bloquearlo con la latencia del LLM.
Uso local (desde tarea1/):  uvicorn interfaces.api_server:app --reload
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request

from interfaces import bot_store, telegram_handlers
from interfaces.telegram_api import ClienteTelegram
from rag_engine.config import cargar_config

ESTADO: dict = {}                    # cfg, conn, cliente, permitidos, clave_interna — se llenan al arrancar (lifespan), no por request


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = cargar_config()
    ESTADO["cfg"] = cfg
    ESTADO["ruta_db"] = cfg.ruta("bot_db")
    bot_store.abrir_db(ESTADO["ruta_db"]).close()         # crea el archivo y el esquema si hace falta; NO se guarda la conexión
    ESTADO["cliente"] = ClienteTelegram(cfg.requerir_env("TELEGRAM_BOT_TOKEN", para="el bot de Telegram"))
    ESTADO["permitidos"] = telegram_handlers.usuarios_permitidos(cfg)
    ESTADO["clave_interna"] = cfg.requerir_env("BACKEND_INTERNAL_KEY", para="validar las peticiones del Worker de Cloudflare")
    try:
        yield
    finally:
        ESTADO.clear()


app = FastAPI(title="Backend del asistente de contrataciones públicas (Fase 11)", lifespan=lifespan)


@app.get("/health")
def salud() -> dict:
    return {"status": "ok"}


def _procesar_en_segundo_plano(update: dict) -> None:
    """Corre en un hilo del pool de FastAPI (BackgroundTasks despacha las funciones síncronas ahí): abre SU PROPIA conexión
    SQLite (sqlite3.Connection no se puede compartir entre hilos) y la cierra al terminar."""
    conn = bot_store.abrir_db(ESTADO["ruta_db"])
    try:
        telegram_handlers.procesar_update(update, ESTADO["cfg"], conn, ESTADO["cliente"], ESTADO["permitidos"])
    except Exception as exc:                              # un update raro no debe tumbar el proceso ni quedar sin registrar
        print(f"Error procesando un update de Telegram: {type(exc).__name__}: {exc}")
    finally:
        conn.close()


@app.post("/telegram/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks,
                  x_internal_key: Annotated[str | None, Header(alias="X-Internal-Key")] = None) -> dict:
    if x_internal_key != ESTADO["clave_interna"]:
        raise HTTPException(status_code=403, detail="clave interna inválida")               # nunca se repite el valor recibido
    try:
        update = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="cuerpo no es JSON válido") from None
    if not isinstance(update, dict):
        raise HTTPException(status_code=400, detail="se esperaba un objeto Update de Telegram")
    background_tasks.add_task(_procesar_en_segundo_plano, update)
    return {"ok": True}

"""feedback_summary.py — resumen del feedback (👍/👎) del bot de Telegram, para la app Streamlit (pestaña Costos).

Lee data/bot.db (SQLite, ignorada por git: contiene IDs de usuarios de Telegram, un dato personal) y escribe
eval/results/feedback_resumen.{csv,md}. Si el archivo no existe (todavía no hubo bot en uso), lo dice y no falla.
Uso (desde tarea1/):  PYTHONPATH=src python -m evaluation.feedback_summary
"""
from __future__ import annotations

import sys
from pathlib import Path

from evaluation.informes import escribir_atomico, escribir_csv, tabla_markdown
from interfaces import bot_store
from rag_engine.config import cargar_config


def resumir(filas: list[dict]) -> dict:
    positivos = sum(f["valor"] == 1 for f in filas)
    negativos = sum(f["valor"] == -1 for f in filas)
    return {"votos": len(filas), "positivos": positivos, "negativos": negativos,
            "pct_positivo": round(positivos / len(filas), 3) if filas else None,
            "abstenciones_calificadas": sum(f["abstuvo"] for f in filas), "errores_calificados": sum(bool(f["error"]) for f in filas)}


def main() -> int:
    cfg = cargar_config(cargar_env=False)
    ruta_db, salida = cfg.ruta("bot_db"), cfg.ruta("eval_results")
    if not ruta_db.is_file():
        print(f"No hay {ruta_db.name} todavía (el bot no se ha usado en este entorno). Nada que resumir.")
        return 0
    conn = bot_store.abrir_db(ruta_db)
    filas = bot_store.todo_el_feedback(conn)
    resumen = resumir(filas)
    escribir_csv(salida / "feedback_resumen.csv",
                [{k: v for k, v in f.items() if k in ("feedback_id", "valor", "feedback_timestamp", "abstuvo", "pregunta")} for f in filas])
    cols = [("pregunta", "Pregunta", ""), ("valor", "Voto", ""), ("abstuvo", "Abstención", ""), ("feedback_timestamp", "Cuándo", "")]
    md = ["# Feedback del bot de Telegram", ""]
    if not filas:
        md += ["Todavía no hay votos registrados.", ""]
    else:
        md += [f"**{resumen['votos']} votos** ({resumen['positivos']} 👍, {resumen['negativos']} 👎; "
               f"{resumen['pct_positivo']:.0%} positivo). {resumen['abstenciones_calificadas']} calificaron una abstención "
               f"y {resumen['errores_calificados']} un error.", "", tabla_markdown(filas, cols), ""]
    escribir_atomico(salida / "feedback_resumen.md", "\n".join(md))
    print(f"Escrito {salida / 'feedback_resumen.md'} ({resumen['votos']} votos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

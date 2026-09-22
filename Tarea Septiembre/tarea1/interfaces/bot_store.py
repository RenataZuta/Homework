"""Almacén SQLite del bot de Telegram: consultas, límite diario y feedback (👍/👎).

Dos tablas, como pide la Fase 10:
  * ``consultas``: una fila por pregunta procesada (respondida, abstención o error), con lo necesario para /fuente y /costo.
  * ``feedback``: un voto por (consulta, usuario); votar dos veces actualiza el voto, no lo duplica.
Todos los timestamps se guardan YA en la zona horaria de ``bot.zona_horaria_limite`` (la pasa quien llama): así el límite diario usa
el prefijo de fecha del propio timestamp, sin depender de la zona horaria del sistema donde corre el bot.
El ID de la BASE DE DATOS es el que codifica el feedback (compacto: cabe en los 64 bytes de un ``callback_data`` de Telegram).
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS consultas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    pregunta TEXT NOT NULL,
    respuesta TEXT,
    abstuvo INTEGER NOT NULL,
    error TEXT,
    fuentes_json TEXT NOT NULL,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    costo_usd_real REAL NOT NULL DEFAULT 0,
    costo_usd_referencia REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_consultas_usuario ON consultas(user_id, id DESC);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    consulta_id INTEGER NOT NULL REFERENCES consultas(id),
    user_id INTEGER NOT NULL,
    valor INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    UNIQUE(consulta_id, user_id)
);
"""


@dataclass(frozen=True)
class Fuente:
    documento: str
    pagina: int
    similitud: float
    texto: str
    citada: bool


def abrir_db(ruta: Path) -> sqlite3.Connection:
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ruta)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(ESQUEMA)
    conn.commit()
    return conn


def registrar_consulta(conn: sqlite3.Connection, user_id: int, pregunta: str, r, momento: datetime) -> int:
    """``r`` es un ``ResultadoRAG``. Devuelve el ID autoincremental (lo que va en ``callback_data`` del feedback)."""
    fuentes = [Fuente(f.documento, f.pagina, f.similitud, f.texto, f.citada).__dict__ for f in r.fuentes]
    cur = conn.execute(
        "INSERT INTO consultas (user_id, timestamp, pregunta, respuesta, abstuvo, error, fuentes_json, tokens_in, tokens_out, costo_usd_real, costo_usd_referencia) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, momento.isoformat(timespec="seconds"), pregunta, r.respuesta, int(bool(r.abstuvo)), r.error,
         json.dumps(fuentes, ensure_ascii=False), r.tokens_entrada, r.tokens_salida, r.costo_usd_real, r.costo_usd_referencia))
    conn.commit()
    return cur.lastrowid


def _fila_a_dict(fila: sqlite3.Row) -> dict:
    d = dict(fila)
    d["fuentes"] = json.loads(d.pop("fuentes_json"))
    d["abstuvo"] = bool(d["abstuvo"])
    return d


def ultima_consulta(conn: sqlite3.Connection, user_id: int) -> dict | None:
    fila = conn.execute("SELECT * FROM consultas WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
    return _fila_a_dict(fila) if fila else None


def consulta_por_id(conn: sqlite3.Connection, consulta_id: int) -> dict | None:
    fila = conn.execute("SELECT * FROM consultas WHERE id = ?", (consulta_id,)).fetchone()
    return _fila_a_dict(fila) if fila else None


def consultas_de_hoy(conn: sqlite3.Connection, user_id: int, ahora: datetime) -> int:
    """Cuántas consultas registró ``user_id`` en la misma fecha (prefijo ``YYYY-MM-DD``) que ``ahora``, YA en la zona horaria del límite."""
    hoy = ahora.date().isoformat()
    fila = conn.execute("SELECT COUNT(*) AS n FROM consultas WHERE user_id = ? AND substr(timestamp, 1, 10) = ?", (user_id, hoy)).fetchone()
    return fila["n"]


def resumen_dia(conn: sqlite3.Connection, user_id: int, ahora: datetime) -> dict:
    hoy = ahora.date().isoformat()
    fila = conn.execute(
        "SELECT COUNT(*) AS consultas, COALESCE(SUM(costo_usd_real), 0) AS costo_real, COALESCE(SUM(costo_usd_referencia), 0) AS costo_referencia "
        "FROM consultas WHERE user_id = ? AND substr(timestamp, 1, 10) = ?", (user_id, hoy)).fetchone()
    return dict(fila)


def registrar_feedback(conn: sqlite3.Connection, consulta_id: int, user_id: int, valor: int, momento: datetime) -> None:
    if valor not in (1, -1):
        raise ValueError(f"valor de feedback inválido: {valor!r} (debe ser 1 o -1)")
    conn.execute(
        "INSERT INTO feedback (consulta_id, user_id, valor, timestamp) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(consulta_id, user_id) DO UPDATE SET valor = excluded.valor, timestamp = excluded.timestamp",
        (consulta_id, user_id, valor, momento.isoformat(timespec="seconds")))
    conn.commit()


def feedback_de(conn: sqlite3.Connection, consulta_id: int, user_id: int) -> int | None:
    fila = conn.execute("SELECT valor FROM feedback WHERE consulta_id = ? AND user_id = ?", (consulta_id, user_id)).fetchone()
    return fila["valor"] if fila else None


def todo_el_feedback(conn: sqlite3.Connection) -> list[dict]:
    """Una fila por voto, con los datos de la consulta que calificó (para evaluation/feedback_summary.py)."""
    filas = conn.execute(
        "SELECT f.id AS feedback_id, f.consulta_id, f.user_id, f.valor, f.timestamp AS feedback_timestamp, "
        "c.pregunta, c.abstuvo, c.error, c.timestamp AS consulta_timestamp "
        "FROM feedback f JOIN consultas c ON c.id = f.consulta_id ORDER BY f.id").fetchall()
    return [dict(f) for f in filas]

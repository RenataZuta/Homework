"""Transporte HTTP mínimo (JSON por POST) para los proveedores que se llaman por REST.

Devuelve ``(estado, cuerpo_json_o_None, cabeceras)`` y convierte los fallos de red en ``ErrorProveedor`` de tipo ``red``. Es un punto de
inyección: los tests pasan una función falsa y nunca tocan la red. La clave viaja SOLO en cabeceras, nunca en la URL (así no aparece en
mensajes de error ni en registros).
"""
from __future__ import annotations

from typing import Callable

from rag_engine.llm.cost_log import sanear
from rag_engine.limites import ErrorProveedor

Transporte = Callable[[str, dict, dict, float], "tuple[int, dict | None, dict]"]


def post_json(url: str, cabeceras: dict, cuerpo: dict, timeout_s: float) -> tuple[int, dict | None, dict]:
    import requests
    try:
        r = requests.post(url, headers={**cabeceras, "Content-Type": "application/json"}, json=cuerpo, timeout=timeout_s)
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
        raise ErrorProveedor("red", f"No se pudo conectar con el proveedor (red o tiempo de espera de {timeout_s:.0f} s). ({sanear(str(exc))})") from exc
    except requests.exceptions.RequestException as exc:
        raise ErrorProveedor("otro", f"Error inesperado al llamar al proveedor: {sanear(str(exc))}") from exc
    try:
        datos = r.json()
    except ValueError:
        datos = None
    return r.status_code, datos if isinstance(datos, dict) else None, dict(r.headers)

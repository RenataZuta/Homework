"""Precios por VENTANA HORARIA: el costo de una llamada usa el precio vigente a la hora de ESA llamada.

Estructura (pricing.yaml): por modelo, una lista de ventanas ``zona_horaria / hora_inicio / hora_fin / USD por millón de tokens de
entrada y de salida``. ``hora_fin: "24:00"`` significa "hasta el final del día"; una ventana con inicio mayor que fin cruza la
medianoche (p. ej. 20:00-08:00). Reglas que evitan costos falsos:
  * un modelo sin tabla, una hora sin ventana o un precio ``null`` es un ERROR: nunca se inventa un precio;
  * las ventanas de un modelo deben cubrir las 24 horas sin huecos ni solapes (se valida al cargar);
  * el momento debe traer zona horaria (un ``datetime`` ingenuo es ambiguo).
La documentación oficial de Anthropic publica un precio único por modelo (ver pricing.yaml); la estructura por ventanas existe y está
probada con una tabla ficticia de horas pico y valle para demostrar que el cálculo respeta la hora de cada llamada.
No se mezclan descuentos de caché ni de batch con el horario.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

MINUTOS_DIA = 24 * 60


class ErrorPrecio(Exception):
    """No hay un precio verificado aplicable. El mensaje dice qué falta."""


def _minutos(hhmm: str) -> int:
    try:
        h, m = str(hhmm).split(":")
        total = int(h) * 60 + int(m)
    except ValueError as exc:
        raise ErrorPrecio(f"Hora inválida '{hhmm}': usa el formato HH:MM (o 24:00 para el fin del día)") from exc
    if not 0 <= total <= MINUTOS_DIA:
        raise ErrorPrecio(f"Hora fuera de rango: '{hhmm}'")
    return total


@dataclass(frozen=True)
class Ventana:
    zona: str
    inicio: int            # minutos desde 00:00
    fin: int               # minutos; 1440 = 24:00
    usd_entrada: float     # por millón de tokens
    usd_salida: float

    def contiene(self, minuto: int) -> bool:
        if self.inicio < self.fin:
            return self.inicio <= minuto < self.fin
        return minuto >= self.inicio or minuto < self.fin          # cruza la medianoche


class TablaPrecios:
    def __init__(self, modelos: dict[str, list[Ventana]], fuente: str = "", fecha_verificacion: str = ""):
        self.modelos, self.fuente, self.fecha_verificacion = modelos, fuente, fecha_verificacion
        for nombre, ventanas in modelos.items():
            self._validar(nombre, ventanas)

    @staticmethod
    def _validar(modelo: str, ventanas: list[Ventana]) -> None:
        if not ventanas:
            raise ErrorPrecio(f"El modelo '{modelo}' no tiene ventanas de precio")
        if len({v.zona for v in ventanas}) > 1:
            raise ErrorPrecio(f"El modelo '{modelo}' mezcla zonas horarias; usa una sola")
        for v in ventanas:
            if v.inicio == v.fin:
                raise ErrorPrecio(f"Ventana vacía en '{modelo}': inicio y fin coinciden")
        for minuto in range(MINUTOS_DIA):
            n = sum(v.contiene(minuto) for v in ventanas)
            if n != 1:
                hh = f"{minuto // 60:02d}:{minuto % 60:02d}"
                raise ErrorPrecio(f"Las ventanas de '{modelo}' " + ("dejan sin precio" if n == 0 else "se solapan en") + f" las {hh}")

    @classmethod
    def desde_dict(cls, d: dict) -> "TablaPrecios":
        modelos: dict[str, list[Ventana]] = {}
        for nombre, datos in (d.get("modelos") or {}).items():
            ventanas = []
            for i, v in enumerate(datos.get("ventanas") or []):
                usd_in, usd_out = v.get("usd_por_millon_entrada"), v.get("usd_por_millon_salida")
                if usd_in is None or usd_out is None:
                    raise ErrorPrecio(f"El precio de '{nombre}' (ventana {i + 1}) es null: verifícalo en la fuente oficial antes de usarlo")
                ventanas.append(Ventana(v["zona_horaria"], _minutos(v["hora_inicio"]), _minutos(v["hora_fin"]), float(usd_in), float(usd_out)))
            modelos[nombre] = ventanas
        return cls(modelos, str(d.get("fuente", "")), str(d.get("fecha_verificacion", "")))

    def precio_en(self, momento: datetime, modelo: str) -> tuple[float, float]:
        """(USD por millón de tokens de entrada, de salida) vigentes en `momento` para `modelo`."""
        if momento.tzinfo is None:
            raise ErrorPrecio("El momento debe incluir zona horaria")
        ventanas = self.modelos.get(modelo)
        if not ventanas:
            raise ErrorPrecio(f"No hay precios verificados para el modelo '{modelo}'. Agrégalos a pricing.yaml con su fuente y fecha.")
        local = momento.astimezone(ZoneInfo(ventanas[0].zona))
        minuto = local.hour * 60 + local.minute
        v = next(v for v in ventanas if v.contiene(minuto))                    # existe exactamente una: se validó al cargar
        return v.usd_entrada, v.usd_salida

    def costo(self, modelo: str, tokens_entrada: int, tokens_salida: int, momento: datetime) -> float:
        usd_in, usd_out = self.precio_en(momento, modelo)
        return (tokens_entrada * usd_in + tokens_salida * usd_out) / 1_000_000


def cargar_tabla(ruta: Path, proveedor: str = "anthropic") -> TablaPrecios:
    datos = yaml.safe_load(Path(ruta).read_text(encoding="utf-8"))
    if proveedor not in datos:
        raise ErrorPrecio(f"{Path(ruta).name} no tiene el bloque '{proveedor}'")
    return TablaPrecios.desde_dict(datos[proveedor])

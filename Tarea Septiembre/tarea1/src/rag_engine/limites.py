"""Límites de uso de un proveedor externo: throttle por RPM y reintentos con backoff exponencial.

Sirve tanto al LLM como a los embeddings por API. No depende de ningún SDK: trabaja con excepciones que traen ``tipo``.
  * ``Limitador``: ventana deslizante de 60 s; nunca deja salir más de ``rpm`` peticiones en cualquier minuto.
  * ``PoliticaReintentos``: reintenta SOLO errores transitorios (429 por tasa, 5xx, red), con espera exponencial + jitter y respetando la
    espera que sugiera el proveedor; los demás errores (clave, formato, cuota diaria) fallan de inmediato, sin gastar cuota.
    Si el límite sigue activo tras los reintentos, el error final es ``cuota_agotada`` (estructurado, nunca una respuesta normal).
El reloj, el sueño y el azar se inyectan para probar todo sin esperar de verdad.
"""
from __future__ import annotations

import random
import threading
import time
from collections import deque
from typing import Callable, TypeVar

T = TypeVar("T")

TIPOS_REINTENTABLES = frozenset({"limite_de_tasa", "servidor", "red"})
TIPO_CUOTA_AGOTADA = "cuota_agotada"


class ErrorProveedor(Exception):
    """Base de los errores de proveedores externos (LLM, embeddings). ``tipo`` clasifica la causa; ``intentos`` cuenta las peticiones hechas."""

    def __init__(self, tipo: str, mensaje: str, *, solicitud_enviada: bool = True, espera_sugerida_s: float | None = None):
        super().__init__(mensaje)
        self.tipo = tipo
        self.mensaje = mensaje
        self.solicitud_enviada = solicitud_enviada          # False si falló ANTES de llamar al proveedor (p. ej. falta la clave)
        self.espera_sugerida_s = espera_sugerida_s          # p. ej. el retryDelay que devuelve Google en un 429
        self.intentos = 1


class Limitador:
    """Como máximo ``rpm`` peticiones por cada 60 s deslizantes. ``rpm=None`` desactiva el límite."""

    VENTANA_S = 60.0

    def __init__(self, rpm: float | None, reloj: Callable[[], float] = time.monotonic, dormir: Callable[[float], None] = time.sleep):
        if rpm is not None and rpm <= 0:
            raise ValueError("rpm debe ser mayor que 0 (o None para no limitar)")
        self.rpm, self._reloj, self._dormir = rpm, reloj, dormir
        self._salidas: deque[float] = deque()
        self._cerrojo = threading.Lock()
        self.espera_total_s = 0.0

    def esperar(self) -> float:
        """Bloquea lo necesario para poder enviar UNA petición y la anota. Devuelve los segundos esperados."""
        if self.rpm is None:
            return 0.0
        cupo = max(1, int(self.rpm))
        esperado = 0.0
        with self._cerrojo:
            while True:
                ahora = self._reloj()
                while self._salidas and ahora - self._salidas[0] >= self.VENTANA_S:
                    self._salidas.popleft()
                if len(self._salidas) < cupo:
                    self._salidas.append(ahora)
                    self.espera_total_s += esperado
                    return esperado
                falta = self.VENTANA_S - (ahora - self._salidas[0])
                self._dormir(falta)
                esperado += falta


class PoliticaReintentos:
    def __init__(self, reintentos: int, espera_inicial_s: float, factor: float, espera_max_s: float, jitter: float,
                 dormir: Callable[[float], None] = time.sleep, azar: Callable[[], float] = random.random):
        if reintentos < 0 or espera_inicial_s <= 0 or factor < 1 or espera_max_s < espera_inicial_s or not 0 <= jitter <= 1:
            raise ValueError("política de reintentos inválida (revisa llm.limites en config.yaml)")
        self.reintentos, self.espera_inicial_s, self.factor = reintentos, espera_inicial_s, factor
        self.espera_max_s, self.jitter, self._dormir, self._azar = espera_max_s, jitter, dormir, azar

    def espera(self, reintento: int, sugerida: float | None) -> float:
        """Segundos antes del reintento número ``reintento`` (1, 2, …): exponencial, con tope, jitter aditivo y la espera sugerida por el proveedor."""
        base = min(self.espera_max_s, self.espera_inicial_s * self.factor ** (reintento - 1))
        return min(self.espera_max_s, max(base, sugerida or 0.0)) * (1 + self.jitter * self._azar())

    def ejecutar(self, operacion: Callable[[], T], limitador: Limitador | None = None) -> T:
        """Ejecuta ``operacion`` (cada intento pasa por el limitador). Relanza el error final con ``intentos`` rellenado."""
        intento = 0
        while True:
            intento += 1
            if limitador is not None:
                limitador.esperar()
            try:
                return operacion()
            except ErrorProveedor as exc:
                exc.intentos = intento
                if not exc.solicitud_enviada or exc.tipo not in TIPOS_REINTENTABLES:
                    raise
                if intento > self.reintentos:
                    if exc.tipo == "limite_de_tasa":
                        exc.mensaje = (f"Se agotó el límite de uso del proveedor tras {intento} intentos con espera creciente. Espera unos minutos "
                                       f"(o hasta mañana si es la cuota diaria de la capa gratuita). Último aviso: {exc.mensaje}")
                        exc.tipo, exc.args = TIPO_CUOTA_AGOTADA, (exc.mensaje,)
                    raise
                self._dormir(self.espera(intento, exc.espera_sugerida_s))

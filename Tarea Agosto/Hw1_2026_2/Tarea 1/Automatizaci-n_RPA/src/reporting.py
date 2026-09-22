"""Registro en log y reporte final de la ejecución del bot."""

import csv
import logging
from datetime import datetime

from . import config


def configurar_logging():
    marca = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta_log = config.LOG_DIR / f"ejecucion_{marca}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(ruta_log, encoding="utf-8"),
            logging.StreamHandler(),
        ],
        force=True,
    )
    return ruta_log


class Reporte:
    def __init__(self):
        self.exitosos = []
        self.fallidos = []

    def registrar_exito(self, registro):
        self.exitosos.append(registro)

    def registrar_fallo(self, registro, motivo):
        self.fallidos.append({**registro, "motivo_error": motivo})

    @property
    def total(self):
        return len(self.exitosos) + len(self.fallidos)

    def resumen(self):
        lineas = [
            "==================== RESUMEN DE EJECUCIÓN ====================",
            f"Total de registros procesados   : {self.total}",
            f"Registros cargados correctamente: {len(self.exitosos)}",
            f"Registros que no se pudieron cargar: {len(self.fallidos)}",
        ]
        if self.fallidos:
            lineas.append("---------------- Detalle de registros fallidos ----------------")
            for r in self.fallidos:
                lineas.append(f"  DNI {r.get('dni', '?')} (fila {r.get('_fila', '?')}): {r['motivo_error']}")
        lineas.append("================================================================")
        return "\n".join(lineas)

    def exportar_csv(self):
        marca = datetime.now().strftime("%Y%m%d_%H%M%S")
        if self.exitosos:
            self._escribir_csv(config.OUTPUT_DIR / f"exitosos_{marca}.csv", self.exitosos)
        if self.fallidos:
            self._escribir_csv(config.OUTPUT_DIR / f"fallidos_{marca}.csv", self.fallidos)

    @staticmethod
    def _escribir_csv(ruta, filas):
        campos = sorted({clave for fila in filas for clave in fila.keys()})
        with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=campos)
            writer.writeheader()
            writer.writerows(filas)

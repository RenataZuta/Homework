"""Punto de entrada del bot RPA de registro de ingresos - PeopleSync.

Uso:
    python -m src.main
    python -m src.main --headless
    python -m src.main --limit 5          (prueba rápida con los primeros 5 registros)
    python -m src.main --data data\\empleados.csv   (usar copia local en vez de Google Sheets)
"""

import argparse
import logging

from .data_loader import cargar_empleados
from .validators import validar_registro
from .bot import PeopleSyncBot
from .reporting import configurar_logging, Reporte
from . import config


def parse_args():
    parser = argparse.ArgumentParser(description="Bot RPA de registro de ingresos - PeopleSync")
    parser.add_argument("--data", help="Ruta o URL del CSV de empleados (sobrescribe DATA_SOURCE)")
    parser.add_argument("--headless", action="store_true", help="Ejecuta Chrome en modo headless")
    parser.add_argument("--limit", type=int, help="Procesa solo los primeros N registros (para pruebas)")
    return parser.parse_args()


def main():
    args = parse_args()
    ruta_log = configurar_logging()
    logging.info("Iniciando bot RPA PeopleSync. Log de esta ejecución: %s", ruta_log)
    logging.info("Origen de datos: %s", args.data or config.DATA_SOURCE)

    registros = cargar_empleados(args.data)
    if args.limit:
        registros = registros[: args.limit]
    logging.info("Se cargaron %d registros para procesar.", len(registros))

    reporte = Reporte()
    bot = PeopleSyncBot(headless=True if args.headless else None)
    bot.abrir()

    try:
        for registro in registros:
            identificador = f"DNI {registro.get('dni', '?')} (fila {registro.get('_fila', '?')})"

            errores = validar_registro(registro)
            if errores:
                motivo = "; ".join(errores)
                logging.warning("Registro inválido, se omite - %s -> %s", identificador, motivo)
                reporte.registrar_fallo(registro, motivo)
                continue

            try:
                exito, motivo = bot.registrar_empleado(registro)
            except Exception as exc:  # errores inesperados de Selenium/el navegador
                exito, motivo = False, f"Error inesperado de automatización: {exc}"

            if exito:
                logging.info("Registrado con éxito - %s", identificador)
                reporte.registrar_exito(registro)
            else:
                logging.warning("Fallo al registrar - %s -> %s", identificador, motivo)
                reporte.registrar_fallo(registro, motivo)
                try:
                    captura = config.SCREENSHOT_DIR / f"error_fila{registro.get('_fila', '0')}_{registro.get('dni', 'sindni')}.png"
                    bot.driver.save_screenshot(str(captura))
                except Exception:
                    pass
    finally:
        bot.cerrar()

    resumen = reporte.resumen()
    print(resumen)
    logging.info("\n%s", resumen)
    reporte.exportar_csv()


if __name__ == "__main__":
    main()

"""
Bot de Web Scraping - Tipo de Cambio Oficial SUNAT
====================================================
Automatiza la consulta y descarga del tipo de cambio oficial publicado por
SUNAT (https://e-consulta.sunat.gob.pe/cl-at-ittipcam/tcS01Alias), desde un
mes de inicio configurable hasta un mes final configurable, consolidando
todo en un único archivo CSV.

Flujo:
    1. Selenium abre la página y navega el selector de fecha mes por mes.
    2. Por cada mes: clic en "Buscar" -> clic en "Descargar" -> se genera un PDF.
    3. pdfplumber extrae la tabla (Día, Compra, Venta) de cada PDF.
    4. Se consolida todo en un DataFrame y se exporta a CSV.

Uso:
    python sunat_scraper.py --start 2024-01 --end 2026-08 --headless

Curso: Data Science - Python | HW_01_202602 (Parte 2 - Web Scraping SUNAT)
"""

import argparse
import logging
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import pdfplumber
from dateutil.relativedelta import relativedelta
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# ----------------------------------------------------------------------------
# CONFIGURACIÓN GENERAL 
# ----------------------------------------------------------------------------

URL_SUNAT = "https://e-consulta.sunat.gob.pe/cl-at-ittipcam/tcS01Alias"

MESES_ES = {
    1: "ene.", 2: "feb.", 3: "mar.", 4: "abr.", 5: "may.", 6: "jun.",
    7: "jul.", 8: "ago.", 9: "sep.", 10: "oct.", 11: "nov.", 12: "dic.",
}

# Confirmados leyendo el HTML/JS real de la página (ver inicializarDatosPapeleta()
# en el <script> inline): el botón Descargar solo lee el VALOR del campo de
# texto fecAsistenciaBusq -- no depende de que el widget visual del calendario
# haya sido abierto ni de haber hecho clic en "Buscar" antes. Por eso fijamos
# ese valor directamente por JavaScript en vez de simular clics en el picker.
SELECTORS = {
    "date_field_id": "fecAsistenciaBusq",
    "descargar_button_id": "btnDescargar",
}


# ----------------------------------------------------------------------------
# UTILIDADES DE FECHAS
# ----------------------------------------------------------------------------

def generar_meses(inicio: str, fin: str):
    """Genera tuplas (anio, mes) desde 'YYYY-MM' hasta 'YYYY-MM', inclusive."""
    d_inicio = datetime.strptime(inicio, "%Y-%m")
    d_fin = datetime.strptime(fin, "%Y-%m")
    if d_inicio > d_fin:
        raise ValueError("La fecha de inicio no puede ser posterior a la fecha final")
    actual = d_inicio
    while actual <= d_fin:
        yield actual.year, actual.month
        actual += relativedelta(months=1)


# ----------------------------------------------------------------------------
# SELENIUM: CONFIGURACIÓN DEL DRIVER
# ----------------------------------------------------------------------------

def obtener_ruta_chromedriver() -> str:
    """webdriver-manager a veces devuelve la ruta al archivo de licencias
    (THIRD_PARTY_NOTICES.chromedriver) en vez del binario real -- un bug
    conocido con el layout nuevo de Chrome for Testing. Esta función corrige
    eso localizando el binario correcto junto a la ruta devuelta."""
    ruta = ChromeDriverManager().install()
    carpeta = Path(ruta).parent
    nombre_binario = "chromedriver.exe" if sys.platform.startswith("win") else "chromedriver"

    if Path(ruta).name != nombre_binario:
        candidato = carpeta / nombre_binario
        if candidato.exists():
            ruta = str(candidato)

    if not sys.platform.startswith("win"):
        Path(ruta).chmod(0o755)  # asegura permiso de ejecución en Mac/Linux

    return ruta


def crear_driver(download_dir: Path, headless: bool = False) -> webdriver.Chrome:
    """Crea el driver de Chrome configurado para descargar PDFs sin diálogo
    ni previsualización, directo a `download_dir`."""
    opciones = Options()
    if headless:
        opciones.add_argument("--headless=new")
    opciones.add_argument("--window-size=1400,1000")

    prefs = {
        "download.default_directory": str(download_dir.resolve()),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        # Sin esto, Chrome intenta ABRIR el PDF en su visor interno en vez
        # de descargarlo como archivo.
        "plugins.always_open_pdf_externally": True,
    }
    opciones.add_experimental_option("prefs", prefs)

    servicio = Service(obtener_ruta_chromedriver())
    return webdriver.Chrome(service=servicio, options=opciones)


# ----------------------------------------------------------------------------
# SELENIUM: FIJAR EL PERIODO Y DESCARGAR
# ----------------------------------------------------------------------------

def esperar_recaptcha_listo(driver, wait: WebDriverWait) -> None:
    """El botón Descargar depende de grecaptcha (cargado por un <script> externo
    de forma asíncrona). Esperamos a que esté listo antes del primer intento."""
    wait.until(lambda d: d.execute_script(
        "return typeof grecaptcha !== 'undefined' && typeof grecaptcha.execute === 'function';"
    ))


def establecer_periodo(driver, wait: WebDriverWait, anio: int, mes: int) -> None:
    """Fija el mes/año directamente en el campo de búsqueda vía JavaScript.

    El campo es readonly para el usuario (se llena con un date-picker visual),
    pero el handler de 'Descargar' solo lee `$('#fecAsistenciaBusq').val()`,
    así que fijar el valor por JS -- igual que hace la librería del picker
    internamente -- evita tener que simular clics en el widget visual.
    """
    texto_periodo = f"{MESES_ES[mes]} {anio}"  # ej. "ago. 2026", mismo formato
    # que usa moment.js (locale 'es', formato 'MMM YYYY') en el input.
    campo = wait.until(EC.presence_of_element_located((By.ID, SELECTORS["date_field_id"])))
    driver.execute_script("arguments[0].value = arguments[1];", campo, texto_periodo)


def click_descargar_y_esperar(
    driver, wait: WebDriverWait, download_dir: Path, timeout: int = 30
) -> Path:
    """Hace clic en Descargar y espera (polling) a que aparezca un PDF nuevo
    y completo (sin extensión .crdownload) en la carpeta de descargas."""
    archivos_antes = set(download_dir.glob("*.pdf"))

    boton = wait.until(EC.element_to_be_clickable((By.ID, SELECTORS["descargar_button_id"])))
    boton.click()

    inicio = time.time()
    while time.time() - inicio < timeout:
        descargas_en_curso = list(download_dir.glob("*.crdownload"))
        if not descargas_en_curso:
            archivos_ahora = set(download_dir.glob("*.pdf"))
            nuevos = archivos_ahora - archivos_antes
            if nuevos:
                return nuevos.pop()
        time.sleep(0.5)

    raise TimeoutException(
        "La descarga del PDF no se completó a tiempo. Si esto se repite, "
        "puede que 'obtenerAnioMes' espere un formato de texto distinto en "
        "el campo -- revisar mostrarMensajeError en pantalla."
    )


def procesar_mes(
    driver, wait: WebDriverWait, anio: int, mes: int, download_dir: Path, max_intentos: int = 3
) -> Path:
    """Intenta descargar el PDF de un mes, con reintentos y espera creciente
    entre cada uno. SUNAT parece limitar/bloquear silenciosamente tras varias
    descargas seguidas en la misma sesión -- este reintento con backoff ayuda
    a superar eso sin detener todo el proceso."""
    ultimo_error: Exception | None = None
    for intento in range(1, max_intentos + 1):
        try:
            establecer_periodo(driver, wait, anio, mes)
            return click_descargar_y_esperar(driver, wait, download_dir)
        except Exception as exc:  # noqa: BLE001
            ultimo_error = exc
            logging.warning(
                "Intento %d/%d falló para %04d-%02d: %s", intento, max_intentos, anio, mes, exc
            )
            if intento < max_intentos:
                espera = 15 * intento  # backoff creciente: 15s, 30s, ...
                logging.info("Esperando %ds antes de reintentar %04d-%02d...", espera, anio, mes)
                time.sleep(espera)
    raise ultimo_error


# ----------------------------------------------------------------------------
# EXTRACCIÓN DE DATOS DEL PDF
# ----------------------------------------------------------------------------

def parse_pdf_mes(pdf_path: Path, anio: int, mes: int) -> list[dict]:
    """Extrae los registros (fecha, compra, venta) de un PDF mensual de SUNAT.

    El PDF trae una única tabla con 4 grupos de columnas (Dia, Compra, Venta)
    repetidos, y celdas vacías para los días que aún no tienen dato publicado.
    """
    registros = []
    with pdfplumber.open(pdf_path) as pdf:
        tablas = pdf.pages[0].extract_tables()
        if not tablas:
            logging.warning("No se encontró tabla en el PDF de %04d-%02d", anio, mes)
            return registros

        filas = tablas[0][1:]  # se salta la fila de encabezado
        for fila in filas:
            for i in range(0, len(fila), 3):
                dia, compra, venta = fila[i], fila[i + 1], fila[i + 2]
                if not dia or not dia.strip():
                    continue  # día futuro / sin dato aún
                try:
                    fecha = datetime(anio, mes, int(dia))
                    registros.append({
                        "fecha": fecha.strftime("%Y-%m-%d"),
                        "compra": float(compra),
                        "venta": float(venta),
                    })
                except (ValueError, TypeError):
                    logging.warning(
                        "Fila con datos inválidos en %04d-%02d: dia=%r compra=%r venta=%r",
                        anio, mes, dia, compra, venta,
                    )
    return registros


# ----------------------------------------------------------------------------
# PROGRAMA PRINCIPAL
# ----------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Scraper de Tipo de Cambio SUNAT")
    parser.add_argument("--start", default="2024-01", help="Mes de inicio (YYYY-MM)")
    parser.add_argument(
        "--end", default=datetime.today().strftime("%Y-%m"), help="Mes final (YYYY-MM)"
    )
    parser.add_argument(
        "--download-dir", default="descargas_sunat", help="Carpeta temporal de descargas"
    )
    parser.add_argument(
        "--output", default="tipo_cambio_sunat.csv", help="Archivo CSV consolidado de salida"
    )
    parser.add_argument("--headless", action="store_true", help="Ejecutar Chrome sin ventana visible")
    parser.add_argument("--min-delay", type=float, default=5.0, help="Pausa mínima entre meses (s)")
    parser.add_argument("--max-delay", type=float, default=10.0, help="Pausa máxima entre meses (s)")
    parser.add_argument(
        "--meses-entre-reinicios",
        type=int,
        default=8,
        help="Cada cuántos meses se reinicia la sesión del navegador",
    )
    args = parser.parse_args()

    download_dir = Path(args.download_dir).resolve()
    download_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler("sunat_scraper.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    logging.info("Iniciando scraper SUNAT | rango %s -> %s", args.start, args.end)

    driver = crear_driver(download_dir, headless=args.headless)
    wait = WebDriverWait(driver, 15)
    todos_los_registros: list[dict] = []
    meses_fallidos: list[tuple[int, int]] = []

    def abrir_sesion() -> None:
        driver.get(URL_SUNAT)
        wait.until(EC.presence_of_element_located((By.ID, SELECTORS["date_field_id"])))
        esperar_recaptcha_listo(driver, wait)

    try:
        abrir_sesion()

        for indice, (anio, mes) in enumerate(generar_meses(args.start, args.end), start=1):
            # Reiniciar la sesión del navegador cada N meses: si el bloqueo es
            # por límite de peticiones en la sesión, esto le da un contexto
            # fresco al proceso en vez de seguir chocando contra el límite.
            if indice > 1 and (indice - 1) % args.meses_entre_reinicios == 0:
                logging.info(
                    "Reiniciando sesión del navegador (cada %d meses) para evitar bloqueos",
                    args.meses_entre_reinicios,
                )
                driver.quit()
                driver = crear_driver(download_dir, headless=args.headless)
                wait = WebDriverWait(driver, 15)
                abrir_sesion()
                time.sleep(5)

            try:
                logging.info("Procesando %04d-%02d", anio, mes)
                pdf_path = procesar_mes(driver, wait, anio, mes, download_dir)
                registros = parse_pdf_mes(pdf_path, anio, mes)
                todos_los_registros.extend(registros)
                logging.info("  -> %d registros extraídos de %04d-%02d", len(registros), anio, mes)

            except Exception as exc:  # noqa: BLE001 - no detener todo el proceso por un mes
                logging.error("Falló definitivamente %04d-%02d tras varios intentos: %s", anio, mes, exc)
                meses_fallidos.append((anio, mes))
                continue

            time.sleep(random.uniform(args.min_delay, args.max_delay))

        # Segunda pasada: reintenta, tras un enfriamiento largo, los meses que
        # quedaron pendientes -- por si el bloqueo se libera con más tiempo.
        if meses_fallidos:
            logging.info(
                "Segunda pasada: reintentando %d mes(es) tras 60s de enfriamiento...",
                len(meses_fallidos),
            )
            time.sleep(60)
            driver.quit()
            driver = crear_driver(download_dir, headless=args.headless)
            wait = WebDriverWait(driver, 15)
            abrir_sesion()

            aun_fallidos = []
            for anio, mes in meses_fallidos:
                try:
                    logging.info("Reintentando %04d-%02d", anio, mes)
                    pdf_path = procesar_mes(driver, wait, anio, mes, download_dir, max_intentos=2)
                    registros = parse_pdf_mes(pdf_path, anio, mes)
                    todos_los_registros.extend(registros)
                    logging.info(
                        "  -> %d registros extraídos de %04d-%02d (reintento)", len(registros), anio, mes
                    )
                except Exception as exc:  # noqa: BLE001
                    logging.error("Falló definitivamente %04d-%02d en la segunda pasada: %s", anio, mes, exc)
                    aun_fallidos.append(f"{anio:04d}-{mes:02d}")
                time.sleep(random.uniform(args.min_delay, args.max_delay))
            meses_fallidos = aun_fallidos
        else:
            meses_fallidos = []

    finally:
        driver.quit()

    if todos_los_registros:
        df = (
            pd.DataFrame(todos_los_registros)
            .drop_duplicates(subset="fecha")
            .sort_values("fecha")
            .reset_index(drop=True)
        )
        df.to_csv(args.output, index=False)
        logging.info("Proceso terminado. %d registros guardados en %s", len(df), args.output)
    else:
        logging.warning("Proceso terminado sin registros extraídos.")

    if meses_fallidos:
        logging.warning("Meses que fallaron y deben revisarse: %s", ", ".join(meses_fallidos))


if __name__ == "__main__":
    main()

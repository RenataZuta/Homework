# Scraper de Tipo de Cambio SUNAT

Automatiza la descarga y consolidación del tipo de cambio oficial (SUNAT)
desde un mes de inicio hasta un mes final, usando Selenium + pdfplumber.

## Cómo funciona la selección de mes/año

El botón "Descargar" de SUNAT no depende del widget visual del calendario:
solo lee el texto del campo `#fecAsistenciaBusq` (ver `inicializarDatosPapeleta()`
en el HTML de la página). Por eso el script fija ese valor directamente por
JavaScript (`establecer_periodo`) en vez de simular clics en el date-picker,
lo cual es más rápido y mucho menos frágil. Si en algún momento esto deja de
funcionar (por ejemplo si `obtenerAnioMes()` cambia de formato esperado), el
plan B es automatizar el click-through real del picker visual — avísame y lo
armamos.

## Estado actual

- [x] Extracción de datos del PDF (`parse_pdf_mes`) — **probada y funcionando**
- [x] Consolidación a CSV, manejo de días sin dato, logging a archivo
- [x] Rango de fechas configurable por línea de comandos
- [x] Selección de mes/año vía JS directo sobre `#fecAsistenciaBusq`
- [ ] Prueba end-to-end contra el sitio real — **siguiente paso: correrlo tú**
- [ ] Configuración y evidencia en Windows Task Scheduler

## Instalación

```bash
python -m venv venv
# Mac/Linux:
source venv/bin/activate
# Windows:
venv\Scripts\activate

pip install -r requirements.txt
```

No necesitas instalar ChromeDriver manualmente: `webdriver-manager` lo
descarga automáticamente la primera vez que corres el script, tanto en
Mac como en Windows.

## Uso

```bash
python sunat_scraper.py --start 2024-01 --end 2026-08
```

Parámetros disponibles:

| Parámetro       | Default                  | Descripción                              |
|-----------------|---------------------------|-------------------------------------------|
| `--start`       | `2024-01`                | Mes de inicio (YYYY-MM)                   |
| `--end`         | mes actual                | Mes final (YYYY-MM)                       |
| `--download-dir`| `descargas_sunat`         | Carpeta temporal para los PDFs descargados|
| `--output`      | `tipo_cambio_sunat.csv`   | Archivo CSV consolidado de salida         |
| `--headless`    | desactivado                | Corre Chrome sin ventana visible          |
| `--min-delay` / `--max-delay` | `2.0` / `5.0`  | Pausa aleatoria entre consultas (segundos)|

## Configurar en Windows Task Scheduler

1. Verifica la ruta completa de tu `python.exe` (dentro del venv):
   `C:\ruta\al\proyecto\venv\Scripts\python.exe`
2. Abre el **Programador de tareas** > Crear tarea básica.
3. **Desencadenador:** el que pida la tarea (ej. diario a una hora fija).
4. **Acción:** Iniciar un programa.
   - Programa/script: `C:\ruta\al\proyecto\venv\Scripts\python.exe`
   - Argumentos: `sunat_scraper.py --headless`
   - Iniciar en: `C:\ruta\al\proyecto`
5. Marca "Ejecutar tanto si el usuario inició sesión como si no" si necesitas
   que corra sin nadie conectado.
6. Guarda y haz clic derecho > **Ejecutar** para probarla manualmente antes
   de esperar al disparador automático.
7. Como evidencia para el video: muestra el historial de la tarea en
   Task Scheduler (pestaña "Historial") y el archivo `sunat_scraper.log`
   generado tras esa ejecución.

# RPA PeopleSync — Registro automático de ingresos

Bot en Python + Selenium que automatiza el registro de los 50 empleados del
dataset en el formulario PeopleSync (`https://the-paul2002.github.io/Proyecto-IA-/Homework1/`).

## Cómo funciona

1. **Carga los datos** desde el CSV publicado de Google Sheets (o un archivo
   local) — [src/data_loader.py](src/data_loader.py).
2. **Valida cada registro en Python** contra las mismas reglas que usa el
   formulario (DNI de 8 dígitos, teléfono `9XXXXXXXX`, correo válido, y que
   género/área/puesto/contrato/sede/modalidad sean opciones que el `<select>`
   realmente ofrece) — [src/validators.py](src/validators.py). Los registros
   que no cumplen se **omiten y quedan registrados como fallidos con el
   motivo exacto**, sin detener el proceso.
   - Importante: el dataset de 50 empleados incluye a propósito ~24 registros
     con `genero` en `No binario` / `Prefiero no indicar`, valores que el
     `<select>` del formulario no contempla (solo admite `Masculino` /
     `Femenino`). Esos registros fallan la validación y se reportan como tal;
     es el caso de "datos inconsistentes" que pide el enunciado.
3. **Llena y envía el formulario con Selenium** para cada registro válido, sin
   recargar la página entre registros — [src/bot.py](src/bot.py).
4. **Verifica** que el registro apareció en la tabla de la sesión (compara el
   conteo de filas y el DNI de la última fila) antes de darlo por exitoso.
5. Al terminar, imprime y guarda un **resumen** (total procesados, exitosos,
   fallidos y motivo de cada fallo) — [src/reporting.py](src/reporting.py).

## Instalación

```powershell
cd C:\Users\Acer\rpa-peoplesync
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Selenium 4.6+ descarga automáticamente el driver de Chrome que corresponda
(Selenium Manager), así que **no hace falta** descargar chromedriver a mano
ni tenerlo en el PATH — solo necesitas Google Chrome instalado.

## Configuración

Copia `.env.example` a `.env` y ajusta si hace falta (URLs, timeouts, modo
headless). Todo tiene un valor por defecto en [src/config.py](src/config.py);
no hay rutas ni datos escritos a fuego en el código.

## Ejecutar

```powershell
python -m src.main                     # corrida completa (50 registros)
python -m src.main --limit 5           # prueba rápida con 5 registros
python -m src.main --headless          # sin abrir ventana de Chrome
python -m src.main --data data\empleados.csv   # usar copia local en vez de Google Sheets
```

Salidas de cada corrida:
- `logs/ejecucion_<fecha>.log` — log detallado de la ejecución.
- `output/exitosos_<fecha>.csv` / `output/fallidos_<fecha>.csv` — detalle de
  cada registro, incluyendo el motivo de error en los fallidos.
- `screenshots/error_*.png` — captura de pantalla cuando un registro falla
  durante la automatización (evidencia para el video/entrega).

Al final de cada corrida se imprime en consola (y en el log) el resumen:

```
==================== RESUMEN DE EJECUCIÓN ====================
Total de registros procesados   : 50
Registros cargados correctamente: 26
Registros que no se pudieron cargar: 24
---------------- Detalle de registros fallidos ----------------
  DNI 48376941 (fila 5): género no soportado por el formulario: 'No binario' (opciones válidas: Femenino, Masculino)
  ...
================================================================
```

## Ejecución automática con el Programador de tareas de Windows

Opción A — script incluido (crea la tarea por ti):

```powershell
cd C:\Users\Acer\rpa-peoplesync
.\task_scheduler_setup.ps1              # todos los días a las 08:00
.\task_scheduler_setup.ps1 -Hora "07:30"
```

Opción B — manual desde la interfaz gráfica:
1. Abrir "Programador de tareas" → "Crear tarea básica".
2. Desencadenador: el horario que prefieras.
3. Acción: "Iniciar un programa".
   - Programa/script: ruta completa a `python.exe` (o a `run_bot.bat`).
   - Argumentos: `-m src.main --headless`
   - Iniciar en: `C:\Users\Acer\rpa-peoplesync`

## Estructura del proyecto

```
rpa-peoplesync/
├── src/
│   ├── config.py       # configuración vía variables de entorno / .env
│   ├── data_loader.py  # lectura y normalización del CSV de empleados
│   ├── validators.py   # validación replicando las reglas del formulario
│   ├── bot.py          # automatización Selenium (llenar, enviar, verificar)
│   ├── reporting.py    # logging y resumen final
│   └── main.py         # orquestador / punto de entrada
├── data/empleados.csv  # copia local del dataset (fallback sin internet)
├── requirements.txt
├── .env.example
├── run_bot.bat
├── task_scheduler_setup.ps1
└── README.md
```

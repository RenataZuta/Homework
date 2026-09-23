# Tarea 2 — Datos de contrataciones públicas (SEACE V3.0 / OCDS)

Fases 1 (adquisición) y 2 (validación y normalización territorial). Las Fases 3-5 parten de
`data/processed/procesos_validados.parquet`. Más adelante se reutilizará `rag_engine`, el motor de la
Tarea 1 (`../Tarea 1/src/rag_engine/`).

## Cómo ejecutarlo

```bash
# Python 3.12 (el mismo que la Tarea 1)
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt

python src/acquisition_bulk.py          # 1a. descarga jun/jul/ago 2026 a data/raw/ (no re-descarga si ya existen)
python src/acquisition_api.py --pages   # 1b. muestra de la API (3 páginas de /records, con caché)
python src/normalize_records.py         # 1c. una fila por ocid → data/processed/procesos.parquet
python src/territory_mapping.py         # 2b. casos de prueba de la regla territorial (opcional)
python src/validation.py                # 2a. reglas de calidad + departamento → reporte_calidad.md
```

Todos los parámetros (URLs, meses, carpetas, límites de la API, lista de códigos OCDS) están en
[config.yaml](config.yaml). La regla territorial está en [config/departamentos.yaml](config/departamentos.yaml).

| Salida | Qué contiene |
|---|---|
| `data/processed/procesos_validados.parquet` | **Tabla para las Fases 3-5**: 20.452 procesos (1 por ocid), `departamento` normalizado y columnas `flag_*` |
| `data/processed/procesos.parquet` | La misma tabla antes de la validación |
| `data/outputs/reporte_calidad.md` / `.json` | Informe de calidad: una fila por regla |
| `data/outputs/reporte_normalizacion.json` | Filas antes/después de pasar a una fila por ocid |
| `logs/descargas.jsonl` | Cada descarga: fecha, URL, tamaño, tiempo, velocidad, SHA-256 |
| `logs/api_requests.jsonl` | Cada petición a la API: URL, estado HTTP, intento, tamaño, tiempo |

## Fuente de datos

El portal `contratacionesabiertas.oece.gob.pe` es una aplicación Angular: la página `/descargas` no tiene
los enlaces en el HTML. Revisando su código, el listado sale del endpoint `/api/v1/files`, y cada archivo
mensual sigue este patrón:

```
https://contratacionesabiertas.oece.gob.pe/api/v1/file/seace_v3/{csv|csv_es|xlsx|json|sha}/{AAAA}/{MM}/
```

Cada ZIP CSV trae 22 tablas: `records.csv`, `releases.csv` y tablas `com_*` (parties, awards, contracts,
tenderers, documents…). La API de datos es `/api/v1/records` (paginada con `links.next`) y
`/api/v1/record/{ocid}`.

## Números del lote (jun-ago 2026)

- 3 ZIP, 32 MB en total (12,5 + 10,9 + 9,0 MB), ~0,9 MB/s.
- **285.290 releases → 20.452 records → 20.452 filas (1 por ocid)**; ~14 releases por proceso.
- 16.297 procesos tienen al menos una marca de calidad; 4.155 no tienen ninguna. El número de marcados
  es alto sobre todo porque el CSV no publica el estado de los contratos (R5) y porque muchas
  adjudicaciones aún no tienen contrato (R7a).

| Regla | Marcados |
|---|---|
| Monto 0 con valor reservado por ley / sin explicación | 2.175 / 111 procesos |
| OCP #1 ids duplicados de postores | 70 procesos |
| OCP #2 contratos sin estado | 9.606 de 9.606 en el CSV (la columna no existe); 46 de 52 en la muestra de la API |
| OCP #3 documentType no declarado / sin tipo | 0 / 754 documentos |
| OCP #4 adjudicación sin contrato / contrato sin adjudicación | 5.352 / 99 |
| Textos con mojibake (`BÂSICA`, `MUÃ¿OZ`) | 3 procesos |
| ocid duplicado, sin monto, sin descripción, no ubicado, tildes | 0 |

## Decisiones de diseño (y por qué)

**Adquisición**
- **Meses jun-jul-ago 2026.** Son los tres últimos meses completos. Septiembre se excluye porque OECE lo
  regenera a diario mientras el mes no termina, así que no sería reproducible.
- **Formato `csv`, no `csv_es`.** Los encabezados en inglés son las rutas OCDS
  (`compiledRelease/tender/value/amount`), que coinciden con el estándar y con la API.
- **Descarga a `.part` y luego renombrar.** Si la descarga se corta, nunca queda un ZIP a medias que parezca
  válido. Al volver a ejecutar, un ZIP que ya existe y está íntegro no se descarga de nuevo.
- **Integridad por `Content-Length` + CRC del ZIP, no por el SHA publicado.** El SHA-256 que publica OECE
  (`/sha/…`) lo comprobamos y corresponde al **JSON descomprimido**, no al ZIP CSV. Por eso guardamos
  nuestro propio SHA-256 en `logs/descargas.jsonl`, y así el equipo puede confirmar que usa los mismos archivos.
- **Los ZIP no se versionan en git; los Parquet sí.** Los ZIP pesan 32 MB y se pueden volver a descargar.
  En cambio, como OECE regenera los archivos, versionar `procesos*.parquet` (~5 MB) garantiza que las
  Fases 3-5 trabajen con los mismos datos que este informe.
- **API: 1 petición por segundo, reintentos exponenciales (2, 4, 8, 16 y 32 s) solo ante 429/5xx o errores
  de red, y se respeta `Retry-After`.** Un 404 no se reintenta porque repetirlo no lo arregla. Cada
  respuesta se guarda en disco (escritura atómica) *antes* de pedir la siguiente. Si el proceso se cae,
  al relanzarlo lo ya bajado sale de la caché y continúa donde quedó.

**Una fila por ocid**
- **Tabla base = `records.csv` (compiledRelease).** Un *release* es una foto de un momento y un *record*
  es el estado actual ya fusionado. Usar `releases.csv` repetiría cada proceso ~14 veces. De los releases
  solo tomamos cuántos hubo y sus fechas.
- **Tablas hijas agregadas antes de unir** (contar, sumar, concatenar) y unidas con LEFT JOIN, que no puede
  duplicar ni perder ocids. Un `assert` lo verifica en cada corrida.
- **Si un ocid se repite entre meses, se queda la versión más reciente** (`compiledRelease/date`) y se reporta
  la decisión. En este lote no hubo repetidos. Se probó duplicando un mes a propósito: 13.140 filas → 6.570.
- **Sin adjudicación, el monto adjudicado es NaN, no 0.** "No se sabe" no es lo mismo que "cero soles".

**Validación**
- **Marcar, nunca borrar.** Cada regla crea una columna `flag_*`, y quien use los datos decide si filtra.
- **El monto 0 se divide en dos.** El 95% de los ceros tienen `hasTenderInformationProtectedByLaw=True`,
  es decir, la entidad reservó el valor referencial. No es un error, pero sumarlos como 0 subestimaría
  los montos.
- **OCP #1 se busca de dos formas:** el id repetido exacto (0 casos) y el mismo nombre de postor con
  varios ids en un proceso (70 procesos, sobre todo empresas extranjeras con id generado `PE-RUC-L…`).
  No se fusionan automáticamente, porque dos empresas pueden llamarse igual.
- **OCP #2 se mide también con la API**, porque el CSV no trae la columna `status`. Con solo el CSV, el
  resultado sería "100%", que es cierto pero poco informativo.
- **OCP #4 en ambos sentidos.** Que una adjudicación no tenga contrato es en parte esperable (contratos aún
  no firmados). Que un contrato apunte a un `awardID` inexistente es un error real del publicador.

**Territorio**
- **Se usa la ubicación del comprador** (la entidad que contrata): es el único actor con dirección en los
  datos (los postores no la traen).
- **Orden de la regla: departamento → alias → provincia → nombre de la entidad → `NO_UBICADO`.** Un
  departamento gana sobre una provincia del mismo nombre ("UCAYALI" es departamento y también provincia de
  Loreto). Si nada coincide, no se adivina.
- **Las tildes se quitan pero la Ñ se conserva** (CAÑETE ≠ CANETE). Si un texto perdió la Ñ por encoding,
  se acepta solo cuando no hay ambigüedad.
- **"Lima Metropolitana" y "Lima Provincias" → LIMA**, para tener exactamente 25 departamentos (24 + Callao).
- **Resultado honesto:** en este lote, el campo `department` de SEACE V3 ya viene limpio (25 valores,
  sin tildes, también en la API). Por eso las reglas de tildes y de provincias dieron 0. Son reglas
  defensivas: 35 casos de prueba (`python src/territory_mapping.py`) muestran que funcionan con
  variantes como `JUNÍN`, `Región Cusco`, `HUAURA` o `CAÑETE`. Además, la tabla de 196 provincias se
  contrastó con el dato: coinciden 194 de 195 provincias (solo faltaba la grafía `ANTONIO RAYMONDI`) y
  ningún par provincia→departamento la contradice.

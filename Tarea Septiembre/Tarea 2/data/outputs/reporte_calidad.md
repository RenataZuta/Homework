# Reporte de calidad de datos — SEACE V3.0 (OCDS)

Generado: 2026-09-23T13:12:09-05:00 · Meses: 2026-06, 2026-07, 2026-08 · Procesos (1 fila por ocid): **20,452**
 · Procesos sin ninguna marca: **4,155**

Ningún registro se eliminó: cada regla añade una columna `flag_*` en `data/processed/procesos_validados.parquet`.

| # | Regla | Unidad | Marcados | Total | % | Qué se hizo |
|---|---|---|---:|---:|---:|---|
| R1 | ocid duplicado en records.csv (entre y dentro de meses) | filas de records | 0 | 20,452 | 0.00 | Se conserva la versión más reciente (compiledRelease/date) en normalize_records.py y se marca flag_ocid_duplicado; la tabla final tiene 1 fila por ocid (verificado con assert). |
| R2a | Monto referencial faltante (vacío) | procesos | 0 | 20,452 | 0.00 | Marcado flag_monto_faltante. No se imputa: un monto inventado sesgaría cualquier suma. |
| R2b | Monto referencial = 0 con valor reservado por ley | procesos | 2,175 | 20,452 | 10.63 | Marcado flag_monto_cero_reservado. NO es error: hasTenderInformationProtectedByLaw=True significa que la entidad reservó el valor referencial; el 0 debe leerse como 'no publicado', nunca sumarse como 0. |
| R2c | Monto referencial = 0 sin explicación | procesos | 111 | 20,452 | 0.54 | Marcado flag_monto_cero_sin_explicacion. Se conserva el registro; tratar el monto como desconocido. |
| R3a | Proceso sin descripción | procesos | 0 | 20,452 | 0.00 | Marcado flag_sin_descripcion. Para el RAG, estos procesos no tienen texto que indexar. |
| R3b | Descripción idéntica a la nomenclatura (sin contenido real) | procesos | 0 | 20,452 | 0.00 | Marcado flag_descripcion_igual_nomenclatura (descripción que solo repite el código del proceso). |
| R4 | OCP #1 · tenderer/parties con identificadores duplicados | procesos | 70 | 20,452 | 0.34 | Marcado flag_ocp1_ids_duplicados. No se fusionan organizaciones automáticamente: dos empresas pueden compartir nombre; unificar ids requiere verificación (p. ej. contra SUNAT). |
| R5 | OCP #2 · contratos sin estado (status) | contratos | 9,606 | 9,606 | 100.00 | Marcado flag_ocp2_contrato_sin_estado en el proceso. No se infiere el estado a partir de fechas. |
| R6a | OCP #3 · documentType con código no declarado | documentos | 0 | 105,212 | 0.00 | Marcado flag_ocp3_documenttype_no_declarado. El código se conserva tal cual (no se reclasifica). |
| R6b | Documento sin documentType | documentos | 754 | 105,212 | 0.72 | Marcado flag_documento_sin_tipo en el proceso. |
| R7a | OCP #4 · adjudicación sin contrato vinculado | adjudicaciones | 5,352 | 14,693 | 36.43 | Marcado flag_ocp4_adjudicacion_sin_contrato. Parte es esperable (contrato aún no firmado en procesos recientes); no se crea ni se borra ningún vínculo. |
| R7b | OCP #4 · contrato cuyo awardID no existe en awards | contratos | 99 | 9,606 | 1.03 | Marcado flag_ocp4_contrato_sin_adjudicacion. Es una inconsistencia real del publicador. |
| R8a | Ubicación no mapeable a los 25 departamentos | procesos | 0 | 20,452 | 0.00 | Se deja departamento=NO_UBICADO y flag_territorio_no_ubicado; nunca se asigna un departamento por defecto. |
| R8b | Provincia mal clasificada como departamento | procesos | 0 | 20,452 | 0.00 | Se reemplaza por el departamento al que pertenece la provincia (config/departamentos.yaml). |
| R8c | Provincia declarada pertenece a otro departamento | procesos | 0 | 20,452 | 0.00 | Se mantiene el departamento declarado y se marca flag_territorio_inconsistente para revisión. |
| R9a | Departamento con tildes/mayúsculas/espacios distintos (JUNÍN vs JUNIN) | procesos | 0 | 20,452 | 0.00 | Se normaliza a MAYÚSCULAS sin tildes (se conserva la Ñ) en la columna 'departamento'; el valor original queda en 'departamento_raw'. |
| R9b | Texto con mojibake o caracteres de reemplazo (Ã, Â, �) | procesos | 3 | 20,452 | 0.01 | Marcado flag_texto_mojibake. Los CSV se leen explícitamente como UTF-8 (verificado: el archivo es UTF-8 válido); si aparece mojibake se reporta, no se 'repara' a ciegas. |

## Notas por regla

- **R1** (records.csv). Tabla final: 0 duplicados.
- **R2b** (records.csv).  Ejemplos: `ocds-dgv273-seacev3-1232957`, `ocds-dgv273-seacev3-1246147`, `ocds-dgv273-seacev3-1244451`, `ocds-dgv273-seacev3-1243790`, `ocds-dgv273-seacev3-1240701`.
- **R2c** (records.csv).  Ejemplos: `ocds-dgv273-seacev3-1239597`, `ocds-dgv273-seacev3-1244699`, `ocds-dgv273-seacev3-1244610`, `ocds-dgv273-seacev3-1234089`, `ocds-dgv273-seacev3-1241747`.
- **R4** (com_ten_tenderers.csv, com_parties.csv). Id repetido exacto (ocid,id): tenderers=0, parties=0 filas. Mismo nombre con >1 id en un proceso: 156 filas de tenderers. En todo el lote, 1221 de 32752 nombres de postor usan más de un id (sobre todo extranjeros con id generado 'PE-RUC-L…'). Ejemplos: `ocds-dgv273-seacev3-1221875`, `ocds-dgv273-seacev3-1222026`, `ocds-dgv273-seacev3-1222366`, `ocds-dgv273-seacev3-1222370`, `ocds-dgv273-seacev3-1223239`.
- **R5** (com_contracts.csv (+ muestra API)). Procesos afectados: 9,046 de 20,452. El CSV mensual NO incluye la columna contracts/status: en el CSV el 100% queda sin estado. Muestra de la API (JSON, 60 records de /records): 46 de 52 contratos sin status (88.5%). Ejemplos: `ocds-dgv273-seacev3-1238201`, `ocds-dgv273-seacev3-1224465`, `ocds-dgv273-seacev3-1228797`, `ocds-dgv273-seacev3-1226639`, `ocds-dgv273-seacev3-1226350`.
- **R6a** (com_ten_documents.csv, com_con_documents.csv). Procesos afectados: 0 de 20,452. Códigos encontrados: {"biddingDocuments": 47849, "awardNotice": 16801, "evaluationReports": 13306, "clarifications": 13100, "contractSigned": 11702, "contractAnnexe": 1700, "nan": 754}
- **R6b** (com_ten_documents.csv, com_con_documents.csv). Procesos afectados: 617 de 20,452.  Ejemplos: `ocds-dgv273-seacev3-1226306`, `ocds-dgv273-seacev3-1224167`, `ocds-dgv273-seacev3-1227115`, `ocds-dgv273-seacev3-2026-2383-138`, `ocds-dgv273-seacev3-1229115`.
- **R7a** (com_awards.csv vs com_contracts.csv). Procesos afectados: 5,032 de 20,452.  Ejemplos: `ocds-dgv273-seacev3-1245462`, `ocds-dgv273-seacev3-1226306`, `ocds-dgv273-seacev3-2026-1003000933-33`, `ocds-dgv273-seacev3-1224167`, `ocds-dgv273-seacev3-2026-1926-114`.
- **R7b** (com_contracts.csv vs com_awards.csv). Procesos afectados: 3 de 20,452.  Ejemplos: `ocds-dgv273-seacev3-1228579`, `ocds-dgv273-seacev3-2026-326-9`, `ocds-dgv273-seacev3-1244803`.
- **R8a** (com_parties.csv (comprador)). Método usado por proceso: {"departamento": 20452}
- **R9a** (com_parties.csv (comprador)). Departamentos con más de una grafía en el dato crudo: 0.
- **R9b** (records.csv, com_awa_suppliers.csv). Columnas revisadas: descripcion, comprador_nombre, tipo_procedimiento, proveedores Ejemplos: `ocds-dgv273-seacev3-1239885`, `ocds-dgv273-seacev3-1239177`, `ocds-dgv273-seacev3-1236320`.

## Procesos por departamento

| Departamento | Procesos |
|---|---:|
| LIMA | 5,633 |
| CUSCO | 1,684 |
| ANCASH | 1,360 |
| PUNO | 1,177 |
| JUNIN | 958 |
| APURIMAC | 866 |
| AREQUIPA | 847 |
| CAJAMARCA | 844 |
| LA LIBERTAD | 768 |
| HUANUCO | 615 |
| AYACUCHO | 600 |
| PIURA | 584 |
| LAMBAYEQUE | 473 |
| LORETO | 455 |
| MOQUEGUA | 428 |
| UCAYALI | 421 |
| HUANCAVELICA | 415 |
| TACNA | 390 |
| SAN MARTIN | 360 |
| CALLAO | 358 |
| ICA | 353 |
| AMAZONAS | 267 |
| PASCO | 259 |
| MADRE DE DIOS | 195 |
| TUMBES | 142 |

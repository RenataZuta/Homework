# cv_experience_ocr_bert — Tarea 3 (HW_04_202602)

Predicción de años de experiencia a partir de **imágenes de CVs** (dataset PopResume, `sumin-yu/PopResume`):
OCR con PaddleOCR → texto limpio → modelos (baselines y BERT).

Este directorio contiene el repo del trabajo grupal. **Persona 1 (datos, OCR y calidad)** entrega `src/utils.py`,
`src/download_data.py`, `src/ocr_extraction.py`, `src/ocr_quality.py`, `src/preprocessing.py` y `src/split.py`.

## Estructura

```
app.py  README.md  requirements.txt
src/        utils, download_data, ocr_extraction, ocr_quality, preprocessing, split (+ módulos de Personas 2 y 3)
data/raw/        imágenes + metadata.csv + reference_texts.csv        (no se versiona)
data/ocr/        un JSON por CV (texto, líneas, confianza, tiempos)    (no se versiona; se comparte aparte)
data/processed/  ocr_quality.csv, clean_texts.csv
data/splits/     train.csv, val.csv, test.csv
models/{baselines,bert}/   (no se versiona)
output/{figures,tables,metrics}/   reportes de cada paso
video/
```

## Entorno

```bash
conda create -n tarea3 python=3.12 && conda activate tarea3
pip install paddlepaddle==3.3.1          # primero Paddle…
pip install -r requirements.txt          # …luego el resto (paddleocr 3.x incluido)
```

PopResume es un dataset **restringido (gated)**: aceptar las condiciones en
<https://huggingface.co/datasets/sumin-yu/PopResume>, crear un token de lectura y guardarlo con
`python scripts/set_hf_token.py` (entrada oculta; queda en `.env`, ignorado por git).

## Pipeline de Persona 1 (ejecutar desde `Tarea 3/`, en este orden)

```bash
python -m src.download_data            # 800 CVs sin foto por ocupación (--n 400 si falta cómputo)
python -m src.ocr_extraction           # JSON por CV en data/ocr/  (reanudable; --shard k/n para paralelizar)
python -m src.ocr_quality              # CER, WER, exactitud de años → data/processed/ocr_quality.csv
python -m src.preprocessing --sample-read 50       # leer textos OCR antes de fijar los regex
python -m src.preprocessing --analyze-threshold    # elegir el umbral de confianza con datos
python -m src.preprocessing            # → data/processed/clean_texts.csv
python -m src.split                    # → data/splits/{train,val,test}.csv
```

## Decisiones de diseño

- **Muestreo:** streaming por ocupación, solo `has_photo == False`, `shuffle(seed=42, buffer_size=5000)` y `take(n)`.
  La muestra es aleatoria dentro de la ventana del buffer (no sobre todo el parquet): es la consecuencia de usar streaming.
- **Orden de lectura del OCR:** cajas ordenadas de arriba a abajo; a la misma altura (|Δy del centro| < 15 px)
  de izquierda a derecha. Cada línea guarda su índice de fila (`row`).
- **Enmascarado:** `[MASKED]` para «X years of experience», «X+ years», variantes y edad / fecha de nacimiento.
  Las fechas de trabajos y de graduación **no** se tocan. Se reporta cuántos CVs quedaron enmascarados y cuántos
  conservan alguna frase residual «N years» (duraciones de empleo, que no se enmascaran). En la corrida real no
  hubo coincidencias (ver Resultados).
- **Semillas:** `RANDOM_SEED = 42` en `src/utils.py` (`set_all_seeds`).

## Resultados de Persona 1 (corrida real, 4000 CVs)

Los reportes completos están en `output/metrics/` y `output/tables/`.

**Muestreo** (`sampling_report.json`): 800 CVs sin foto por ocupación (4000 en total). `exp_year` es **continuo**
(0,003 a 25,45; media 6,53; mediana 5,57). Solo **29 CVs (0,73 %)** llegan a 20 años o más, muy por debajo del 15 %
que obligaría a subir el tope: **el tope de 20 se mantiene**.

**OCR** (`ocr_report.json`): PaddleOCR 3.7.0 / PaddlePaddle 3.3.1, perfil por defecto (PP-OCRv6 medium), solo CPU
(Apple M2, 8 GB). 4000/4000 CVs procesados, **0 fallidos**. Tiempo total 122 306 s (suma de tres procesos en
paralelo), **30,6 s por CV** de media (mediana 29,9 s). Confianza media 0,9953, 14,4 líneas por CV.

**Calidad del OCR** (`ocr_quality.json`, frente al texto de referencia, textos normalizados):

| Métrica | Media | Mediana | p90 | Máx. |
|---|---|---|---|---|
| CER | 0,0001 | 0 | 0 | 0,0075 |
| WER | 0,0004 | 0 | 0 | 0,0222 |

Los años (24 429 en la referencia) se leen **al 100 %**. Por ocupación, el peor caso es `software_developers`
(CER 0,0002, WER 0,0012). Este OCR es casi perfecto porque los CVs de PopResume son plantillas limpias de una columna.
Limitación: en 13 CVs el OCR cortó el final de la última fecha (p. ej. `2020.02–2023.` en lugar de `2020.02–2023.01`).

**Preprocesamiento** (`preprocessing_report.json`):
- Umbral de confianza **0,5**: ninguna línea tiene confianza menor a 0,95, así que no descarta nada y funciona como red
  de seguridad. Subirlo a 0,97 o más borra texto correcto (CER 0,0001 → 0,0018 con 0,97, 0,026 con 0,98 y 0,21 con
  0,99; ver `confidence_threshold_analysis.csv`).
- PII: se quita el bloque de cabecera (nombre, ciudad, teléfono, email). Tras limpiar no queda ningún email, teléfono
  ni URL.
- **Enmascarado: 0 CVs (0 %)**. Se leyeron textos OCR completos (más de 25 en detalle y unos 280 con revisión automática) y luego se escanearon los 4000 con los patrones: no contienen frases de
  «years of experience», «X+ years», edad ni fecha de nacimiento, así que no hay nada que enmascarar
  (`masking_examples.csv` queda vacío). Los patrones siguen activos por si otro dataset sí las trae.
- Ningún CV perdió un año al limpiar (las fechas de empleo y graduación se conservan).

**Split** (`split_report.json`): train 2800 / val 600 / test 600 (70/15/15), estratificado por ocupación y banda
(0-2, 3-5, 6-10, 11-20), seed 42. La diferencia máxima entre conjuntos es de 0,33 puntos porcentuales por banda,
0,20 por ocupación y 0,17 por celda ocupación × banda. `exp_year` medio: 6,519 / 6,553 / 6,533.

### Qué debe saber el resto del equipo

1. **La experiencia está en las fechas.** Los textos no dicen cuántos años de experiencia hay, pero se deduce de los
   rangos del historial (`2020.05–2023.01`). Un modelo solo-texto debe aprender aritmética sobre fechas: un baseline
   con duraciones calculadas a mano (suma de rangos, años desde el primer empleo) probablemente será muy fuerte y
   BERT lo tendrá más difícil.
2. **`data/ocr/` no está en git.** Se comparte aparte en un zip junto con `data/raw/reference_texts.csv` y
   `data/raw/metadata.csv` (necesarios para la Pregunta 2). Sí están en git `data/splits/*.csv`,
   `data/processed/clean_texts.csv` y `data/processed/ocr_quality.csv`.
3. Como el OCR es casi perfecto, se espera que el gap de MAE entre texto OCR y texto de referencia sea muy chico.

## Pendiente

Pregunta 2 (¿cuánto cuesta el ruido del OCR?): cuando Persona 2 entregue los modelos, evaluar cada uno sobre texto
OCR y sobre texto de referencia del test, comparar el gap de MAE e indicar cuál modelo es más robusto.

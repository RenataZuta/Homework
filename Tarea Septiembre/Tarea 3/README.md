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
  conservan alguna frase residual «N years» (duraciones de empleo, que no se enmascaran).
- **Semillas:** `RANDOM_SEED = 42` en `src/utils.py` (`set_all_seeds`).

## Estado

Ver el informe de resultados reales (tiempos de OCR, CER/WER, CVs enmascarados, tamaños de split) en
`output/metrics/` y `output/tables/` una vez ejecutado el pipeline.

Pregunta 2 (¿cuánto cuesta el ruido del OCR?) se responde cuando Persona 2 entregue los modelos: evaluar cada
modelo sobre texto OCR y sobre texto de referencia del test y comparar el gap de MAE.

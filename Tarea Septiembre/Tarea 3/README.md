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

La Pregunta 2 ya tiene números calculados con los modelos de Persona 2 (ver más abajo, `output/tables/q2_ocr_noise.csv`);
Persona 1 solo debe revisarla y redactar su conclusión final si quiere ampliarla.

---

# Resultados de Persona 2 — baselines, BERT, evaluación y Preguntas 1, 2 y 3

Scripts (desde `Tarea 3/`): `src/model_common.py` (datos, métricas, predictores, perturbaciones), `src/baselines.py`,
`src/train_bert.py`, `src/evaluation.py`, `src/analysis_questions.py`. Orden de ejecución:

```bash
python -m src.baselines
python -m src.train_bert --model sentence-transformers/all-MiniLM-L6-v2 --epochs 12 --patience 4 --lr 1e-4 --tag minilm-l6_mse
python -m src.evaluation --bert-tag minilm-l6_mse
python -m src.analysis_questions --bert-tag minilm-l6_mse        # Preguntas 1, 2 y 3
```

Todos los modelos se entrenan solo con `train` (texto OCR limpio), eligen hiperparámetros con `val` y se miden una vez
en `test` (600 CVs). Entorno usado: Python 3.12, torch 2.14.1 (CPU), transformers 4.57.1, scikit-learn 1.9.1.
Las predicciones de cada modelo están en `output/predictions/` y las tablas en `output/tables/`.

## Modelos

| Modelo | Detalle |
|---|---|
| Mediana | mediana de train (5,54 años) |
| TF-IDF + Ridge | palabras 1-2 gramas, `sublinear_tf`, `min_df=2`. **Se mantienen números y años**: val MAE 0,969 con ellos vs. 1,671 sin ellos; α=0,1 elegido en val |
| MiniLM congelado + Ridge | `all-MiniLM-L6-v2`, normalizado. Texto largo: el CV se parte en trozos de líneas completas de ≤200 tokens y se promedian los embeddings (en la práctica 1 trozo: el CV más largo mide 161 tokens). α=0,03 |
| Regla de fechas (bonus) | suma de las duraciones de los rangos `AAAA.MM–AAAA.MM`. Variantes en val: `sum` y `union` MAE 0,0209, `span` (primer inicio → último fin) 0,749 → se elige `sum`. Si el OCR corta el mes final se asume enero |
| BERT regresor | `all-MiniLM-L6-v2` (22,7 M parámetros, arquitectura BERT) con `num_labels=1`, pérdida **MSE**, target `y/20`, predicción desescalada y recortada a [0, 20] |

**Hiperparámetros de BERT:** lr 1e-4 (AdamW, weight decay 0,01, calentamiento 10 % y decaimiento lineal), batch 16, hasta 12 épocas,
`max_len=256`, early stopping con paciencia 4 sobre el MAE de val (años), semilla 42. **Hardware:** Intel Core i5-10210U
(4 hilos), sin GPU, torch CPU. **Tiempo:** mediana de 534 s por época (~9 min), unas 1,8 h de entrenamiento efectivo (el
reloj marca 518 min porque el equipo se suspendió durante una época). **Elección del modelo:** se probó DistilBERT en una
corrida corta y era demasiado lento en CPU (decenas de minutos por época), por eso se usó MiniLM-L6.
**Texto largo:** con la cabeza (`head`) a 256 tokens, 0 % de los CVs se trunca (máximo 161 tokens), así que `head`,
`head_tail` y chunking dan exactamente lo mismo; se usa `head`. El mejor val MAE fue en la **última época (12)**: el early
stopping no llegó a activarse y con más épocas BERT podría mejorar algo (no se probó).

## Resultados en test (n = 600)

| Modelo | MAE | RMSE | ±1 año | ±2 | ±3 | Acc. bandas | F1 macro bandas | R² |
|---|---|---|---|---|---|---|---|---|
| Mediana | 3,502 | 4,536 | 19,2 % | 34,0 % | 51,7 % | 28,8 % | 0,112 | −0,049 |
| TF-IDF + Ridge | 1,018 | 1,361 | 57,8 % | 88,5 % | 96,8 % | 83,5 % | 0,843 | 0,906 |
| MiniLM congelado + Ridge | 1,392 | 1,828 | 45,2 % | 76,3 % | 91,7 % | 76,5 % | 0,774 | 0,830 |
| **BERT (MiniLM-L6 ajustado)** | **0,296** | **0,393** | **97,5 %** | **100 %** | **100 %** | **94,3 %** | **0,943** | **0,992** |
| Regla de fechas (bonus) | **0,023** | 0,033 | 100 % | 100 % | 100 % | 99,0 % | 0,990 | 1,000 |

Tabla completa: `output/tables/model_comparison.csv`. Gráficos: `output/figures/pred_vs_real.png` (con la línea de 45°),
`mae_by_band.png`, `mae_by_occupation.png`. Matrices de confusión por banda: `output/tables/confusion_*.csv`.

**Ganancia de BERT (bootstrap pareado, 2000 remuestreos, ΔMAE = MAE baseline − MAE BERT; Δ>0 = BERT mejor):**

| Frente a | ΔMAE | IC 95 % |
|---|---|---|
| Mediana | 3,206 | [2,988; 3,430] |
| TF-IDF + Ridge | 0,722 | [0,650; 0,798] |
| MiniLM congelado + Ridge | 1,095 | [0,999; 1,196] |
| Regla de fechas | **−0,273** | [−0,295; −0,253] |

BERT supera a los tres modelos aprendidos de forma significativa, pero **la regla de fechas lo supera a él** (también
significativo). Esto no es un fallo: en PopResume `exp_year` es prácticamente la suma de las duraciones de los empleos
(MAE de la regla 0,02 años), y la regla lo calcula de forma explícita.

**MAE por banda (años):**

| Modelo | 0-2 | 3-5 | 6-10 | 11-20 |
|---|---|---|---|---|
| TF-IDF + Ridge | 0,903 | 0,908 | 0,933 | 1,559 |
| MiniLM congelado + Ridge | 1,274 | 1,249 | 1,282 | 2,040 |
| BERT | 0,180 | 0,191 | 0,289 | 0,678 |
| Regla de fechas | 0,024 | 0,024 | 0,022 | 0,021 |

Por ocupación el MAE de BERT es parejo (0,27–0,33; la mejor, obreros de construcción; la peor, contadores).

## 10 mayores errores de BERT (`output/tables/bert_top10_errors.csv`)

Los 10 son **sobreestimaciones de 1,1 a 1,4 años** en CVs de **4 empleos y 12–19 años de experiencia**
(la banda 11-20, que además es la más escasa en train). La regla acierta en los 10 (error < 0,05 años).
Causas: **5 con huecos de carrera** entre empleos y **5 sin causa de OCR** (error de aritmética de fechas con 4 empleos).
No hay ningún caso de fecha mal leída, orden de lectura, fechas faltantes, trabajos solapados ni truncamiento: el OCR es casi
perfecto y ningún CV supera los 256 tokens. El error de BERT es de **aritmética**, no de lectura.

## Pregunta 1 — ¿Qué aprende BERT que los baselines no?

*Reducción de MAE:* BERT baja el MAE de 1,018 (TF-IDF) a 0,296 (−71 %, IC 95 % de la diferencia [0,65; 0,80]) y de 1,392
(embeddings) a 0,296. Ayuda en **todas las bandas**, sobre todo en la alta: 0,68 vs. 1,56 (TF-IDF) en 11-20 años.

*Prueba de perturbación* (`output/tables/q1_perturbation.csv`, 20 CVs de test con ≥2 empleos, semilla 42, y una muestra de 200 para
confirmar). (a) **Fechas +5 años**: la duración real no cambia, así que un modelo que lee duraciones debería dar la misma predicción.
(b) **Borrar el primer empleo**: la experiencia real baja justo lo que duraba; se mide cuánto sigue el modelo ese cambio
(pendiente 1 = lo sigue perfecto).

| Modelo (20 CVs) | Cambio medio de la predicción con fechas +5 | Pendiente al borrar un empleo | Correlación |
|---|---|---|---|
| TF-IDF + Ridge | 1,99 años | −0,55 | −0,67 |
| MiniLM + Ridge | 0,78 años | 1,04 | 0,65 |
| **BERT** | **2,41 años** | **−0,01** | **−0,01** |
| Regla de fechas | 0,00 | 1,00 | 1,00 |

(200 CVs: BERT 2,16 años, pendiente 0,21; TF-IDF 1,93, pendiente −0,24; regla 0,00, pendiente 0,90.)

**Conclusión: este BERT NO lee las fechas como una resta.** Con las fechas desplazadas cambia su respuesta unos 2 años, y al
borrar un empleo su predicción casi no se mueve (cuando debería bajar unos 2,8 años). Aprendió a reconocer los **años absolutos**
(probablemente el año del primer empleo, ya que todos los CVs terminan en 2023.01) y no a restar. Eso explica por qué gana a
TF-IDF pero queda muy lejos de la regla. Es una limitación real: sirve en este dataset sintético, pero no se generalizaría
a CVs con otra fecha de corte.

## Pregunta 2 — ¿Cuánto cuesta el ruido del OCR?

Se evalúa cada modelo sobre el texto OCR limpio y sobre el texto de referencia limpiado con las mismas reglas
(`output/tables/q2_ocr_noise.csv`). Como el OCR es casi perfecto (CER medio 0,0001; solo 14 de los 600 CVs de test tienen CER > 0),
la brecha total mezcla dos cosas, así que se separó:

| Modelo | MAE OCR | MAE OCR con formato armonizado | MAE referencia | Brecha de formato | **Brecha por ruido real** (IC 95 %) |
|---|---|---|---|---|---|
| Mediana | 3,502 | 3,502 | 3,502 | 0 | 0 |
| TF-IDF | 1,018 | 1,018 | 1,021 | 0 | −0,003 [−0,006; 0,001] |
| MiniLM + Ridge | 1,392 | 1,411 | 1,410 | −0,019 | +0,001 [−0,004; 0,005] |
| BERT | 0,296 | 0,358 | 0,359 | **−0,062** | −0,001 [−0,002; 0,000] |
| Regla de fechas | 0,0229 | 0,0229 | 0,0217 | 0 | **+0,0012** [0,000; 0,003] |

* Los textos OCR traen fin de línea `\r\n` y viñetas «•», y la referencia `\n` y «-». *Armonizado* = el OCR con esos dos
  cambios de formato, sin corregir ningún carácter mal leído.
* **El ruido real de caracteres cuesta prácticamente nada** (≤ 0,003 años en todos los modelos), porque los CVs de PopResume
  son plantillas limpias.
* **BERT es el más sensible al formato**: su MAE sube de 0,296 a 0,358 si cambian solo las viñetas y los saltos de línea,
  porque se entrenó con el estilo exacto del OCR. Por eso la brecha «OCR − referencia» da negativa (el OCR parece «mejor»:
  es el formato con el que aprendió, no una mejora real).
* **TF-IDF y la mediana son los más robustos** a esos cambios (ignoran la puntuación). **La regla de fechas es la única a la
  que sí le afecta el ruido real** (5 % relativo; en los 14 CVs con CER > 0 su MAE sube de 0,021 a 0,070), por las fechas
  truncadas tipo `2020.02–2023.`.

## Pregunta 3 — Sensibilidad metodológica (`output/tables/q3_sensitivity.csv`)

| Decisión | Variante | TF-IDF (reentrenado) | Regla | BERT (sin reentrenar) |
|---|---|---|---|---|
| Números en TF-IDF | con números | 1,018 | — | — |
| | sin números | **1,782** | — | — |
| Limpieza del OCR | limpio (por defecto) | 1,018 | 0,023 | 0,296 |
| | crudo (sin limpiar, con cabecera) | 1,084 | 0,023 | 1,750 |
| | solo líneas con confianza ≥ 0,99 | 1,429 | 1,872 | 1,168 |
| Texto largo (BERT, solo inferencia) | `max_len` 256 cabeza / cabeza+cola | — | — | 0,296 / 0,296 |
| | 96 tokens | — | — | 0,344 / 1,445 |
| | 64 tokens | — | — | 1,599 / 3,911 |

* **Quitar los números empeora TF-IDF un 75 %** (1,02 → 1,78): los años son casi toda la señal.
* **Descartar líneas con umbral alto destruye texto correcto** (el OCR casi nunca baja de 0,95 de confianza): la regla
  pasa de 0,02 a 1,87. Por eso el umbral se mantiene en 0,5. El texto crudo apenas daña a TF-IDF (1,08) pero sí a BERT, que
  no vio esa cabecera en el entrenamiento (1,75; esa celda es solo inferencia, no un reentrenamiento).
* **Texto largo:** con los CVs reales no hay diferencia (ninguno se trunca). En la prueba de estrés con un tope artificial,
  `head` se degrada más despacio que `head_tail`, porque los empleos recientes (los de arriba) pesan más; ninguna estrategia
  es necesaria para este dataset.
* **MSE vs. Huber:** no se corrió Huber (`--loss huber` está implementado en `train_bert.py`); entrenar otro BERT en CPU
  costaba ~2 h. Queda como limitación. Tampoco se reentrenó BERT con cada variante de limpieza (solo se evaluó).

## Mejoras posibles

* Entrenar más épocas (el mejor val fue la última) o con GPU para probar DistilBERT/DeBERTa.
* Ayudar a BERT a hacer aritmética real: darle duraciones ya calculadas o aumentar los datos desplazando fechas (el
  desplazamiento +5 años fue justo lo que lo desorientó).
* Entrenar con varios formatos de texto (viñetas, fin de línea) para eliminar la sensibilidad de formato.
* Combinar BERT con la regla (como feature o como respaldo cuando las fechas están completas).

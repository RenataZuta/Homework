# Tarea 4 — From Voice to Record

Sistema ASR que convierte entrevistas laborales y llamadas de ventas en registros estructurados y verificables usando Whisper (`faster-whisper`). Issue: [d2cml-ai/Data-Science-Python#195](https://github.com/d2cml-ai/Data-Science-Python/issues/195).

- **Tarea 1 (`tasks/task1_interview/`)**: entrevistas laborales → años de experiencia, último puesto, tecnologías, pretensión salarial, disponibilidad y nivel de inglés.
- **Tarea 2 (`tasks/task2_sales/`)**: llamadas de ventas → ítems, promoción, dirección de entrega, método de pago y total dicho.

El motor común está en `engine/` (transcripción, extracción, validación); la configuración base, en `config.yaml`.

## Documentación

- [Pipeline — From Voice to Record (HW05)](https://app.notion.com/p/Pipeline-From-Voice-to-Record-HW05-4056115a59c180839c95d663f3bdbd5c?source=copy_link) — documento del pipeline en Notion.

## Puesta en marcha

```bash
pip install -r requirements.txt
cp .env.example .env   # opcional: ANTHROPIC_API_KEY solo para el extractor LLM (de pago); por defecto no hace falta
```

## Comparar extractores (reglas vs LLM)

```bash
python -m engine.compare_extractors                       # solo reglas, sin clave: exactitud por campo vs ground truth
python -m engine.compare_extractors --llm api --confirm-api   # API real (de pago, ANTHROPIC_API_KEY); 10 llamadas, tope --max-calls
python -m engine.compare_extractors --llm answers --answers tasks/comparison/llm_answers_simulado.json   # respuestas simuladas
```

Usa las transcripciones cacheadas de la mejor configuración del benchmark (no hace ASR). `--llm answers` prueba el flujo sin clave, pero
sus respuestas están escritas a mano viendo el ground truth: **no son una medición del LLM**.

## Escalera de degradación L0–L3

```bash
python tasks/task2_sales/degradation/build_ladder.py --input_dir tasks/task2_sales/audio --preset l0-l3
```

Genera `L0/` (original), `L1/` (Opus 24 kbps mono, estilo nota de voz de WhatsApp), `L2/` (pasa-banda 300–3400 Hz a 8 kHz, estilo llamada) y `L3/` (L1 + ruido ambiente a SNR 10 dB) y el manifiesto `ladder_l0_l3_manifest.csv` con el SNR real de cada archivo. Opus usa `ffmpeg` si está en el PATH y, si no, PyAV con el mismo códec. L3 usa ruido rosa sintético por defecto; con `--noise-file RUTA` mezcla una grabación real; el repo trae un ambiente de restaurante de dominio público en `tasks/task2_sales/degradation/noise/` (fuente y licencia en su README). Sin `--preset` se genera la escalera de 12 niveles de siempre; para transcribir L0–L3 con el benchmark hay que pedirlos: `--ladder-dir ... --levels L0 L1 L2 L3`.

L3 publicado (audios, manifiesto y transcripciones) usa el ruido real `Restaurant_ambience.ogg` (`--noise-file`). Las transcripciones de L0–L3 (`medium` y `large-v3`, `float16`, GPU) están en `tasks/task2_sales/transcriptions_cache/` y los resultados en `tasks/task2_sales/metrics/l0_l3_*.csv` (`wer_*`: WER por nivel; `detail/summary/validation`: extracción por reglas y aritmética del pedido por nivel). Para regenerar estos últimos sin ASR: `python -m engine.evaluate_ladder --levels L0 L1 L2 L3 --prefix l0_l3`. Además genera `l0_l3_detection.csv`: por modelo y nivel, cuántas trampas del ground truth (totales mal dichos a propósito) detectó la aritmética del pedido y cuántas se le escaparon.

## Métricas de extracción en dos capas (entrevistas)

```bash
python tasks/task1_interview/metrics/compute_extraction_metrics.py          # reglas; --llm answers|api para el camino LLM
```

Compara los campos extraídos con el ground truth (accuracy por campo, MAE en los numéricos, macro F1 de `nivel_ingles`), la tabla de dos capas (transcripción: WER/CER; registro: campos correctos) y los dos contrastes para el video: **WER alto con registro perfecto** y **WER bajo con registro roto**. Salida en `tasks/task1_interview/metrics/extraction_metrics_*.csv`.

## Interfaz (Streamlit)

```bash
pip install -r requirements.txt
streamlit run app.py        # desde esta carpeta; se abre en http://localhost:8501
```

Cuatro pestañas: **Probador** (sube un audio y obtén transcripción, campos extraídos, verificación y, en ventas, la aritmética del pedido), **Benchmark** (WER/CER, tiempo y VRAM por modelo × precisión × dispositivo), **Escalera de degradación** (cuánto sube el WER al degradar el audio) y **Ejemplos** (guion, ground truth y transcripciones lado a lado). Usa el extractor por reglas, sin API ni clave. En CPU, `tiny` y `base` responden en segundos; `medium` y `large-v3` tardan bastante. La app solo escucha en `localhost` (ver `.streamlit/config.toml`).

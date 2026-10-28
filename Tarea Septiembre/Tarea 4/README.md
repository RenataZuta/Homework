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

## Interfaz (Streamlit)

```bash
pip install -r requirements.txt
streamlit run app.py        # desde esta carpeta; se abre en http://localhost:8501
```

Cuatro pestañas: **Probador** (sube un audio y obtén transcripción, campos extraídos, verificación y, en ventas, la aritmética del pedido), **Benchmark** (WER/CER, tiempo y VRAM por modelo × precisión × dispositivo), **Escalera de degradación** (cuánto sube el WER al degradar el audio) y **Ejemplos** (guion, ground truth y transcripciones lado a lado). Usa el extractor por reglas, sin API ni clave. En CPU, `tiny` y `base` responden en segundos; `medium` y `large-v3` tardan bastante. La app solo escucha en `localhost` (ver `.streamlit/config.toml`).

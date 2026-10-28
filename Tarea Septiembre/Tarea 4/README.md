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
cp .env.example .env   # completar ANTHROPIC_API_KEY y HF_TOKEN
```

# Comparación de modelos de embeddings locales

> **PROVISIONAL.** Estas métricas dependen de `eval/preguntas.csv`, cuyas páginas esperadas aún no han sido validadas por la persona (Fase 3, punto manual). Se recalculan sin cambios de código cuando `eval.set_validado` pasa a `true`.

Mismos 1260 fragmentos (troceado `c1000_o150`: 1000 caracteres, solape 150) y las 21 preguntas in_domain del set de evaluación. Sin llamar al LLM. CPU, sin GPU.

| Modelo | Params (M) | Dim | Máx. tokens | Prefijos | % truncados | Indexación (s) | Consulta (ms) | R@1 | R@3 | R@5 | R@3 modif. | MRR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| intfloat/multilingual-e5-small | 118 | 384 | 512 | sí | 0.0 | 59.7 | 21.9 | 0.714 | 0.810 | 0.857 | 0.800 | 0.771 |
| intfloat/multilingual-e5-base | 278 | 768 | 512 | sí | 0.0 | 229.1 | 60.9 | 0.714 | 0.762 | 0.762 | 0.600 | 0.738 |
| sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 | 118 | 384 | 128 | no | 91.6 | 24.2 | 15.7 | 0.571 | 0.667 | 0.667 | 0.400 | 0.611 |
| BAAI/bge-m3 | 568 | 1024 | 8192 | no | 0.0 | 503.4 | 134.0 | 0.762 | 0.810 | 0.857 | 0.800 | 0.790 |

**% truncados** = fragmentos cuya longitud en tokens (con el prefijo) supera la longitud máxima real del modelo: lo que exceda se descarta en silencio al calcular el vector. **R@3 modif.** = Recall@3 de las preguntas de versiones exigiendo el fragmento del DS 001.

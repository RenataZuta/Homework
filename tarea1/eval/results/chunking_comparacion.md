# Comparación de tamaño y solapamiento de fragmentos

> **PROVISIONAL.** Estas métricas dependen de `eval/preguntas.csv`, cuyas páginas esperadas aún no han sido validadas por la persona (Fase 3, punto manual). Se recalculan sin cambios de código cuando `eval.set_validado` pasa a `true`.

Modelo: `intfloat/multilingual-e5-small` (máx. 512 tokens). Un índice por configuración; 21 preguntas in_domain; sin llamar al LLM.

| Configuración | Tamaño | Solape | Encab. contexto | Fragmentos | Mediana car. | < 150 car. | % truncados | Indexación (s) | R@1 | R@3 | R@5 | R@3 modif. | MRR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| c500_o50 | 500 | 50 | True | 2447 | 406 | 44 | 0.0 | 51.9 | 0.810 | 0.810 | 0.857 | 0.600 | 0.821 |
| c750_o100 | 750 | 100 | True | 1674 | 625 | 7 | 0.0 | 53.7 | 0.762 | 0.905 | 0.905 | 0.800 | 0.825 |
| c750_o100_sinctx | 750 | 100 | False | 1674 | 625 | 7 | 0.0 | 46.9 | 0.762 | 0.857 | 0.905 | 0.600 | 0.821 |
| c1000_o150 | 1000 | 150 | True | 1260 | 843 | 4 | 0.0 | 51.1 | 0.714 | 0.810 | 0.857 | 0.800 | 0.771 |
| c1500_o200 | 1500 | 200 | True | 800 | 1286 | 0 | 0.0 | 49.9 | 0.810 | 0.810 | 0.857 | 0.800 | 0.821 |
| c1000_o150_sinctx | 1000 | 150 | False | 1260 | 843 | 4 | 0.0 | 48.4 | 0.714 | 0.857 | 0.905 | 0.800 | 0.787 |

**Ganadora: `c750_o100`** (criterio: mayor Recall@3; empate, mayor Recall@5; empate, menos fragmentos).

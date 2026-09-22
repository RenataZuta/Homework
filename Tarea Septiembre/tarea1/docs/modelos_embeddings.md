# Elección del modelo de embeddings local

Verificado el **21-sep-2026** en las tarjetas oficiales de Hugging Face (`https://huggingface.co/<modelo>/raw/main/README.md` y
`sentence_bert_config.json`). Lo que exige cada modelo NO se dio por sabido: se leyó de su tarjeta.

## Lo que dice cada tarjeta

| Modelo | Dim | Longitud máx. de entrada | ¿Prefijos? |
|---|---:|---:|---|
| `intfloat/multilingual-e5-small` | 384 | **512 tokens** (`sentence_bert_config`: `max_seq_length: 512`; tarjeta: *«Long texts will be truncated to at most 512 tokens»*) | **Sí**: `query: ` para la consulta y `passage: ` para el pasaje. Tarjeta, FAQ: *«Do I need to add the prefix "query: " and "passage: " to input texts? Yes, this is how the model is trained, otherwise you will see a performance degradation»* |
| `intfloat/multilingual-e5-base` | 768 | 512 tokens | Sí, los mismos |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | 384 | **128 tokens** (`max_seq_length: 128`) | No |
| `BAAI/bge-m3` | 1024 | 8192 tokens (tarjeta: *«up to 8192 tokens»*) | No para recuperación densa |

Cómo se aplica en el código: los prefijos salen de `config.yaml` (`embeddings.local.prefijo_consulta` / `prefijo_pasaje`) y los pone la
propia clase `LocalSentenceTransformers`; quien la usa nunca los escribe. La longitud máxima que se reporta es la **real** del modelo
(`model.max_seq_length`), no la que diga la configuración.

## Relación entre el tamaño del fragmento y el límite de entrada

Los fragmentos de 1000 caracteres miden ~250 tokens en español. Con el límite de **512** de E5 caben con margen (0 truncados). Con
el de **128** de MiniLM se descartaría en silencio más de la mitad de cada fragmento: **91,6 % de los fragmentos truncados**. Es la
trampa clásica: el índice se construye sin errores y el modelo simplemente no "lee" el final de cada fragmento.

## Resultado de la comparación (mismos 1 260 fragmentos, sin llamar al LLM, CPU)

Tabla completa en `eval/results/modelos_locales.md`. **PROVISIONAL** hasta que la persona valide el set de evaluación (21 preguntas: una
pregunta equivale a 4,8 puntos de Recall, así que diferencias de una pregunta son ruido).

| Modelo | Params | R@1 | R@3 | R@5 | Indexación | Consulta | % truncados |
|---|---:|---:|---:|---:|---:|---:|---:|
| **multilingual-e5-small** | **118 M** | 0,714 | **0,810** | **0,857** | **60 s** | **22 ms** | 0 |
| multilingual-e5-base | 278 M | 0,714 | 0,762 | 0,762 | 229 s | 61 ms | 0 |
| paraphrase-multilingual-MiniLM-L12-v2 | 118 M | 0,571 | 0,667 | 0,667 | 24 s | 16 ms | 91,6 |
| bge-m3 | 568 M | 0,762 | 0,810 | 0,857 | 503 s | 134 ms | 0 |

## Decisión: `intfloat/multilingual-e5-small`

- **Recupera igual que el mejor** en R@3 y R@5 (empata con bge-m3) y solo pierde una pregunta en R@1, una diferencia dentro del ruido con 21 preguntas.
- **Cuesta una fracción**: 118 M de parámetros frente a 568 M (≈ 0,47 GB frente a ≈ 2,3 GB en float32), indexa ocho veces más rápido y contesta cada consulta seis
  veces más rápido. Eso decide el despliegue público (Fase 12): una app gratuita con ~1 GB de memoria no carga bge-m3.
- **El modelo más grande de su familia no mejora** (e5-base: 0,762 en R@3): más parámetros no compensan en un corpus de ~1 300 fragmentos.
- **MiniLM se descarta** por truncar casi todos los fragmentos y por su Recall inferior.
- Requiere los prefijos `query: ` / `passage: `, ya implementados y probados.

Limitaciones: la comparación usa un solo set de 21 preguntas y el mismo troceado (1000/150); con otro troceado el orden podría cambiar. Los candidatos
son los que caben en una laptop sin GPU; no se probaron modelos de API distintos a `text-embedding-3-small` (Fase 6).

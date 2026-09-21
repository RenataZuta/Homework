# Qué mide cada métrica de evaluación (y por qué evaluar cuesta USD 0)

El sistema es un pipeline de etapas. Cada métrica evalúa **una** etapa; ninguna evalúa todo.

| Métrica | Qué pregunta responde | Etapa que evalúa | ¿Llama al LLM? |
|---|---|---|---|
| **Recall@1 / @3 / @5** | ¿El fragmento con la respuesta (documento y página esperados) está entre los k más similares? | **Recuperación**: troceado + embeddings + índice | No |
| **Recall de la modificatoria** | En las preguntas de versiones, ¿aparece el fragmento del DS 001-2026-EF entre los k primeros? Traer solo el original desactualizado no cuenta | Recuperación + manejo de versiones | No |
| **Tasa de abstención correcta** (fuera de dominio) | Cuando la pregunta no es del corpus, ¿la compuerta corta antes de llamar al modelo? | **Compuerta del umbral** | No |
| **Tasa de abstención incorrecta** (dentro del dominio) | ¿La compuerta descarta preguntas que sí se podían responder? | **Compuerta del umbral** | No |
| Calidad de la respuesta (citas correctas, ausencia de invenciones) | ¿Lo que dice el modelo es fiel al contexto? | **Generación** | **Sí** (`eval_end_to_end.py`) |

## Lo que NO dicen

- Un Recall@3 alto no garantiza una buena respuesta: el modelo aún puede leer mal un fragmento correcto.
- Una abstención «correcta» de la compuerta no prueba que el sistema sepa lo que no sabe: solo que la similitud del mejor fragmento quedó bajo el umbral. Con
  modelos multilingües las similitudes están comprimidas (aquí, preguntas del dominio 0,837–0,931 frente a 0,795–0,893 fuera del dominio), de modo que la
  compuerta separa poco y el LLM (`contexto_suficiente`) es una segunda línea de defensa que estas métricas no miden.
- El set de evaluación es pequeño (21 preguntas del dominio: una pregunta equivale a 4,8 puntos de Recall) y el umbral se calibró con el mismo set con que se evalúa.

## Por qué importa que la evaluación cueste USD 0

`run_eval.py` no llama al modelo de generación: usa solo el índice local y el modelo de embeddings local. Eso tiene tres consecuencias:

1. **Puede correr en cada cambio.** Se ejecuta en segundos tras cada modificación del troceado, del modelo o del umbral, y en el CI en cada `push`. Una evaluación que
   cuesta dinero se corre «cuando hace falta» y las regresiones se descubren tarde.
2. **Es reproducible y determinista.** No depende de la red, de la cuota de un proveedor ni de la temperatura de un modelo generativo.
3. **Permite una compuerta de calidad.** El CI falla si Recall@3 cae por debajo del mínimo (`eval.min_recall_at_3`), sin exigir secretos: un colaborador o un
   revisor puede ejecutarla sin claves.

La evaluación de la generación (`eval_end_to_end.py`) sí cuesta unos centavos (una llamada por pregunta) y por eso se ejecuta a mano, no en cada push.

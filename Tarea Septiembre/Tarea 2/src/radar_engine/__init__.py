"""Motor RAG híbrido de la Tarea 2 (procesos de contratación): filtros estructurados + búsqueda semántica.

Reutiliza de la Tarea 1 (``../Tarea 1/src/rag_engine/``, ver ``bootstrap_t1.py``): embeddings, cliente de LLM,
log y tabla de precios, y las primitivas genéricas del índice ChromaDB. No reutiliza ``rag_engine.retrieval``
ni ``rag_engine.engine`` porque ambos están escritos para metadatos documento/versión/página; aquí los
metadatos son ocid/departamento/monto/fecha/categoría (ver ``store.py`` y ``engine.py``).

Este paquete se llama ``radar_engine`` (no ``rag_engine``) a propósito: si se llamara igual, importar
``rag_engine`` desde aquí sería ambiguo en cuanto ambas carpetas ``src`` estuvieran en ``sys.path``.
"""

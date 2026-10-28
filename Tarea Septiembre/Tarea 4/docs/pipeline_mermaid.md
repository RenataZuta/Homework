# Pipeline — versión Mermaid

Mismo diagrama que `pipeline_diagram.png` (generado con `pipeline_diagram.py`), en texto. Azul = carril 1 (una vez), verde = carril 2 (por cada audio nuevo), rojo punteado = descartado.

```mermaid
flowchart TD
    subgraph L1["CARRIL 1 — se ejecuta UNA VEZ"]
        direction TB
        A1["<b>1. Escribir guiones de entrevista y ventas</b><br/>5 entrevistas + 5 llamadas de ventas (restaurante)<br/><i>▸ Trampas plantadas: correcciones, total incorrecto, dirección con dígitos</i>"]
        A2["<b>2. Grabar audios con compañero</b><br/>Entrevistador/operador + candidato/cliente<br/><i>▸ Voz real grabada, no audio generado</i>"]
        A3["<b>3. Escribir ground truth</b><br/>Gratis: sale de los guiones, escritos antes de grabar<br/><i>▸ El ground truth viene del guion, no de un ASR</i>"]
        A4["<b>4. Transcribir corpus completo en GPU</b><br/>faster-whisper, español, los 10 audios<br/><i>▸ Modelo large-v3 · precisión float16</i>"]
        A5["<b>5. Cachear transcripciones en JSON</b><br/>transcriptions_cache/ (se commitean)<br/><i>▸ Las métricas se reproducen sin volver a transcribir</i>"]
        A1 --> A2 --> A3 --> A4 --> A5
    end

    subgraph L2["CARRIL 2 — se ejecuta POR CADA AUDIO NUEVO"]
        direction TB
        B1["<b>1. Transcribir audio</b><br/>faster-whisper, español<br/><i>▸ Modelo medium · precisión int8</i>"]
        B2["<b>2. Extraer campos</b><br/><i>▸ Dos caminos independientes para contrastar el resultado</i>"]
        B2a["Regex (reglas)"]
        B2b["LLM (Claude)"]
        B3["<b>3. Normalizar números hablados</b><br/>'seis mil quinientos' → 6500<br/><i>▸ Regla: palabras → dígitos (text2num, español) antes de verificar</i>"]
        B4["<b>4. Verificar literalmente</b><br/>¿El valor existe en la transcripción?<br/><i>▸ Regla: valor sin respaldo literal → queda marcado con flag</i>"]
        Q{"¿Es llamada<br/>de ventas?"}
        B5["<b>5. Validar aritmética [solo ventas]</b><br/>¿cantidad × precio − promo = total?<br/><i>▸ Se compara el total dicho contra el recalculado</i>"]
        B6["<b>6. Diagnosticar errores</b><br/>¿El error es del ASR o del hablante?<br/><i>▸ ASR: la transcripción no refleja lo dicho · Hablante: lo dicho ya estaba mal</i>"]
        B7["<b>7. Retornar registro</b><br/>Campos extraídos + flags de verificación"]
        B1 --> B2
        B2 --> B2a & B2b
        B2a & B2b --> B3
        B3 --> B4 --> Q
        Q -- "Sí (ventas)" --> B5 --> B6
        Q -- "No (entrevista)" --> B6
        B6 --> B7
    end

    X1["✗ Descartado: corpus sintético (demasiado limpio)"]
    X2["✗ Descartado: YouTube captions como ground truth (circular)"]
    X1 -.- A2
    X2 -.- A3

    classDef once fill:#dbeafe,stroke:#1d4ed8,stroke-width:2px,color:#111
    classDef perAudio fill:#dcfce7,stroke:#15803d,stroke-width:2px,color:#111
    classDef discard fill:#fee2e2,stroke:#b91c1c,stroke-width:2px,stroke-dasharray:5 3,color:#7f1d1d
    class A1,A2,A3,A4,A5 once
    class B1,B2,B2a,B2b,B3,B4,Q,B5,B6,B7 perAudio
    class X1,X2 discard
```

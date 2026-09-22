# Cómo desplegar la app públicamente en Streamlit Community Cloud (Fase 12) [MANUAL]

## Antes de empezar: memoria medida en local (2026-09-22)

Medí el consumo real de RAM del motor (sin Streamlit todavía) en esta máquina: **883 MB** apenas se carga el modelo de
embeddings local (`multilingual-e5-small` + PyTorch); abrir el índice y hacer consultas no lo sube más. Sumando el propio
servidor de Streamlit, es razonable esperar que la app pase de 1 GB. La cifra que más se cita para el límite gratuito de
Streamlit Community Cloud es **1 GB**, pero no encontré una página oficial que la confirme hoy con esas palabras exactas.
**Es un riesgo real, no teórico.** Si el despliegue falla por memoria, la salida más simple es cambiar
`embeddings.proveedor: gemini` en `config.yaml` (ya implementado y probado desde la Fase 6: sin PyTorch, sin el modelo local,
mucho más liviano) y hacer push; Streamlit Cloud vuelve a desplegar solo.

Se descartó Hugging Face Spaces (con Streamlit o con Docker) porque, según su documentación oficial, ahora exige el plan PRO
de pago para crear un Space que corre cómputo en una cuenta personal (ver Fase 11).

## 1. Preparar el repositorio (ya hecho en este commit)
- `data/index/` se agregó al repositorio (11 MB, no hace falta Git LFS): la app pública no tiene un paso de "build" propio,
  así que **nunca** reconstruye el índice al iniciar sesión — lo carga tal cual está en git.
- Los topes de gasto (`deploy.topes` en `config.yaml`) ya están activos en `app.py`: al alcanzarlos, aviso y CERO llamadas
  al LLM, sin importar dónde corra la app.

## 2. Crear la app en Streamlit Community Cloud
1. Entra a <https://share.streamlit.io> con tu cuenta de GitHub (gratis, sin tarjeta).
2. **New app** → elige el repositorio `RenataZuta/Homework`, rama `main`, **Main file path: `Tarea Septiembre/tarea1/app.py`**.
3. En **Advanced settings → Secrets**, pega (con tus valores reales, nunca los compartas conmigo):
   ```toml
   GEMINI_API_KEY = "<pega-aqui-tu-clave>"
   ```
   Streamlit expone las claves de nivel superior de `secrets.toml` también como variables de entorno normales, así que
   `rag_engine/config.py` las lee sin ningún cambio de código (usa `os.environ`, no algo específico de Streamlit).
4. **Deploy.** La primera vez descarga el modelo de embeddings (~500 MB): puede tardar varios minutos.

## 3. Verificar la aceptación de la fase
- [ ] La URL pública abre sin errores.
- [ ] Una pregunta del dominio responde con citas (documento, página, similitud).
- [ ] Una pregunta ajena («¿cómo se prepara un ceviche?») muestra el caso de abstención.
- [ ] Los topes funcionan: baja `deploy.topes.consultas_por_sesion` a 1 en una prueba, confirma el aviso, y vuelve a subirlo.
- [ ] Si la memoria no alcanza, cambia a `embeddings.proveedor: gemini` (ver arriba) y reintenta.

## 4. Poner el enlace en el README
Una vez desplegada, dime la URL pública y la agrego a `tarea1/README.md`.

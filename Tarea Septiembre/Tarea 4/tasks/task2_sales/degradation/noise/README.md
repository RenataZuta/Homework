# Ruido ambiente para L3

`Restaurant_ambience.ogg` — ambiente de un restaurante de tamaño medio (murmullo y conversaciones de fondo), 1 min 16 s,
Ogg Vorbis, 1 970 215 bytes.

- **Fuente**: [Wikimedia Commons, File:Restaurant ambience.ogg](https://commons.wikimedia.org/wiki/File:Restaurant_ambience.ogg)
  (archivo original: <https://upload.wikimedia.org/wikipedia/commons/b/b5/Restaurant_ambience.ogg>).
- **Licencia**: dominio público. La página del archivo dice: «This work has been released into the public domain by its
  author, stephan. This applies worldwide.» (origen: pdsounds.org).
- **SHA-256**: `0aeb1fa7a3d9647d3284e97d9880b6375b54db2eda6a517c64e3bb02ac8a51cc`

Uso (desde la carpeta de la Tarea 4):

```bash
python tasks/task2_sales/degradation/build_ladder.py --input_dir tasks/task2_sales/audio --preset l0-l3 \
    --noise-file tasks/task2_sales/degradation/noise/Restaurant_ambience.ogg
```

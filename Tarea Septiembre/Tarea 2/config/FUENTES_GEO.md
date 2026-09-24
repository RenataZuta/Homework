# Fuente del GeoJSON de departamentos (mapa coroplético, Fase 4)

- **Archivo:** `peru_departamentos.geojson` (25 features, un polígono por departamento).
- **Fuente:** [`juaneladio/peru-geojson`](https://github.com/juaneladio/peru-geojson) (repositorio público de dominio educativo, derivado de la cartografía del INEI), archivo `peru_departamental_simple.geojson`.
- **URL exacta:** `https://raw.githubusercontent.com/juaneladio/peru-geojson/master/peru_departamental_simple.geojson`
- **Descargado:** 2026-09-23.
- **Por qué esta fuente:** el enunciado permite "cualquier fuente declarada (puedes reutilizar la del Issue 2)"; este repositorio no tiene un Issue 2 con ese archivo, así que se buscó una fuente pública equivalente. Se verificó que trae exactamente 25 polígonos y que la propiedad `NOMBDEP` usa las mismas 25 grafías (mayúsculas, sin tildes) que `config/departamentos.yaml` — no hace falta ningún mapeo adicional entre el GeoJSON y la columna `departamento` de `procesos_validados.parquet`.
- **Por qué se versiona (no va en `data/raw/`, que está en `.gitignore`):** es un archivo estático de referencia (como `departamentos.yaml`), no un dato que se regenere descargando de OECE; sin él el mapa no se puede dibujar en una máquina limpia.

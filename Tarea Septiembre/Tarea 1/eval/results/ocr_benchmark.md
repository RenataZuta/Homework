# Benchmark de OCR — Decreto Supremo N.° 009-2025-EF, Reglamento de la Ley N.° 32069

Páginas de texto promediadas: [10, 60, 100] · control (formulario, fuera de las medias): [150] · vocabulario de referencia: 3674 palabras · imagen nativa del escaneo: 96 DPI (652×1039 px).

| Motor | DPI | s/pág | Confianza motor | % alfabéticos | Caracteres leídos | % palabras conocidas | Palabras conocidas (n) |
|---|---:|---:|---:|---:|---:|---:|---:|
| tesseract | 96 | 2.7 | 78.3 | 96.3 | 7074 | 80.1 | 564 |
| tesseract | 150 | 3.1 | 90.5 | 95.7 | 5797 | 90.9 | 513 |
| tesseract | 200 | 4.5 | 89.0 | 96.1 | 7215 | 87.6 | 620 |
| tesseract | 300 | 5.2 | 86.5 | 96.3 | 7203 | 85.0 | 601 |
| easyocr | 200 | 30.2 | 49.2 | 95.8 | 6908 | 40.3 | 276 |

**Control — página 150 (formulario de tablas)**: caracteres leídos por variante: tesseract 96 dpi = 92, tesseract 150 dpi = 0, tesseract 200 dpi = 454, tesseract 300 dpi = 429, easyocr 200 dpi = 993.

Carga inicial del motor (una vez): tesseract 0.1 s, easyocr 6.3 s

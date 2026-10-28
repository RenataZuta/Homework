"""Escalera de degradación de audio (ventas): versiones de cada llamada con calidad cada vez peor.

Sirve para medir a qué severidad se rompe el ASR. Para cada audio de --input_dir genera una versión por nivel:

  original         copia a 16 kHz mono (línea base, mismo formato que los demás niveles)
  ruido_snr20/10/5/0   ruido blanco gaussiano con relación señal-ruido de 20, 10, 5 y 0 dB
  telefono         banda telefónica: filtro 300-3400 Hz y muestreo a 8 kHz
  mp3_32k/16k/8k   compresión MP3 con bitrate bajo (32, 16 y 8 kbps)
  volumen_m20dB/m30dB/m40dB   volumen reducido 20, 30 y 40 dB

Salida: <output_dir>/<nivel>/<clip>.wav (WAV 16 kHz, mono, 16 bits; el nombre del clip es el del audio original, p. ej.
llamada_01) y <output_dir>/ladder_manifest.csv con el nivel, parámetros y mediciones de cada archivo (SNR realmente
logrado, RMS, pico). Los .wav no se versionan (están en el .gitignore).

Preset --preset l0-l3 (escenarios de canal; salida en L0/ L1/ L2/ L3/ y ladder_l0_l3_manifest.csv, sin tocar lo anterior):

  L0   copia del original sin cambios (16 kHz mono)
  L1   Opus 24 kbps mono (nota de voz de WhatsApp): ffmpeg por subprocess si está en el PATH; si no, PyAV (libopus)
  L2   filtro pasa-banda 300-3400 Hz + remuestreo a 8 kHz con scipy (llamada telefónica); el WAV se guarda a 8 kHz
  L3   L1 + ruido ambiente a SNR 10 dB (restaurante ruidoso), mezclado con numpy respecto a la potencia de L1. Con
       --noise-file ARCHIVO se usa una grabación real de ruido de calle o cafetería (se repite o recorta al largo de la
       llamada, desde un punto aleatorio reproducible); sin él, ruido rosa (1/f) sintético

  El manifiesto del preset añade `snr_etapa_db` (SNR de la última etapa: en L3, ruido frente a L1), `sample_rate` y
  `herramienta` (qué se usó realmente). `snr_db_measured` es siempre contra el original (L0).

Notas de diseño
  - Todo se decodifica y escribe a 16 kHz mono, que es lo que ve Whisper; MP3 se codifica y decodifica con PyAV
    (ya viene con faster-whisper), sin necesitar ffmpeg instalado.
  - El SNR se calcula sobre la potencia de todo el audio (incluye pausas). Si el ruido provoca saturación, se
    reescala la señal completa por su pico, lo que no cambia el SNR.
  - Es reproducible: el ruido sale de una semilla (--seed) combinada con el nombre del clip y del nivel.

Uso (desde la carpeta de la Tarea 4):
  python tasks/task2_sales/degradation/build_ladder.py --input_dir tasks/task2_sales/audio
"""
import argparse
import csv
import io
import shutil
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

import numpy as np
from faster_whisper.audio import decode_audio
from scipy import signal
from scipy.io import wavfile

SR = 16_000
EXT_AUDIO = {".m4a", ".wav", ".mp3", ".ogg", ".opus", ".flac"}
MANIFIESTO = "ladder_manifest.csv"


# ── Degradaciones ─────────────────────────────────────────────────────────────

def _normalizar_pico(y):
    """Si hay saturación, reescala toda la señal por su pico (no altera la relación señal-ruido)."""
    pico = float(np.max(np.abs(y))) if len(y) else 0.0
    return y / pico if pico > 1.0 else y


def original(x, rng):
    return x.copy()


def ruido(snr_db):
    def aplicar(x, rng):
        potencia_senal = float(np.mean(x**2))
        potencia_ruido = potencia_senal / (10 ** (snr_db / 10))
        ruido_blanco = rng.normal(0.0, np.sqrt(potencia_ruido), size=len(x)).astype(np.float32)
        return _normalizar_pico(x + ruido_blanco)

    return aplicar


def telefono(x, rng):
    """Banda telefónica: pasa-banda 300-3400 Hz, muestreo a 8 kHz y vuelta a 16 kHz."""
    sos = signal.butter(4, [300, 3400], btype="bandpass", fs=SR, output="sos")
    y = signal.sosfiltfilt(sos, x)
    y = signal.resample_poly(y, up=1, down=2)  # 16 kHz -> 8 kHz
    y = signal.resample_poly(y, up=2, down=1)  # 8 kHz -> 16 kHz (el contenido sigue limitado a 4 kHz)
    return _ajustar_largo(np.clip(y, -1.0, 1.0).astype(np.float32), len(x))


def mp3(kbps):
    def aplicar(x, rng):
        import av

        buf = io.BytesIO()
        with av.open(buf, mode="w", format="mp3") as salida:
            stream = salida.add_stream("libmp3lame", rate=SR)
            stream.bit_rate = kbps * 1000
            stream.layout = "mono"
            pcm = (np.clip(x, -1.0, 1.0) * 32767).astype(np.int16)
            frame = av.AudioFrame.from_ndarray(pcm.reshape(1, -1), format="s16", layout="mono")
            frame.sample_rate = SR
            for paquete in stream.encode(frame):
                salida.mux(paquete)
            for paquete in stream.encode(None):
                salida.mux(paquete)
        return _ajustar_largo(decode_audio(io.BytesIO(buf.getvalue()), sampling_rate=SR), len(x))

    return aplicar


def volumen(db_menos):
    ganancia = 10 ** (-db_menos / 20)

    def aplicar(x, rng):
        return (x * ganancia).astype(np.float32)

    return aplicar


def _ajustar_largo(y, n):
    """Recorta o rellena con ceros para que la duración coincida con la del original."""
    return y[:n] if len(y) >= n else np.pad(y, (0, n - len(y)))


def _opus_ffmpeg(x, kbps):
    """Codifica a Opus con ffmpeg (subprocess) y decodifica de vuelta a 16 kHz."""
    with tempfile.TemporaryDirectory() as tmp:
        entrada, salida = Path(tmp) / "in.wav", Path(tmp) / "out.ogg"
        wavfile.write(entrada, SR, (np.clip(x, -1.0, 1.0) * 32767).astype(np.int16))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(entrada), "-ac", "1", "-c:a", "libopus",
                        "-b:a", f"{kbps}k", "-application", "voip", str(salida)], check=True)
        return decode_audio(str(salida), sampling_rate=SR)


def _opus_pyav(x, kbps):
    """Mismo códec (libopus) sin ffmpeg instalado, con PyAV."""
    import av

    buf = io.BytesIO()
    with av.open(buf, mode="w", format="ogg") as salida:
        stream = salida.add_stream("libopus", rate=SR)
        stream.bit_rate = kbps * 1000
        stream.layout = "mono"
        pcm = (np.clip(x, -1.0, 1.0) * 32767).astype(np.int16)
        frame = av.AudioFrame.from_ndarray(pcm.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = SR
        for paquete in stream.encode(frame):
            salida.mux(paquete)
        for paquete in stream.encode(None):
            salida.mux(paquete)
    return decode_audio(io.BytesIO(buf.getvalue()), sampling_rate=SR)


def herramienta_opus():
    return "ffmpeg" if shutil.which("ffmpeg") else "pyav-libopus"


def opus(kbps):
    def aplicar(x, rng):
        y = _opus_ffmpeg(x, kbps) if shutil.which("ffmpeg") else _opus_pyav(x, kbps)
        return _ajustar_largo(y, len(x))

    return aplicar


def banda_telefonica_8k(x, rng):
    """Pasa-banda 300-3400 Hz y remuestreo 16 kHz -> 8 kHz (la señal devuelta está a 8 kHz)."""
    sos = signal.butter(4, [300, 3400], btype="bandpass", fs=SR, output="sos")
    y = signal.resample_poly(signal.sosfiltfilt(sos, x), up=1, down=2)
    return np.clip(y, -1.0, 1.0).astype(np.float32)


def _ruido_rosa(n, rng):
    """Ruido rosa (potencia ∝ 1/f), más parecido al ruido ambiente que el blanco."""
    espectro = np.fft.rfft(rng.normal(size=n))
    f = np.arange(len(espectro), dtype=float)
    f[0] = 1.0
    return np.fft.irfft(espectro / np.sqrt(f), n=n).astype(np.float32)


def _ruido_de_archivo(ruta, n, rng):
    """Ruido real de un archivo, a 16 kHz mono, repetido o recortado a `n` muestras desde un punto aleatorio."""
    ruido = decode_audio(str(ruta), sampling_rate=SR)
    if len(ruido) < SR:  # menos de 1 s no sirve como ambiente
        raise SystemExit(f"El archivo de ruido es demasiado corto ({len(ruido) / SR:.2f} s): {ruta}")
    if float(np.mean(ruido**2)) == 0.0:
        raise SystemExit(f"El archivo de ruido es silencio: {ruta}")
    ruido = np.tile(ruido, int(np.ceil(n / len(ruido))) + 1)  # repetir si es más corto que la llamada
    inicio = int(rng.integers(0, len(ruido) - n + 1))
    return ruido[inicio:inicio + n].astype(np.float32)


def ruido_ambiente(snr_db, archivo=None):
    def aplicar(x, rng):
        r = _ruido_de_archivo(archivo, len(x), rng) if archivo else _ruido_rosa(len(x), rng)
        r *= np.sqrt(float(np.mean(x**2)) / (10 ** (snr_db / 10)) / float(np.mean(r**2)))
        return _normalizar_pico(x + r)

    return aplicar


def opus_mas_ruido(kbps, snr_db, archivo=None):
    def aplicar(x, rng):
        return ruido_ambiente(snr_db, archivo)(opus(kbps)(x, rng), rng)

    return aplicar


# nombre -> (familia, severidad dentro de la familia, parámetro, función)
NIVELES = {
    "original": ("original", 0, "", original),
    "ruido_snr20": ("ruido", 1, "SNR 20 dB", ruido(20)),
    "ruido_snr10": ("ruido", 2, "SNR 10 dB", ruido(10)),
    "ruido_snr5": ("ruido", 3, "SNR 5 dB", ruido(5)),
    "ruido_snr0": ("ruido", 4, "SNR 0 dB", ruido(0)),
    "telefono": ("telefono", 1, "300-3400 Hz, 8 kHz", telefono),
    "mp3_32k": ("compresion", 1, "MP3 32 kbps", mp3(32)),
    "mp3_16k": ("compresion", 2, "MP3 16 kbps", mp3(16)),
    "mp3_8k": ("compresion", 3, "MP3 8 kbps", mp3(8)),
    "volumen_m20dB": ("volumen", 1, "-20 dB", volumen(20)),
    "volumen_m30dB": ("volumen", 2, "-30 dB", volumen(30)),
    "volumen_m40dB": ("volumen", 3, "-40 dB", volumen(40)),
}


# Preset l0-l3: nombre -> (familia, severidad, parámetro, función, frecuencia de muestreo del WAV, herramienta usada)
NIVELES_L0_L3 = {
    "L0": ("original", 0, "copia sin cambios", original, SR, "decode (16 kHz mono)"),
    "L1": ("whatsapp", 1, "Opus 24 kbps mono", opus(24), SR, herramienta_opus),
    "L2": ("telefono", 2, "300-3400 Hz, 8 kHz", banda_telefonica_8k, 8_000, "scipy"),
    "L3": ("whatsapp_ruido", 3, "Opus 24 kbps + ruido ambiente SNR 10 dB", opus_mas_ruido(24, 10), SR,
           lambda: herramienta_opus() + "+numpy"),
}
MANIFIESTO_L0_L3 = "ladder_l0_l3_manifest.csv"


# ── Mediciones y escritura ────────────────────────────────────────────────────

def _dbfs(x):
    rms = float(np.sqrt(np.mean(x**2))) if len(x) else 0.0
    return 20 * np.log10(rms) if rms > 0 else float("-inf")


def _snr_db(limpio, degradado):
    """SNR real entre el original y la versión degradada (con ganancia ajustada por mínimos cuadrados)."""
    g = float(np.dot(degradado, limpio) / max(np.dot(limpio, limpio), 1e-12))
    residuo = degradado - g * limpio
    pr = float(np.mean(residuo**2))
    return 10 * np.log10(float(np.mean((g * limpio) ** 2)) / pr) if pr > 0 else float("inf")


def _escribir_wav(path, y, sr=SR):
    path.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(path, sr, (np.clip(y, -1.0, 1.0) * 32767).round().astype(np.int16))


def construir_escalera(input_dir, output_dir, niveles=None, seed=0, progreso=print):
    """Genera la escalera y devuelve la lista de filas del manifiesto."""
    input_dir, output_dir = Path(input_dir), Path(output_dir)
    audios = sorted(p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in EXT_AUDIO)
    if not audios:
        raise SystemExit(f"No hay audios ({', '.join(sorted(EXT_AUDIO))}) en {input_dir}")
    elegidos = niveles or list(NIVELES)
    desconocidos = [n for n in elegidos if n not in NIVELES]
    if desconocidos:
        raise SystemExit(f"Niveles desconocidos: {desconocidos}. Opciones: {list(NIVELES)}")

    filas = []
    for audio in audios:
        x = decode_audio(str(audio), sampling_rate=SR)
        progreso(f"{audio.name}: {len(x) / SR:.1f} s")
        for nivel in elegidos:
            familia, severidad, parametro, funcion = NIVELES[nivel]
            rng = np.random.default_rng([seed, zlib.crc32(f"{audio.stem}|{nivel}".encode())])
            y = funcion(x, rng)
            destino = output_dir / nivel / f"{audio.stem}.wav"
            _escribir_wav(destino, y)
            filas.append({"level": nivel, "family": familia, "severity": severidad, "param": parametro,
                          "clip": audio.stem, "input_file": audio.name,
                          "output_file": destino.relative_to(output_dir).as_posix(),  # relativa a output_dir
                          "duration_s": round(len(y) / SR, 2), "rms_dbfs": round(_dbfs(y), 2),
                          "peak": round(float(np.max(np.abs(y))), 4),
                          # En volumen la señal solo cambia de ganancia: no hay "ruido" que medir (saldría ~110 dB de
                          # redondeo numérico), así que se deja vacío.
                          "snr_db_measured": round(_snr_db(x, y), 2) if familia in ("ruido", "telefono", "compresion") else ""})
    manifiesto = output_dir / MANIFIESTO
    with manifiesto.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(filas)
    progreso(f"{len(filas)} archivos ({len(audios)} audios × {len(elegidos)} niveles) en {output_dir}")
    progreso(f"Manifiesto: {manifiesto}")
    return filas


def construir_l0_l3(input_dir, output_dir, niveles=None, seed=0, progreso=print, ruido_archivo=None):
    """Preset l0-l3: genera L0/ L1/ L2/ L3/ y ladder_l0_l3_manifest.csv; devuelve las filas del manifiesto.

    `ruido_archivo`: grabación de ruido ambiente real para L3 (por defecto, ruido rosa sintético)."""
    input_dir, output_dir = Path(input_dir), Path(output_dir)
    audios = sorted(p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() in EXT_AUDIO)
    if not audios:
        raise SystemExit(f"No hay audios ({', '.join(sorted(EXT_AUDIO))}) en {input_dir}")
    elegidos = niveles or list(NIVELES_L0_L3)
    desconocidos = [n for n in elegidos if n not in NIVELES_L0_L3]
    if desconocidos:
        raise SystemExit(f"Niveles desconocidos: {desconocidos}. Opciones: {list(NIVELES_L0_L3)}")
    progreso(f"L1/L3: Opus con {herramienta_opus()}" + ("" if shutil.which("ffmpeg") else " (ffmpeg no está en el PATH)"))
    tabla = dict(NIVELES_L0_L3)
    if ruido_archivo:
        ruido_archivo = Path(ruido_archivo)
        if not ruido_archivo.is_file():
            raise SystemExit(f"--noise-file no es un archivo: {ruido_archivo}")
        fam, sev, par, _, sr3, _ = tabla["L3"]
        tabla["L3"] = (fam, sev, par, opus_mas_ruido(24, 10, ruido_archivo), sr3,
                       lambda: herramienta_opus() + f"+numpy (ruido: {ruido_archivo.name})")
        progreso(f"L3: ruido ambiente de {ruido_archivo.name}")

    filas = []
    for audio in audios:
        x = decode_audio(str(audio), sampling_rate=SR)
        progreso(f"{audio.name}: {len(x) / SR:.1f} s")
        l1 = None
        for nivel in elegidos:
            familia, severidad, parametro, funcion, sr, herramienta = tabla[nivel]
            rng = np.random.default_rng([seed, zlib.crc32(f"{audio.stem}|{nivel}".encode())])
            y = funcion(x, rng)
            destino = output_dir / nivel / f"{audio.stem}.wav"
            _escribir_wav(destino, y, sr)
            y16 = signal.resample_poly(y, up=SR // sr, down=1) if sr != SR else y  # para comparar con el original
            y16 = _ajustar_largo(y16.astype(np.float32), len(x))
            if nivel == "L1":
                l1 = y
            if nivel == "L3":
                l1 = l1 if l1 is not None else tabla["L1"][3](x, rng)
            filas.append({"level": nivel, "family": familia, "severity": severidad, "param": parametro,
                          "clip": audio.stem, "input_file": audio.name,
                          "output_file": destino.relative_to(output_dir).as_posix(),
                          "duration_s": round(len(y) / sr, 2), "rms_dbfs": round(_dbfs(y), 2),
                          "peak": round(float(np.max(np.abs(y))), 4),
                          "snr_db_measured": round(_snr_db(x, y16), 2) if nivel != "L0" else "",
                          "snr_etapa_db": round(_snr_db(l1, y), 2) if nivel == "L3" else "",
                          "sample_rate": sr, "herramienta": herramienta() if callable(herramienta) else herramienta})
    manifiesto = output_dir / MANIFIESTO_L0_L3
    with manifiesto.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(filas)
    progreso(f"{len(filas)} archivos ({len(audios)} audios × {len(elegidos)} niveles) en {output_dir}")
    progreso(f"Manifiesto: {manifiesto}")
    return filas


def main():
    p = argparse.ArgumentParser(description="Escalera de degradación de audio para las llamadas de ventas")
    p.add_argument("--input_dir", required=True, type=Path, help="carpeta con los audios de las llamadas")
    p.add_argument("--output_dir", type=Path, default=Path(__file__).resolve().parent,
                   help="carpeta de salida (por defecto, la de este script)")
    p.add_argument("--preset", choices=["l0-l3"], help="escenarios de canal L0-L3 (ver el docstring); sin esto, la escalera original")
    p.add_argument("--noise-file", type=Path, help="con --preset l0-l3: grabación de ruido de calle o cafetería para L3 "
                   "(por defecto, ruido rosa sintético)")
    p.add_argument("--levels", nargs="+", metavar="NIVEL",
                   help=f"subconjunto de niveles; opciones: {', '.join(NIVELES)} (con --preset l0-l3: {', '.join(NIVELES_L0_L3)})")
    p.add_argument("--seed", type=int, default=0, help="semilla del ruido (por defecto 0)")
    a = p.parse_args()
    if not a.input_dir.is_dir():
        sys.exit(f"--input_dir no es una carpeta: {a.input_dir}")
    if a.preset == "l0-l3":
        construir_l0_l3(a.input_dir, a.output_dir, a.levels, a.seed, ruido_archivo=a.noise_file)
    else:
        if a.noise_file:
            sys.exit("--noise-file solo se usa con --preset l0-l3")
        construir_escalera(a.input_dir, a.output_dir, a.levels, a.seed)


if __name__ == "__main__":
    main()

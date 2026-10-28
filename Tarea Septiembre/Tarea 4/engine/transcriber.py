"""Transcripción de audio a texto con faster-whisper.

- Modelos y precisiones salen de config.yaml (`asr.models`, `asr.precisions`); dispositivo "cuda", "cpu" o "auto".
- El dispositivo se lee en tiempo de ejecución del modelo ya cargado (no se asume el pedido).
- VRAM: `vram_peak_mb` usa torch.cuda.max_memory_allocated(). OJO: faster-whisper corre sobre CTranslate2, que reserva
  su propia memoria fuera del allocator de PyTorch, así que ese valor suele salir ~0. Por eso también se mide
  `vram_device_peak_mb`: el pico de memoria usada en TODA la GPU durante la transcripción (incluye los pesos).
- Glosario de dominio: se inyecta con `initial_prompt` (por defecto) o `hotwords`; ambos parámetros existen en
  faster-whisper 1.2.1 (config: `asr.glossary_mechanism`).
"""
import gc
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class TranscriptionResult:
    text: str
    device_used: str
    vram_peak_mb: float | None
    vram_device_peak_mb: float | None
    elapsed_seconds: float
    model: str
    compute_type: str
    language: str
    glossary: bool
    glossary_mechanism: str | None

    def to_dict(self):
        return asdict(self)


# ── Dispositivo y precisión ───────────────────────────────────────────────────

def cuda_available():
    import ctranslate2

    return ctranslate2.get_cuda_device_count() > 0


def resolve_device(device="auto"):
    if device in (None, "auto"):
        return "cuda" if cuda_available() else "cpu"
    return device


def supported_compute_types(device):
    import ctranslate2

    return set(ctranslate2.get_supported_compute_types(device))


def resolve_compute_type(device, compute_type="auto"):
    if compute_type in (None, "auto"):
        return "float16" if device == "cuda" else "int8"
    return compute_type


def is_supported(device, compute_type):
    """¿El par dispositivo/precisión funciona? (p. ej. float16 no existe en CPU)."""
    if device == "cuda" and not cuda_available():
        return False
    return compute_type in supported_compute_types(device)


# ── Glosario ──────────────────────────────────────────────────────────────────

def build_glossary(config, schema):
    """{"intro": str, "terms": [str]} para el tipo de audio; None si el config no define términos."""
    clave = {"interview": "tecnologias", "sales": "ventas"}.get(schema)
    terms = list(config.get("domain_glossary", {}).get(clave, [])) if clave else []
    if not terms:
        return None
    return {"intro": config["asr"].get("glossary_intro", {}).get(schema, "Términos:"), "terms": terms}


def _glossary_kwargs(glossary, mechanism):
    if not glossary:
        return {}
    if mechanism == "hotwords":
        return {"hotwords": ", ".join(glossary["terms"])}
    return {"initial_prompt": f"{glossary['intro']} {', '.join(glossary['terms'])}."}


# ── Medición de VRAM ──────────────────────────────────────────────────────────

def _torch_cuda():
    """El módulo torch si está instalado y ve una GPU; si no, None (la medición de VRAM es opcional)."""
    try:
        import torch
    except ImportError:
        return None
    return torch if torch.cuda.is_available() else None


def _gpu_used_mb():
    """Memoria usada en toda la GPU (MB), con torch o, si no está, con nvidia-smi. None si no se puede medir."""
    torch = _torch_cuda()
    if torch is not None:
        libre, total = torch.cuda.mem_get_info()
        return (total - libre) / 1024**2
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5, check=True).stdout
        return float(out.splitlines()[0])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


class _MuestreadorVram:
    """Muestrea en un hilo la memoria usada de toda la GPU y guarda el máximo (MB)."""

    def __init__(self, intervalo=0.05):
        self.intervalo, self.pico_mb = intervalo, None
        self._parar = threading.Event()
        self._hilo = threading.Thread(target=self._correr, daemon=True)

    def _muestrear(self):
        usado = _gpu_used_mb()
        if usado is not None:
            self.pico_mb = usado if self.pico_mb is None else max(self.pico_mb, usado)

    def _correr(self):
        while not self._parar.is_set():
            self._muestrear()
            time.sleep(self.intervalo)

    def __enter__(self):
        self._hilo.start()
        return self

    def __exit__(self, *exc):
        self._parar.set()
        self._hilo.join()
        self._muestrear()  # última muestra, por si el pico ocurrió entre dos ciclos


# ── Transcriptor ──────────────────────────────────────────────────────────────

class Transcriber:
    """Un modelo faster-whisper cargado (modelo × precisión × dispositivo). Reutilízalo para varios audios."""

    def __init__(self, model_size="medium", device="auto", compute_type="auto", config=None):
        self.config = config or {}
        asr = self.config.get("asr", {})
        self.model_size = model_size
        self.device = resolve_device(device)
        self.compute_type = resolve_compute_type(self.device, compute_type)
        self.language = asr.get("language", "es")
        self.beam_size = asr.get("beam_size", 5)
        self.mechanism = asr.get("glossary_mechanism", "initial_prompt")
        self._model = None
        self._vram_base_mb = None

    def load(self):
        if self._model is None:
            if not is_supported(self.device, self.compute_type):
                raise ValueError(f"{self.compute_type} no está soportado en {self.device} "
                                 f"(soportados: {sorted(supported_compute_types(self.device)) if self.device == 'cpu' or cuda_available() else 'sin GPU'})")
            from faster_whisper import WhisperModel

            self._vram_base_mb = _gpu_used_mb() if self.device == "cuda" else None
            self._model = WhisperModel(self.model_size, device=self.device, compute_type=self.compute_type)
        return self

    @property
    def device_used(self):
        """Dispositivo real del modelo cargado, leído de CTranslate2 en tiempo de ejecución."""
        self.load()
        return str(getattr(self._model.model, "device", self.device))

    def transcribe(self, audio_path, glossary=None):
        """Transcribe un audio. `glossary` es el dict de build_glossary() o None (sin glosario)."""
        self.load()
        torch = _torch_cuda() if self.device == "cuda" else None
        if torch is not None:
            torch.cuda.reset_peak_memory_stats()
        kwargs = _glossary_kwargs(glossary, self.mechanism)
        muestreador = _MuestreadorVram() if self.device == "cuda" else None
        inicio = time.perf_counter()
        if muestreador:
            muestreador.__enter__()
        try:
            segmentos, _ = self._model.transcribe(str(audio_path), language=self.language,
                                                  beam_size=self.beam_size, **kwargs)
            texto = " ".join(s.text.strip() for s in segmentos)  # generador: la transcripción ocurre aquí
        finally:
            elapsed = time.perf_counter() - inicio
            if muestreador:
                muestreador.__exit__(None, None, None)
        vram_torch = round(torch.cuda.max_memory_allocated() / 1024**2, 1) if torch is not None else None
        vram_gpu = None
        if muestreador and muestreador.pico_mb is not None and self._vram_base_mb is not None:
            vram_gpu = round(muestreador.pico_mb - self._vram_base_mb, 1)
        return TranscriptionResult(text=texto, device_used=self.device_used, vram_peak_mb=vram_torch,
                                   vram_device_peak_mb=vram_gpu, elapsed_seconds=round(elapsed, 2),
                                   model=self.model_size, compute_type=self.compute_type, language=self.language,
                                   glossary=bool(glossary), glossary_mechanism=self.mechanism if glossary else None)

    def close(self):
        """Libera el modelo (y la memoria de GPU) para poder cargar otra combinación."""
        self._model = None
        gc.collect()
        torch = _torch_cuda()
        if torch is not None:
            torch.cuda.empty_cache()


_CACHE = {}


def get_transcriber(model_size, device="auto", compute_type="auto", config=None):
    """Transcriptor compartido por proceso: evita recargar el mismo modelo en cada audio."""
    dispositivo = resolve_device(device)
    clave = (model_size, dispositivo, resolve_compute_type(dispositivo, compute_type))
    if clave not in _CACHE:
        _CACHE[clave] = Transcriber(model_size, dispositivo, clave[2], config)
    return _CACHE[clave]


def transcribe_audio(audio_path, config, schema=None, model_size=None, device=None, compute_type=None, glossary=False):
    """Atajo para un audio. `schema` ("interview"/"sales") elige el glosario si `glossary` es True."""
    asr = config["asr"]
    t = get_transcriber(model_size or asr["default_model"], device or asr.get("default_device", "auto"),
                        compute_type or asr.get("default_precision", "auto"), config)
    return t.transcribe(Path(audio_path), build_glossary(config, schema) if glossary else None)

"""Pipeline principal: audio → transcripción → extracción → validación.

`process_audio` es el único punto de entrada. No importa ninguna librería de UI: lo usan por igual el notebook, el
benchmark y (más adelante) una app de Streamlit.
"""
import os
import time

from . import load_config
from .extractor import LLMExtractor, RuleExtractor
from .transcriber import transcribe_audio
from .validator import validate_order_arithmetic, verify_record


def _resolver_extractor(config, nombre):
    """'auto' = llm si hay ANTHROPIC_API_KEY, si no rules."""
    nombre = nombre or config.get("pipeline", {}).get("extractor", "auto")
    if nombre == "auto":
        from dotenv import load_dotenv

        load_dotenv()
        return "llm" if os.environ.get("ANTHROPIC_API_KEY") else "rules"
    return nombre


def process_audio(audio_path, schema, config_path="config.yaml", *, extractor=None, model=None, device=None,
                  compute_type=None, glossary=False, transcript=None, llm_client=None):
    """Procesa un audio de punta a punta y devuelve un dict con:

    transcript, fields, verified_fields, device_used, elapsed_seconds (solo la transcripción), vram_peak_mb
    (torch.cuda.max_memory_allocated, suele ser ~0 con CTranslate2), error.
    Extras: vram_device_peak_mb (pico en toda la GPU), model, compute_type, extractor_used, diagnostics
    (detalle de la verificación y de la aritmética de ventas) y pipeline_seconds.

    `schema`: "interview" o "sales". `extractor`: "rules" | "llm" | "both" | "auto" (por defecto el de config.yaml).
    `transcript`: si se pasa un texto se omite el ASR (útil con la caché de transcripciones). Si una etapa falla, `error`
    dice cuál y se conserva lo que se alcanzó a calcular.
    """
    inicio = time.perf_counter()
    out = {"transcript": None, "fields": None, "verified_fields": None, "device_used": None, "elapsed_seconds": None,
           "vram_peak_mb": None, "vram_device_peak_mb": None, "model": None, "compute_type": None,
           "extractor_used": None, "diagnostics": {}, "error": None}
    etapa = "configuración"
    try:
        config = load_config(config_path)
        if schema not in config["schemas"]:
            raise ValueError(f"schema desconocido: {schema!r} (opciones: {sorted(config['schemas'])})")

        etapa = "transcripción"
        if transcript is None:
            r = transcribe_audio(audio_path, config, schema=schema, model_size=model, device=device,
                                 compute_type=compute_type, glossary=glossary)
            out.update(transcript=r.text, device_used=r.device_used, elapsed_seconds=r.elapsed_seconds,
                       vram_peak_mb=r.vram_peak_mb, vram_device_peak_mb=r.vram_device_peak_mb, model=r.model,
                       compute_type=r.compute_type)
        else:
            out["transcript"] = transcript
        texto = out["transcript"]

        etapa = "extracción"
        pedido = extractor or config.get("pipeline", {}).get("extractor", "auto")
        nombre = _resolver_extractor(config, extractor)
        por_extractor = {}
        if nombre in ("rules", "both"):
            por_extractor["rules"] = RuleExtractor(config).extract(texto, schema)
        if nombre in ("llm", "both"):
            try:
                por_extractor["llm"] = LLMExtractor(config, llm_client).extract(texto, schema)
            except Exception as e:  # sin red/clave: con 'auto' se cae a reglas y se avisa; si se pidió llm/both, es un error
                if pedido != "auto":
                    raise
                out["diagnostics"]["aviso"] = f"el LLM falló ({type(e).__name__}: {e}); se usaron las reglas"
                por_extractor["rules"] = RuleExtractor(config).extract(texto, schema)
        principal = "llm" if "llm" in por_extractor else "rules"
        out["fields"], out["extractor_used"] = por_extractor[principal], principal
        if len(por_extractor) > 1:
            out["diagnostics"]["fields_by_extractor"] = por_extractor

        etapa = "validación"
        out["verified_fields"], detalle = verify_record(out["fields"], texto)
        out["diagnostics"]["verification"] = detalle
        if schema == "sales":
            out["diagnostics"]["arithmetic"] = validate_order_arithmetic(
                out["fields"], transcript=texto, menu=config.get("menu"))
    except Exception as e:
        out["error"] = f"{etapa}: {type(e).__name__}: {e}"
    out["pipeline_seconds"] = round(time.perf_counter() - inicio, 2)
    return out

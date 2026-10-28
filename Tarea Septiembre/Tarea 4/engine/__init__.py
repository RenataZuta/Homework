"""Motor ASR de la Tarea 4: transcripción, extracción y validación de registros."""
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent  # Tarea 4/


def load_config(config_path="config.yaml"):
    """Lee config.yaml. Si la ruta relativa no existe desde el directorio actual, se busca en la raíz de la Tarea 4."""
    path = Path(config_path)
    if not path.is_absolute() and not path.exists():
        path = PROJECT_ROOT / config_path
    with path.open(encoding="utf-8") as f:
        config = yaml.safe_load(f)
    config["_base_dir"] = str(path.resolve().parent)
    return config


def task_dir(config, task, key):
    """Carpeta absoluta de una tarea: task_dir(config, "task1_interview", "audio")."""
    return Path(config["_base_dir"]) / config["paths"]["root"] / config["paths"][task][key]

"""Read and write the models kept in ``configs/models``.

Each model has two files there: a specification that people edit (YAML) and the fitted
model that the lab writes (JSON). A fitted model is an artefact, versioned with the
code like any other file: a build applies it and never changes it.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from front_office.config.settings import ConfigError, read_yaml
from front_office.domain.value_model import ValueModel, ValueSpec

MODELS_DIR = "models"
VALUE_SPEC_FILE = "player_value.yaml"
VALUE_MODEL_FILE = "player_value.json"


def value_spec_path(config_dir: Path) -> Path:
    return config_dir / MODELS_DIR / VALUE_SPEC_FILE


def value_model_path(config_dir: Path) -> Path:
    return config_dir / MODELS_DIR / VALUE_MODEL_FILE


def load_value_spec(config_dir: Path) -> ValueSpec:
    """The specification the value model is to be fitted with."""
    path = value_spec_path(config_dir)
    try:
        return ValueSpec.model_validate(read_yaml(path))
    except ValidationError as error:
        raise ConfigError(f"invalid value model specification in {path}:\n{error}") from error


def load_value_model(config_dir: Path) -> ValueModel | None:
    """The fitted value model, or ``None`` if none has been written."""
    path = value_model_path(config_dir)
    if not path.is_file():
        return None
    try:
        return ValueModel.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as error:
        raise ConfigError(
            f"{path} is not a fitted value model this version of the lab can read:\n{error}\n"
            "Fit it again: fol value fit --write"
        ) from error


def save_value_model(config_dir: Path, model: ValueModel) -> Path:
    """Write the fitted value model where a build will find it."""
    path = value_model_path(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_value_model(model), encoding="utf-8", newline="\n")
    return path


def render_value_model(model: ValueModel) -> str:
    """The model as JSON: indented, with each backtest row on a line of its own."""
    document = model.model_dump(mode="json")
    rows = document.pop("backtest")
    head = json.dumps(document, indent=1, ensure_ascii=False)
    lines = ",\n".join(f"  {json.dumps(row)}" for row in rows)
    return f'{head[:-2]},\n "backtest": [\n{lines}\n ]\n}}\n'

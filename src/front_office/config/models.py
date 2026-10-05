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
from front_office.domain.fit_model import FitEvidence, FitSpec
from front_office.domain.postseason import PostseasonModel, PostseasonSpec
from front_office.domain.value_model import ValueModel, ValueSpec

MODELS_DIR = "models"
VALUE_SPEC_FILE = "player_value.yaml"
VALUE_MODEL_FILE = "player_value.json"
FIT_SPEC_FILE = "roster_fit.yaml"
FIT_EVIDENCE_FILE = "roster_fit.json"
POSTSEASON_SPEC_FILE = "postseason.yaml"
POSTSEASON_MODEL_FILE = "postseason.json"


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


# --- roster fit --------------------------------------------------------------------------


def fit_spec_path(config_dir: Path) -> Path:
    return config_dir / MODELS_DIR / FIT_SPEC_FILE


def fit_evidence_path(config_dir: Path) -> Path:
    return config_dir / MODELS_DIR / FIT_EVIDENCE_FILE


def load_fit_spec(config_dir: Path) -> FitSpec:
    """How the roster fit evidence is to be gathered."""
    path = fit_spec_path(config_dir)
    try:
        return FitSpec.model_validate(read_yaml(path))
    except ValidationError as error:
        raise ConfigError(f"invalid roster fit specification in {path}:\n{error}") from error


def load_fit_evidence(config_dir: Path) -> FitEvidence | None:
    """The roster fit evidence on file, or ``None`` if none has been written."""
    path = fit_evidence_path(config_dir)
    if not path.is_file():
        return None
    try:
        return FitEvidence.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as error:
        raise ConfigError(
            f"{path} is not roster fit evidence this version of the lab can read:\n{error}\n"
            "Gather it again: fol fit test --write"
        ) from error


def save_fit_evidence(config_dir: Path, evidence: FitEvidence) -> Path:
    """Write the evidence where the services will find it."""
    path = fit_evidence_path(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(evidence.model_dump_json(indent=1) + "\n", encoding="utf-8", newline="\n")
    return path


# --- the postseason model ------------------------------------------------------------------


def postseason_spec_path(config_dir: Path) -> Path:
    return config_dir / MODELS_DIR / POSTSEASON_SPEC_FILE


def postseason_model_path(config_dir: Path) -> Path:
    return config_dir / MODELS_DIR / POSTSEASON_MODEL_FILE


def load_postseason_spec(config_dir: Path) -> PostseasonSpec:
    """How the postseason model is to be fitted and tested."""
    path = postseason_spec_path(config_dir)
    try:
        return PostseasonSpec.model_validate(read_yaml(path))
    except ValidationError as error:
        raise ConfigError(f"invalid postseason model specification in {path}:\n{error}") from error


def load_postseason_model(config_dir: Path) -> PostseasonModel | None:
    """The fitted postseason model, or ``None`` if none has been written."""
    path = postseason_model_path(config_dir)
    if not path.is_file():
        return None
    try:
        return PostseasonModel.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as error:
        raise ConfigError(
            f"{path} is not a fitted postseason model this version of the lab can read:\n"
            f"{error}\nFit it again: fol playoffs fit --write"
        ) from error


def save_postseason_model(config_dir: Path, model: PostseasonModel) -> Path:
    """Write the fitted postseason model where the services will find it."""
    path = postseason_model_path(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=1) + "\n", encoding="utf-8", newline="\n")
    return path

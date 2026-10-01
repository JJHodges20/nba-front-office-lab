"""Load season-specific cap and roster rules from ``configs/seasons``.

One YAML file per season. The file name and the ``season`` field inside must agree, so
a copied file that was never edited cannot masquerade as another year's rules.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from front_office.config.settings import ConfigError, read_yaml
from front_office.domain.cap_rules import SeasonRules
from front_office.domain.seasons import Season


class SeasonRulesNotFound(ConfigError):
    """No rules file exists for the requested season."""


def season_rules_path(rules_dir: Path, season: Season | str) -> Path:
    return rules_dir / f"{Season.coerce(season).label}.yaml"


def configured_seasons(rules_dir: Path) -> list[Season]:
    """Seasons that have a rules file, oldest first."""
    if not rules_dir.is_dir():
        return []
    seasons = []
    for path in rules_dir.glob("*.yaml"):
        try:
            seasons.append(Season.parse(path.stem))
        except ValueError as error:
            raise ConfigError(
                f"{path} is not named for a season (expected e.g. 2025-26.yaml)"
            ) from error
    return sorted(seasons)


def load_season_rules(rules_dir: Path, season: Season | str) -> SeasonRules:
    """Load and validate one season's rules."""
    target = Season.coerce(season)
    path = season_rules_path(rules_dir, target)
    if not path.is_file():
        available = ", ".join(s.label for s in configured_seasons(rules_dir)) or "none"
        raise SeasonRulesNotFound(
            f"no cap rules configured for {target.label} (looked for {path}); "
            f"configured seasons: {available}"
        )
    try:
        rules = SeasonRules.model_validate(read_yaml(path))
    except ValidationError as error:
        raise ConfigError(f"invalid season rules in {path}:\n{error}") from error
    if rules.season != target.label:
        raise ConfigError(
            f"{path} declares season {rules.season!r} but is named for {target.label!r}"
        )
    return rules


def load_all_season_rules(rules_dir: Path) -> dict[Season, SeasonRules]:
    """Every configured season's rules, oldest first."""
    return {
        season: load_season_rules(rules_dir, season) for season in configured_seasons(rules_dir)
    }

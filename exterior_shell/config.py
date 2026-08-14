"""Configuration management for exterior-shell.

Loads defaults from ~/.exterior-shell/config.json and merges with
CLI flags and environment variables.

Precedence: CLI flags > environment variables > config file > hardcoded defaults.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

CONFIG_PATH = Path.home() / ".exterior-shell" / "config.json"

# Backward-compatible aliases
CONFIG_FILE = CONFIG_PATH
CONFIG_DIR = CONFIG_PATH.parent


# ── Field definitions ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FieldDef:
    label: str
    default: Any
    env_var: str | None = None
    is_secret: bool = False


CONFIG_FIELDS: dict[str, FieldDef] = {
    "ai_api_key": FieldDef("AI API Key", None, "EXTERIOR_SHELL_AI_KEY", is_secret=True),
    "ai_model": FieldDef("AI Model", "openai/gpt-4o-mini", "EXTERIOR_SHELL_AI_MODEL"),
    "ai_base_url": FieldDef("AI Base URL", "https://openrouter.ai/api/v1", "EXTERIOR_SHELL_AI_BASE"),
    "default_crs": FieldDef("Default CRS", "EPSG:4326", "EXTERIOR_SHELL_CRS"),
    "default_footprint": FieldDef("Default Footprint", False),
    "default_no_stripped_ifc": FieldDef("Default No Stripped IFC", False),
    "default_keep_interior": FieldDef("Default Keep Interior", False),
    "default_report": FieldDef("Default Report", True),
}


def load_config_file(path: Path | None = None) -> dict[str, Any]:
    """Load raw config from ~/.exterior-shell/config.json.

    Args:
        path: Override config file location (default: ~/.exterior-shell/config.json).

    Returns:
        Config dict (empty dict if file doesn't exist or is invalid).
    """
    config_path = path or CONFIG_FILE
    if not config_path.exists():
        return {}
    try:
        with open(config_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to read config file {config_path}: {e}")
        return {}


# Backward-compatible alias used by ai/vision.py
_load_config_file = load_config_file


# ── Init ─────────────────────────────────────────────────────────────────────

@dataclass
class InitResult:
    path: Path
    created: bool


def init_config(path: Path | None = None) -> InitResult:
    """Write a default config file.

    Args:
        path: Override config file location.

    Returns:
        InitResult with path and whether file was created.
    """
    target = path or CONFIG_FILE
    created = not target.exists()
    target.parent.mkdir(parents=True, exist_ok=True)

    defaults = {key: field_def.default for key, field_def in CONFIG_FIELDS.items()}
    with open(target, "w", encoding="utf-8") as f:
        json.dump(defaults, f, indent=2)

    logger.info(f"Config written to {target}")
    return InitResult(path=target, created=created)


def write_config_file(config: dict[str, Any], path: Path | None = None) -> Path:
    """Write config dict to the config file.

    Args:
        config: Config dict to write.
        path: Override config file location.

    Returns:
        Path to the written config file.
    """
    target = path or CONFIG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    logger.info(f"Config written to {target}")
    return target


# Backward-compatible flat defaults dict (used by CLI config init)
DEFAULTS: dict[str, Any] = {
    key: field_def.default for key, field_def in CONFIG_FIELDS.items()
}


def show_config() -> str:
    """Show current config with source annotations.

    Returns:
        Human-readable string showing each config key, value, and source.
    """
    resolved, sources = resolve_config()
    lines = []
    for field_name, field_def in CONFIG_FIELDS.items():
        value = resolved.get(field_name, field_def.default)
        if field_def.is_secret and value:
            display = f"{str(value)[:8]}..." if len(str(value)) > 8 else "***"
        elif isinstance(value, str) and len(value) > 30:
            display = value[:27] + "..."
        else:
            display = str(value) if value is not None else "(not set)"
        lines.append(f"  {field_name:<25} = {display}")
        lines.append(f"  {'':25}   [{sources.get(field_name, 'default')}]")
    return "\n".join(lines)


# ── Resolve ──────────────────────────────────────────────────────────────────

def resolve_config(
    cli_overrides: dict[str, Any] | None = None,
    path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Resolve config by merging: CLI overrides > env vars > config file > defaults.

    Args:
        cli_overrides: Dict of values explicitly set by the user via CLI flags.
        path: Override config file location.

    Returns:
        Tuple of (resolved dict, source dict mapping config key to source name).
    """
    cli_overrides = cli_overrides or {}
    file_config = load_config_file(path)
    sources: dict[str, str] = {}

    resolved: dict[str, Any] = {}
    for key, field_def in CONFIG_FIELDS.items():
        # 1. CLI override (explicit)
        if key in cli_overrides:
            resolved[key] = cli_overrides[key]
            sources[key] = "cli"
            continue

        # 2. Environment variable
        if field_def.env_var:
            env_val = os.environ.get(field_def.env_var)
            if env_val is not None:
                # Coerce booleans
                if isinstance(field_def.default, bool):
                    resolved[key] = env_val.lower() in ("1", "true", "yes")
                else:
                    resolved[key] = env_val
                sources[key] = f"env ({field_def.env_var})"
                continue

        # 3. Config file
        if key in file_config:
            resolved[key] = file_config[key]
            sources[key] = f"config ({path or CONFIG_PATH})"
            continue

        # 4. Default
        resolved[key] = field_def.default
        sources[key] = "default"

    return resolved, sources

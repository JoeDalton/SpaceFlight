"""
YAML file reading shared by the settings modules.
"""

import logging
from pathlib import Path

import yaml

LOGGER = logging.getLogger()


def load_yaml(path: Path) -> dict:
    """Parse a YAML file and return its contents as a dict ({} if empty)."""
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def load_user_yaml(path: Path) -> dict:
    """
    Parse a user-editable YAML file, if present and readable. Never raises on a
    malformed file: it logs and returns {}, so the caller falls back to its
    defaults.

    :param path: The user file
    :return: Its contents ({} if missing, empty or unreadable)
    """
    if not path.exists():
        return {}
    try:
        return load_yaml(path)
    except Exception as exc:  # noqa: BLE001 - never let bad YAML crash boot
        LOGGER.warning(f"Could not read {path}: {exc}; using defaults")
        return {}

"""
Graphics settings persistence.

Mirrors the input-settings pattern (see
:mod:`space_flight.menus.input_settings_menu_state`): a user-editable
configuration/graphics.yaml is layered over a read-only
configuration/default_graphics.yaml so that any missing or invalid key
always falls back to a sane default.

The parsed, sanitised settings are consumed by
:class:`~space_flight.global_architecture.graphics_manager.GraphicsManager`.
"""

import copy
import logging

import yaml

from space_flight import CONFIGURATION_PATH

LOGGER = logging.getLogger()

GRAPHICS_FILE = CONFIGURATION_PATH / "graphics.yaml"
DEFAULT_GRAPHICS_FILE = CONFIGURATION_PATH / "default_graphics.yaml"

_VALID_MODES = ("fullscreen", "windowed")
_VALID_MSAA = (0, 2, 4, 8)
_MIN_SCALE = 0.25
_MAX_SCALE = 1.0
_MIN_REFLECTION = 0.1
_MAX_REFLECTION = 1.0
_MIN_MIRROR = 0.5
_MAX_MIRROR = 2.0


def _deep_merge(base: dict, override: dict) -> dict:
    """
    Recursively overlay *override* onto a deep copy of *base*.

    Nested dicts are merged key-by-key; any other value in *override* replaces
    the one in *base*. Used to layer the user config over the defaults.
    """
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class GraphicsSettings:
    """
    Loads, sanitises and saves the graphics configuration.

    :ivar config: The current, sanitised settings dict (always fully populated).
    """

    def __init__(self):
        self.config = self.load()

    @staticmethod
    def load_file(path) -> dict:
        """Parse a YAML file and return its contents as a dict ({} if empty)."""
        with open(path, "r") as f:
            return yaml.safe_load(f) or {}

    def load(self) -> dict:
        """
        Read the defaults, overlay the user file (if present and readable), and
        return the sanitised result. Never raises on a malformed user file — it
        logs and falls back to the defaults.
        """
        defaults = self.load_file(DEFAULT_GRAPHICS_FILE)
        user = {}
        if GRAPHICS_FILE.exists():
            try:
                user = self.load_file(GRAPHICS_FILE)
            except Exception as exc:  # noqa: BLE001 - never let bad YAML crash boot
                LOGGER.warning(f"Could not read {GRAPHICS_FILE}: {exc}; using defaults")
        return self.sanitise(_deep_merge(defaults, user))

    def save(self, config: dict):
        """
        Sanitise *config*, write it to graphics.yaml and store it on
        :attr:`config`.
        """
        config = self.sanitise(config)
        with open(GRAPHICS_FILE, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        self.config = config

    def reset_to_default(self) -> dict:
        """Reload the default config (without writing the user file) and return it."""
        self.config = self.sanitise(self.load_file(DEFAULT_GRAPHICS_FILE))
        return self.config

    @staticmethod
    def sanitise(config: dict) -> dict:
        """
        Clamp every field to a value the renderer can act on, leaving the input
        dict untouched (works on a deep copy).

        Out-of-range or wrong-typed values are coerced to the nearest valid
        option rather than rejected, so a hand-edited file never hard-crashes
        the renderer.
        """
        config = copy.deepcopy(config)
        display = config.setdefault("display", {})
        render = config.setdefault("render", {})
        aa = config.setdefault("antialiasing", {})

        if display.get("mode") not in _VALID_MODES:
            display["mode"] = "fullscreen"

        size = display.get("windowed_size", [1280, 720])
        try:
            w, h = int(size[0]), int(size[1])
            display["windowed_size"] = [max(640, w), max(480, h)]
        except (TypeError, ValueError, IndexError):
            display["windowed_size"] = [1280, 720]

        try:
            render["scale"] = min(
                _MAX_SCALE, max(_MIN_SCALE, float(render.get("scale", 1.0)))
            )
        except (TypeError, ValueError):
            render["scale"] = 1.0

        try:
            render["reflection_scale"] = min(
                _MAX_REFLECTION,
                max(_MIN_REFLECTION, float(render.get("reflection_scale", 0.5))),
            )
        except (TypeError, ValueError):
            render["reflection_scale"] = 0.5

        try:
            render["mirror_scale"] = min(
                _MAX_MIRROR, max(_MIN_MIRROR, float(render.get("mirror_scale", 1.0)))
            )
        except (TypeError, ValueError):
            render["mirror_scale"] = 1.0

        if aa.get("msaa") not in _VALID_MSAA:
            aa["msaa"] = 0
        aa["fxaa"] = bool(aa.get("fxaa", False))

        return config

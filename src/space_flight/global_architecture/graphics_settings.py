"""
Graphics settings persistence.

A user-editable configuration/graphics.yaml is layered over a read-only
datafiles/default_configuration/default_graphics.yaml, and the result
sanitised, so that any missing or invalid key falls back to a sane default.

The ``world`` section holds WorldBuilder's quality settings (terrain, air,
sky, clouds, ocean) as :meth:`WorldSettings.to_dict` writes them; WorldBuilder
owns their knobs, names and limits.
"""

import copy

import yaml
from world_builder.settings import WorldSettings

from space_flight import CONFIGURATION_PATH, DEFAULT_CONFIGURATION_PATH
from space_flight.global_architecture.yaml_files import load_user_yaml, load_yaml

GRAPHICS_FILE = CONFIGURATION_PATH / "graphics.yaml"
DEFAULT_GRAPHICS_FILE = DEFAULT_CONFIGURATION_PATH / "default_graphics.yaml"

_VALID_MODES = ("fullscreen", "windowed")
_VALID_MSAA = (0, 2, 4, 8)
_MIN_SCALE = 0.25
_MAX_SCALE = 1.0
_MIN_MIRROR = 0.25
_MAX_MIRROR = 1.0


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


def _clamp_float(value, default: float, minimum: float, maximum: float) -> float:
    """
    :return: value as a float clamped to [minimum, maximum], or default if it
        is not a number
    """
    try:
        return min(maximum, max(minimum, float(value)))
    except (TypeError, ValueError):
        return default


def _migrate_legacy(user: dict) -> dict:
    """
    Carry the settings older files kept outside ``world`` into it:
    ``clouds.quality`` becomes the clouds' preset and
    ``render.reflection_scale`` the ocean's knob. Only for a file without a
    ``world`` section; :meth:`GraphicsSettings.sanitise` drops the old keys.

    :param user: the user file's content, left untouched
    :return: the content, with a ``world`` section if one was derived
    """
    if not isinstance(user, dict) or "world" in user:
        return user
    clouds = user.get("clouds")
    render = user.get("render")
    quality = clouds.get("quality") if isinstance(clouds, dict) else None
    reflection = render.get("reflection_scale") if isinstance(render, dict) else None
    if quality is None and reflection is None:
        return user
    world = WorldSettings.preset("high")
    if quality is not None:
        world = world.with_section_level("clouds", quality)
    if reflection is not None:
        world = world.with_value("ocean", "reflection_scale", reflection)
    return {**user, "world": world.to_dict()}


class GraphicsSettings:
    """
    Loads, sanitises and saves the graphics configuration.

    :ivar config: The current, sanitised settings dict (always fully populated).
    """

    def __init__(self):
        self.config = self.load()

    def load(self) -> dict:
        """
        Read the defaults, overlay the user file (if present and readable), and
        return the sanitised result. Never raises on a malformed user file — it
        logs and falls back to the defaults.
        """
        defaults = load_yaml(DEFAULT_GRAPHICS_FILE)
        user = _migrate_legacy(load_user_yaml(GRAPHICS_FILE))
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

    def world_settings(self) -> WorldSettings:
        """:return: WorldBuilder's quality settings, to build its objects with"""
        return WorldSettings.from_dict(self.config["world"])

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
        compatibility = config.setdefault("compatibility", {})
        hud = config.setdefault("hud", {})

        if display.get("mode") not in _VALID_MODES:
            display["mode"] = "fullscreen"

        size = display.get("windowed_size", [1280, 720])
        try:
            w, h = int(size[0]), int(size[1])
            display["windowed_size"] = [max(640, w), max(480, h)]
        except (TypeError, ValueError, IndexError):
            display["windowed_size"] = [1280, 720]

        render["scale"] = _clamp_float(
            render.get("scale", 1.0), 1.0, _MIN_SCALE, _MAX_SCALE
        )
        # Moved into world (see _migrate_legacy)
        render.pop("reflection_scale", None)
        config.pop("clouds", None)
        render["mirror_scale"] = _clamp_float(
            render.get("mirror_scale", 1.0), 1.0, _MIN_MIRROR, _MAX_MIRROR
        )

        if aa.get("msaa") not in _VALID_MSAA:
            aa["msaa"] = 0
        aa["fxaa"] = bool(aa.get("fxaa", False))

        compatibility["alternate_model_orientation"] = bool(
            compatibility.get("alternate_model_orientation", False)
        )

        hud["fps_counter"] = bool(hud.get("fps_counter", True))

        # Lenient: whatever it cannot use falls back to the preset, logged
        config["world"] = WorldSettings.from_dict(config.get("world")).to_dict()

        return config

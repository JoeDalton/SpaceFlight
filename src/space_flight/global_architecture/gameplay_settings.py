"""
Gameplay (difficulty) settings persistence.

configuration/gameplay_presets.yaml holds the difficulty presets (read-only).
The user-editable configuration/gameplay.yaml names the selected preset, or is
"custom" and holds its own values. Values come from the preset file whenever a
preset is selected, so re-tuning a preset reaches every player who picked it.

The "normal" preset reproduces the game's original, untuned behaviour, and is
the only source of defaults: the fallback for a missing or unknown preset, and
for missing or invalid custom values. The user file is sanitised, so a
hand-edited one never crashes the game; the read-only presets file must be
complete and valid.

Game code reads these settings once, when a level is built (see
:func:`gameplay_config`): changes made from the menus apply from the next
mission.
"""

import copy
import functools
import logging
from pathlib import Path

import yaml

from space_flight import CONFIGURATION_PATH

LOGGER = logging.getLogger()

GAMEPLAY_FILE = CONFIGURATION_PATH / "gameplay.yaml"
PRESETS_FILE = CONFIGURATION_PATH / "gameplay_presets.yaml"

# Preset used as a fallback, and the name of user-defined values
DEFAULT_PRESET = "normal"
CUSTOM_PRESET = "custom"

# Sides with their own settings: the player's ship, and every bot (fighters,
# turrets, capital ships)
SIDES = ("player", "bots")

# The values of a side, by path within its settings: (minimum, maximum) of each
# numeric value, and the boolean ones
LIMITS = {
    ("auto_aim", "lock_delay_s"): (0.0, 5.0),
    ("auto_aim", "lock_angle_deg"): (1.0, 45.0),
    # Strictly positive: the assist clamp divides by its tangent
    ("auto_aim", "assist_angle_deg"): (0.5, 20.0),
    ("deviation_deg",): (0.0, 2.0),
    ("damage_multiplier",): (0.1, 3.0),
    ("collision_damage_multiplier",): (0.0, 2.0),
}
FLAGS = (("auto_aim", "enabled"), ("lead_indicator",))
# Values only the player has
PLAYER_ONLY = (("collision_damage_multiplier",), ("lead_indicator",))

# Marks a value missing from its settings
_MISSING = object()


def side_paths(side: str) -> list[tuple]:
    """
    :param side: "player" or "bots"
    :return: The paths of the side's values, within its settings
    """
    return [
        path
        for path in (*FLAGS, *LIMITS)
        if side == "player" or path not in PLAYER_ONLY
    ]


def _get_path(section, path: tuple):
    """:return: The value at *path* in nested dict *section*, or _MISSING."""
    for key in path:
        if not isinstance(section, dict) or key not in section:
            return _MISSING
        section = section[key]
    return section


def _set_path(section: dict, path: tuple, value):
    """Set the value at *path* in nested dict *section*, replacing non-dicts."""
    for key in path[:-1]:
        if not isinstance(section.get(key), dict):
            section[key] = {}
        section = section[key]
    section[path[-1]] = value


def _clean(path: tuple, value, fallback):
    """
    :param path: The value's path within its side's settings
    :param value: The value, possibly _MISSING or wrong-typed
    :param fallback: What to return if value is missing or not a number
    :return: The value coerced to a bool, or to a number within its limits
    """
    if value is _MISSING:
        return fallback
    if path in FLAGS:
        return bool(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    minimum, maximum = LIMITS[path]
    return min(maximum, max(minimum, number))


def _load_file(path: Path) -> dict:
    """Parse a YAML file and return its contents as a dict ({} if empty)."""
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def load_presets() -> dict[str, dict]:
    """
    :return: The values of each preset of gameplay_presets.yaml, by name, in
        file order
    :raises ValueError: If the file lacks the default preset, uses the custom
        preset's name, or has a preset missing a value or with an invalid one
        (it is read-only: there is nothing to fall back on)
    """
    presets = {str(name): values for name, values in _load_file(PRESETS_FILE).items()}
    if DEFAULT_PRESET not in presets:
        raise ValueError(f"{PRESETS_FILE} has no '{DEFAULT_PRESET}' preset")
    if CUSTOM_PRESET in presets:
        raise ValueError(f"'{CUSTOM_PRESET}' is not a valid name in {PRESETS_FILE}")
    for name, values in presets.items():
        for side in SIDES:
            for path in side_paths(side):
                value = _get_path(_get_path(values, (side,)), path)
                if value is _MISSING or _clean(path, value, _MISSING) != value:
                    raise ValueError(
                        f"{PRESETS_FILE}: preset '{name}' has no valid "
                        f"{'.'.join((side, *path))} ({value!r})"
                    )
    return presets


class GameplaySettings:
    """
    Loads, sanitises and saves the gameplay configuration.

    :ivar presets: The sanitised values of each preset, by name, in menu order
    :ivar config: The current settings: the selected preset's name under
        "preset", and the sanitised, fully populated values it stands for
    """

    def __init__(self):
        self.presets = load_presets()
        self.config = self.load()

    def load(self) -> dict:
        """
        Read the user file (if present and readable) and return the settings it
        selects. Never raises on a malformed user file — it logs and falls back
        to the default preset.
        """
        user = {}
        if GAMEPLAY_FILE.exists():
            try:
                user = _load_file(GAMEPLAY_FILE)
            except Exception as exc:  # noqa: BLE001 - never let bad YAML crash boot
                LOGGER.warning(f"Could not read {GAMEPLAY_FILE}: {exc}; using defaults")
        return self.resolve(user)

    def resolve(self, config: dict) -> dict:
        """
        :param config: The selected preset's name under "preset" and, for the
            custom preset, its values (possibly partial or invalid)
        :return: The preset's name, and the fully populated values it stands
            for: the preset's own values, or the custom values, sanitised over
            the default preset's. An unknown preset falls back to the default
            one.
        """
        if not isinstance(config, dict):
            config = {}
        preset = config.get("preset", DEFAULT_PRESET)
        if preset == CUSTOM_PRESET:
            values = self.sanitise(config, fallback=self.presets[DEFAULT_PRESET])
        elif preset in self.presets:
            values = self.presets[preset]
        else:
            LOGGER.warning(f"Unknown gameplay preset {preset!r}; using defaults")
            preset = DEFAULT_PRESET
            values = self.presets[preset]
        return _with_preset(preset, values)

    def save(self, config: dict):
        """
        Resolve *config* (see :meth:`resolve`), write it to gameplay.yaml (only
        the preset's name, unless custom) and store it on :attr:`config`.
        """
        config = self.resolve(config)
        if config["preset"] == CUSTOM_PRESET:
            on_disk = config
        else:
            on_disk = {"preset": config["preset"]}
        with open(GAMEPLAY_FILE, "w") as f:
            yaml.dump(on_disk, f, default_flow_style=False, sort_keys=False)
        self.config = config

    @staticmethod
    def sanitise(config: dict, fallback: dict) -> dict:
        """
        Clamp every value to one the game can act on, leaving the input dict
        untouched (works on a deep copy). Keys other than the values (e.g.
        "preset") are passed through.

        Out-of-range values are clamped, and missing or wrong-typed values (or
        sections) replaced by the fallback's, so a hand-edited file never
        crashes the game.

        :param config: The values to sanitise
        :param fallback: Complete and valid values (e.g. the default preset's)
        :return: The sanitised, fully populated values
        """
        config = copy.deepcopy(config)
        for side in SIDES:
            if not isinstance(config.get(side), dict):
                config[side] = {}
            for path in side_paths(side):
                value = _clean(
                    path,
                    _get_path(config[side], path),
                    _get_path(fallback[side], path),
                )
                _set_path(config[side], path, value)
        return config


def _with_preset(preset: str, values: dict) -> dict:
    """
    :return: A deep copy of *values* labelled with *preset*, which comes first
        (so it heads the saved file)
    """
    values = copy.deepcopy(values)
    values.pop("preset", None)
    return {"preset": preset, **values}


@functools.cache
def _default_config() -> dict:
    """The default preset's settings, read from disk once."""
    return _with_preset(DEFAULT_PRESET, load_presets()[DEFAULT_PRESET])


def gameplay_config(game) -> dict:
    """
    The gameplay settings to build a level with.

    :param game: The current game object; the default preset is used if its app
        has no gameplay settings (e.g. a test double or a lightweight headless
        stub)
    :return: The settings dict. Read it, do not modify it.
    """
    try:
        config = game.app.gameplay_settings.config
    except AttributeError:
        config = None
    if isinstance(config, dict):
        return config
    return _default_config()


def auto_aim_params(game, side: str) -> dict:
    """
    :param game: The current game object (see :func:`gameplay_config`)
    :param side: "player" or "bots"
    :return: The side's auto-aim settings, as keyword arguments of
        :meth:`~space_flight.ai.auto_aim.AutoAim.configure`
    """
    auto_aim = gameplay_config(game)[side]["auto_aim"]
    return {
        "enabled": auto_aim["enabled"],
        "target_lock_delay_s": auto_aim["lock_delay_s"],
        "acquisition_cone_angle_deg": auto_aim["lock_angle_deg"],
        "max_assist_angle_deg": auto_aim["assist_angle_deg"],
    }

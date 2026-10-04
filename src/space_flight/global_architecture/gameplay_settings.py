"""
Gameplay (difficulty) settings persistence.

configuration/gameplay_presets.yaml holds the difficulty presets (read-only).
The user-editable configuration/gameplay.yaml names the selected preset, or is
"custom" and holds its own values. Values come from the preset file whenever a
preset is selected, so re-tuning a preset reaches every player who picked it.

The "normal" preset reproduces the game's original, untuned behaviour, and is
the fallback for a missing or unknown preset and for missing custom values.
Every value is sanitised, so a hand-edited file never crashes the game.

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
from space_flight.global_architecture.graphics_settings import _deep_merge

LOGGER = logging.getLogger()

GAMEPLAY_FILE = CONFIGURATION_PATH / "gameplay.yaml"
PRESETS_FILE = CONFIGURATION_PATH / "gameplay_presets.yaml"

# Preset used as a fallback, and the name of user-defined values
DEFAULT_PRESET = "normal"
CUSTOM_PRESET = "custom"

# Sides with their own settings: the player's ship, and every bot (fighters,
# turrets, capital ships)
SIDES = ("player", "bots")

# (minimum, maximum, fallback) of each numeric field
_AUTO_AIM_LIMITS = {
    "lock_delay_s": (0.0, 5.0, 1.0),
    # Beyond 90 degrees, targets behind the ship could be locked
    "lock_angle_deg": (1.0, 90.0, 30.0),
    # Strictly positive: the assist clamp divides by its tangent
    "assist_angle_deg": (0.5, 20.0, 5.0),
}
_DEVIATION_LIMITS = (0.0, 5.0, 0.0)
_DAMAGE_MULTIPLIER_LIMITS = (0.1, 5.0, 1.0)
_COLLISION_DAMAGE_MULTIPLIER_LIMITS = (0.0, 5.0, 1.0)


def _clamp(value, limits: tuple[float, float, float]) -> float:
    """
    :param value: The value to coerce to a float within limits
    :param limits: (minimum, maximum, fallback if value is not a number)
    :return: The clamped value
    """
    minimum, maximum, fallback = limits
    try:
        return min(maximum, max(minimum, float(value)))
    except (TypeError, ValueError):
        return fallback


def _load_file(path: Path) -> dict:
    """Parse a YAML file and return its contents as a dict ({} if empty)."""
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def load_presets() -> dict[str, dict]:
    """
    :return: The sanitised values of each preset of gameplay_presets.yaml, by
        name, in file order
    :raises ValueError: If the file lacks the default preset, or uses the
        custom preset's name
    """
    presets = {
        str(name): GameplaySettings.sanitise(values)
        for name, values in _load_file(PRESETS_FILE).items()
    }
    if DEFAULT_PRESET not in presets:
        raise ValueError(f"{PRESETS_FILE} has no '{DEFAULT_PRESET}' preset")
    if CUSTOM_PRESET in presets:
        raise ValueError(f"'{CUSTOM_PRESET}' is not a valid name in {PRESETS_FILE}")
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
        :return: The preset's name, and the sanitised, fully populated values it
            stands for: the preset's own values, or the custom values over the
            default preset's. An unknown preset falls back to the default one.
        """
        if not isinstance(config, dict):
            config = {}
        preset = config.get("preset", DEFAULT_PRESET)
        if preset == CUSTOM_PRESET:
            values = _deep_merge(self.presets[DEFAULT_PRESET], config)
        elif preset in self.presets:
            values = self.presets[preset]
        else:
            LOGGER.warning(f"Unknown gameplay preset {preset!r}; using defaults")
            preset = DEFAULT_PRESET
            values = self.presets[preset]
        return _with_preset(preset, self.sanitise(values))

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
    def sanitise(config: dict) -> dict:
        """
        Clamp every value to one the game can act on, leaving the input dict
        untouched (works on a deep copy). Keys other than the values (e.g.
        "preset") are passed through.

        Out-of-range or wrong-typed values are coerced to the nearest valid
        option rather than rejected, so a hand-edited file never crashes the
        game.
        """
        config = copy.deepcopy(config)
        for side in SIDES:
            section = config.setdefault(side, {})
            if not isinstance(section, dict):
                section = config[side] = {}
            auto_aim = section.setdefault("auto_aim", {})
            if not isinstance(auto_aim, dict):
                auto_aim = section["auto_aim"] = {}

            auto_aim["enabled"] = bool(auto_aim.get("enabled", True))
            for key, limits in _AUTO_AIM_LIMITS.items():
                auto_aim[key] = _clamp(auto_aim.get(key, limits[2]), limits)

            section["deviation_deg"] = _clamp(
                section.get("deviation_deg", 0.0), _DEVIATION_LIMITS
            )
            section["damage_multiplier"] = _clamp(
                section.get("damage_multiplier", 1.0), _DAMAGE_MULTIPLIER_LIMITS
            )

        player = config["player"]
        player["collision_damage_multiplier"] = _clamp(
            player.get("collision_damage_multiplier", 1.0),
            _COLLISION_DAMAGE_MULTIPLIER_LIMITS,
        )
        player["lead_indicator"] = bool(player.get("lead_indicator", True))

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

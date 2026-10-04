"""
Unit tests for the gameplay-settings persistence layer
(:mod:`space_flight.global_architecture.gameplay_settings`).

Covers:
- :meth:`GameplaySettings.sanitise` — clamping / coercion of every value,
  with the fallback's for missing or wrong-typed ones
- :func:`load_presets` — the presets file, in order, complete and valid
- :meth:`GameplaySettings.load` — the preset (or custom values) the user file
  selects, with fallbacks to the default preset
- :meth:`GameplaySettings.save` — round-trip to disk
- :func:`gameplay_config` — the app's settings, or the defaults on a stub app
- The shipped gameplay_presets.yaml: complete, valid, and "normal" reproduces
  the untuned game
"""

import copy
import inspect
import types
from unittest.mock import MagicMock

import pytest
import yaml

from space_flight.ai.auto_aim import AutoAim
from space_flight.global_architecture import gameplay_settings as gps
from space_flight.global_architecture.gameplay_settings import (
    CUSTOM_PRESET,
    DEFAULT_PRESET,
    LIMITS,
    GameplaySettings,
    gameplay_config,
    load_presets,
)

# A fully-populated, valid config matching the YAML schema. Several tests assert
# exact equality against it, so every field sanitise() populates must appear
# here -- otherwise adding a field looks like a test failure.
_VALID = {
    "player": {
        "auto_aim": {
            "enabled": False,
            "lock_delay_s": 0.5,
            "lock_angle_deg": 20.0,
            "assist_angle_deg": 8.0,
        },
        "deviation_deg": 1.0,
        "damage_multiplier": 2.0,
        "collision_damage_multiplier": 0.5,
        "lead_indicator": False,
    },
    "bots": {
        "auto_aim": {
            "enabled": True,
            "lock_delay_s": 1.5,
            "lock_angle_deg": 45.0,
            "assist_angle_deg": 3.0,
        },
        "deviation_deg": 0.5,
        "damage_multiplier": 0.5,
    },
}

# The untuned game's values (as the shipped "normal" preset)
_NORMAL = {
    "player": {
        "auto_aim": {
            "enabled": True,
            "lock_delay_s": 1.0,
            "lock_angle_deg": 30.0,
            "assist_angle_deg": 5.0,
        },
        "deviation_deg": 0.0,
        "damage_multiplier": 1.0,
        "collision_damage_multiplier": 1.0,
        "lead_indicator": True,
    },
    "bots": {
        "auto_aim": {
            "enabled": True,
            "lock_delay_s": 1.0,
            "lock_angle_deg": 30.0,
            "assist_angle_deg": 5.0,
        },
        "deviation_deg": 0.0,
        "damage_multiplier": 1.0,
    },
}

# Test presets: "hard" is _VALID
_PRESETS = {"easy": _NORMAL, DEFAULT_PRESET: _NORMAL, "hard": _VALID}


def _get(section: dict, path: tuple):
    """Return the value at *path* in nested dict *section*."""
    for key in path:
        section = section[key]
    return section


def _set(section: dict, path: tuple, value):
    """Set the value at *path* in nested dict *section*, creating dicts."""
    for key in path[:-1]:
        section = section.setdefault(key, {})
    section[path[-1]] = value


def _write_yaml(path, data):
    """Dump *data* to *path* as YAML and return the path."""
    path.write_text(yaml.dump(data, sort_keys=False))
    return path


@pytest.fixture
def files(tmp_path, monkeypatch):
    """
    Point the module at test presets, and at a user file (not created) in
    tmp_path, which is returned.
    """
    monkeypatch.setattr(
        gps, "PRESETS_FILE", _write_yaml(tmp_path / "presets.yaml", _PRESETS)
    )
    user = tmp_path / "user.yaml"
    monkeypatch.setattr(gps, "GAMEPLAY_FILE", user)
    return user


# ---------------------------------------------------------------------------
# GameplaySettings.sanitise
# ---------------------------------------------------------------------------


class TestSanitise:
    def test_valid_config_passes_through(self):
        assert GameplaySettings.sanitise(_VALID, fallback=_NORMAL) == _VALID

    def test_input_is_not_modified(self):
        config = {"player": {"damage_multiplier": 99.0}}
        GameplaySettings.sanitise(config, fallback=_NORMAL)
        assert config == {"player": {"damage_multiplier": 99.0}}

    def test_empty_config_takes_every_value_from_the_fallback(self):
        assert GameplaySettings.sanitise({}, fallback=_VALID) == _VALID

    def test_player_only_values_are_not_added_to_the_bots(self):
        out = GameplaySettings.sanitise({}, fallback=_NORMAL)
        assert "lead_indicator" not in out["bots"]
        assert "collision_damage_multiplier" not in out["bots"]

    @pytest.mark.parametrize("path", list(LIMITS))
    def test_numbers_clamped_to_their_limits(self, path):
        """Below its minimum, a value is raised to it; above its maximum, cut."""
        minimum, maximum = LIMITS[path]
        for raw, expected in [(minimum - 1.0, minimum), (maximum + 1.0, maximum)]:
            config = {"player": {}}
            _set(config["player"], path, raw)
            out = GameplaySettings.sanitise(config, fallback=_NORMAL)
            assert _get(out["player"], path) == expected

    def test_numeric_strings_are_numbers(self):
        out = GameplaySettings.sanitise(
            {"player": {"deviation_deg": "1"}}, fallback=_NORMAL
        )
        assert out["player"]["deviation_deg"] == 1.0

    @pytest.mark.parametrize("raw", [None, "x", [1]])
    def test_wrong_typed_number_takes_the_fallbacks_value(self, raw):
        out = GameplaySettings.sanitise(
            {"bots": {"damage_multiplier": raw, "auto_aim": {"lock_delay_s": raw}}},
            fallback=_VALID,
        )
        assert out["bots"]["damage_multiplier"] == _VALID["bots"]["damage_multiplier"]
        assert (
            out["bots"]["auto_aim"]["lock_delay_s"]
            == (_VALID["bots"]["auto_aim"]["lock_delay_s"])
        )

    @pytest.mark.parametrize("raw, expected", [(1, True), (0, False), ("", False)])
    def test_flags_coerced_to_bool(self, raw, expected):
        out = GameplaySettings.sanitise(
            {"player": {"auto_aim": {"enabled": raw}, "lead_indicator": raw}},
            fallback=_NORMAL,
        )
        assert out["player"]["auto_aim"]["enabled"] is expected
        assert out["player"]["lead_indicator"] is expected

    @pytest.mark.parametrize("raw", [None, 3, "hard", [1, 2]])
    def test_malformed_sections_take_the_fallbacks_values(self, raw):
        out = GameplaySettings.sanitise(
            {"player": raw, "bots": {"auto_aim": raw}}, fallback=_VALID
        )
        assert out == _VALID

    def test_other_keys_pass_through(self):
        out = GameplaySettings.sanitise({"preset": "hard"}, fallback=_NORMAL)
        assert out["preset"] == "hard"


# ---------------------------------------------------------------------------
# load_presets
# ---------------------------------------------------------------------------


class TestLoadPresets:
    def test_presets_in_file_order(self, files):
        assert list(load_presets()) == ["easy", DEFAULT_PRESET, "hard"]

    def test_presets_are_read_as_is(self, files):
        assert load_presets() == _PRESETS

    @pytest.mark.parametrize(
        "side, path, raw",
        [
            # Missing
            ("bots", ("damage_multiplier",), None),
            ("player", ("lead_indicator",), None),
            ("bots", ("auto_aim", "lock_delay_s"), None),
            # Out of range
            ("bots", ("damage_multiplier",), 99.0),
            # Not a number
            ("player", ("deviation_deg",), "wide"),
            ("player", ("deviation_deg",), "2"),
        ],
    )
    def test_incomplete_or_invalid_preset_raises(
        self, tmp_path, monkeypatch, side, path, raw
    ):
        """The presets file is read-only: there is nothing to fall back on."""
        hard = copy.deepcopy(_VALID)
        section = hard[side]
        for key in path[:-1]:
            section = section[key]
        if raw is None:
            del section[path[-1]]
        else:
            section[path[-1]] = raw
        path_file = _write_yaml(
            tmp_path / "presets.yaml", {DEFAULT_PRESET: _NORMAL, "hard": hard}
        )
        monkeypatch.setattr(gps, "PRESETS_FILE", path_file)
        with pytest.raises(ValueError, match="hard"):
            load_presets()

    def test_missing_default_preset_raises(self, tmp_path, monkeypatch):
        path = _write_yaml(tmp_path / "presets.yaml", {"hard": _VALID})
        monkeypatch.setattr(gps, "PRESETS_FILE", path)
        with pytest.raises(ValueError):
            load_presets()

    def test_custom_preset_name_raises(self, tmp_path, monkeypatch):
        path = _write_yaml(
            tmp_path / "presets.yaml",
            {DEFAULT_PRESET: _NORMAL, CUSTOM_PRESET: _VALID},
        )
        monkeypatch.setattr(gps, "PRESETS_FILE", path)
        with pytest.raises(ValueError):
            load_presets()


# ---------------------------------------------------------------------------
# GameplaySettings.load
# ---------------------------------------------------------------------------


class TestLoad:
    def test_missing_user_file_selects_default_preset(self, files):
        assert GameplaySettings().config == {"preset": DEFAULT_PRESET, **_NORMAL}

    def test_named_preset_selects_its_values(self, files):
        _write_yaml(files, {"preset": "hard"})
        assert GameplaySettings().config == {"preset": "hard", **_VALID}

    def test_named_preset_ignores_stale_values(self, files):
        """Values come from the preset file, so re-tuning a preset applies."""
        _write_yaml(files, {"preset": "hard", "bots": {"damage_multiplier": 3}})
        assert GameplaySettings().config == {"preset": "hard", **_VALID}

    def test_custom_values_are_used(self, files):
        _write_yaml(files, {"preset": CUSTOM_PRESET, **_VALID})
        assert GameplaySettings().config == {"preset": CUSTOM_PRESET, **_VALID}

    def test_missing_custom_values_come_from_default_preset(self, files):
        _write_yaml(files, {"preset": CUSTOM_PRESET, "bots": {"damage_multiplier": 3}})
        config = GameplaySettings().config
        assert config["preset"] == CUSTOM_PRESET
        assert config["bots"]["damage_multiplier"] == 3.0
        assert config["bots"]["auto_aim"] == _NORMAL["bots"]["auto_aim"]
        assert config["player"] == _NORMAL["player"]

    def test_custom_values_are_sanitised(self, files):
        _write_yaml(files, {"preset": CUSTOM_PRESET, "bots": {"damage_multiplier": 99}})
        assert (
            GameplaySettings().config["bots"]["damage_multiplier"]
            == (LIMITS[("damage_multiplier",)][1])
        )

    @pytest.mark.parametrize("content", [{"preset": "nightmare"}, {}, [1, 2], "hard"])
    def test_invalid_user_file_selects_default_preset(self, files, content):
        _write_yaml(files, content)
        assert GameplaySettings().config == {"preset": DEFAULT_PRESET, **_NORMAL}

    def test_malformed_user_file_selects_default_preset(self, files):
        files.write_text("{ this: is: not: valid: yaml")
        # Should not raise; defaults are used.
        assert GameplaySettings().config == {"preset": DEFAULT_PRESET, **_NORMAL}

    def test_presets_are_exposed_in_order(self, files):
        assert list(GameplaySettings().presets) == ["easy", DEFAULT_PRESET, "hard"]


# ---------------------------------------------------------------------------
# GameplaySettings.save
# ---------------------------------------------------------------------------


class TestSave:
    def test_named_preset_writes_only_its_name(self, files):
        settings = GameplaySettings()
        settings.save({"preset": "hard", **_VALID})
        assert yaml.safe_load(files.read_text()) == {"preset": "hard"}
        assert settings.config == {"preset": "hard", **_VALID}

    def test_named_preset_overrides_edited_values(self, files):
        """A named preset stands for its own values, whatever comes with it."""
        settings = GameplaySettings()
        settings.save({"preset": "hard", **_NORMAL})
        assert settings.config == {"preset": "hard", **_VALID}

    def test_custom_writes_sanitised_values(self, files):
        settings = GameplaySettings()
        settings.save({"preset": CUSTOM_PRESET, "player": {"damage_multiplier": 99}})

        on_disk = yaml.safe_load(files.read_text())
        assert on_disk["preset"] == CUSTOM_PRESET
        assert (
            on_disk["player"]["damage_multiplier"]
            == (LIMITS[("damage_multiplier",)][1])
        )
        assert on_disk["bots"] == _NORMAL["bots"]
        assert settings.config == on_disk

    @pytest.mark.parametrize("preset", ["hard", CUSTOM_PRESET])
    def test_save_then_load_round_trips(self, files, preset):
        GameplaySettings().save({"preset": preset, **_VALID})
        assert GameplaySettings().config == {"preset": preset, **_VALID}

    def test_preset_heads_the_saved_file(self, files):
        GameplaySettings().save({**_VALID, "preset": CUSTOM_PRESET})
        assert files.read_text().startswith(f"preset: {CUSTOM_PRESET}\n")


# ---------------------------------------------------------------------------
# gameplay_config
# ---------------------------------------------------------------------------


class TestGameplayConfig:
    def test_returns_the_apps_settings(self):
        game = MagicMock()
        game.app.gameplay_settings.config = _VALID
        assert gameplay_config(game) is _VALID

    def test_mock_app_falls_back_to_default_preset(self):
        """A MagicMock app's config is not a dict: use the default preset."""
        expected = {"preset": DEFAULT_PRESET, **load_presets()[DEFAULT_PRESET]}
        assert gameplay_config(MagicMock()) == expected

    def test_app_without_settings_falls_back_to_default_preset(self):
        game = types.SimpleNamespace(app=types.SimpleNamespace())
        assert gameplay_config(game)["preset"] == DEFAULT_PRESET


# ---------------------------------------------------------------------------
# Shipped presets
# ---------------------------------------------------------------------------


class TestShippedPresets:
    def test_presets_in_menu_order(self):
        assert list(load_presets()) == ["easy", "normal", "hard", "ace"]

    def test_every_preset_is_complete_and_valid(self):
        """Every preset sets every value, in its limits (or loading raises)."""
        load_presets()

    def test_default_preset_matches_the_untuned_game(self):
        """
        The default preset changes nothing: auto-aim as AutoAim builds it, no
        spread, unscaled damage, lead indicator on.
        """
        normal = load_presets()[DEFAULT_PRESET]
        assert normal == _NORMAL
        params = inspect.signature(AutoAim.__init__).parameters
        for side in ("player", "bots"):
            auto_aim = normal[side]["auto_aim"]
            assert auto_aim["enabled"] is True
            assert auto_aim["lock_delay_s"] == params["target_lock_delay_s"].default
            assert (
                auto_aim["lock_angle_deg"]
                == params["acquisition_cone_angle_deg"].default
            )
            assert (
                auto_aim["assist_angle_deg"] == params["max_assist_angle_deg"].default
            )
            assert normal[side]["deviation_deg"] == 0.0
            assert normal[side]["damage_multiplier"] == 1.0
        assert normal["player"]["collision_damage_multiplier"] == 1.0
        assert normal["player"]["lead_indicator"] is True

    def test_shipped_user_file_selects_a_preset(self):
        user = gps._load_file(gps.GAMEPLAY_FILE)
        assert user.get("preset") in [*load_presets(), CUSTOM_PRESET]

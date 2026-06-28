"""
Unit tests for the graphics-settings persistence layer
(:mod:`space_flight.global_architecture.graphics_settings`).

Covers:
- :func:`_deep_merge` — recursive dict overlay
- :meth:`GraphicsSettings.sanitise` — clamping / coercion of every field
- :meth:`GraphicsSettings.load_file` — static YAML loader
- :meth:`GraphicsSettings.load` — defaults + user overlay + sanitise
- :meth:`GraphicsSettings.save` — round-trip to disk
"""

import pytest
import yaml

from space_flight.global_architecture import graphics_settings as gs
from space_flight.global_architecture.graphics_settings import (
    GraphicsSettings,
    _deep_merge,
)

# A fully-populated, valid config matching the YAML schema.
_VALID = {
    "display": {"mode": "windowed", "windowed_size": [1280, 720]},
    "render": {"scale": 0.75, "reflection_scale": 0.5, "mirror_scale": 1.0},
    "antialiasing": {"msaa": 4, "fxaa": True},
}


def _write_yaml(path, data):
    """Dump *data* to *path* as YAML and return the path."""
    path.write_text(yaml.dump(data))
    return path


# ---------------------------------------------------------------------------
# _deep_merge
# ---------------------------------------------------------------------------


class TestDeepMerge:
    def test_override_replaces_scalar(self):
        assert _deep_merge({"a": 1}, {"a": 2}) == {"a": 2}

    def test_missing_override_key_keeps_base(self):
        assert _deep_merge({"a": 1, "b": 2}, {"a": 9}) == {"a": 9, "b": 2}

    def test_nested_dicts_merged_key_by_key(self):
        base = {"render": {"scale": 1.0, "mirror_scale": 1.0}}
        override = {"render": {"scale": 0.5}}
        assert _deep_merge(base, override) == {
            "render": {"scale": 0.5, "mirror_scale": 1.0}
        }

    def test_empty_override_returns_copy_of_base(self):
        base = {"a": {"b": 1}}
        out = _deep_merge(base, {})
        assert out == base
        # Must be a copy, not the same nested object.
        out["a"]["b"] = 99
        assert base["a"]["b"] == 1

    def test_none_override_treated_as_empty(self):
        assert _deep_merge({"a": 1}, None) == {"a": 1}


# ---------------------------------------------------------------------------
# GraphicsSettings.sanitise
# ---------------------------------------------------------------------------


class TestSanitise:
    def test_valid_config_passes_through(self):
        assert GraphicsSettings.sanitise(_VALID) == _VALID

    def test_does_not_mutate_input(self):
        src = {"render": {"scale": 5.0}}
        GraphicsSettings.sanitise(src)
        assert src["render"]["scale"] == 5.0  # untouched

    def test_invalid_mode_defaults_to_fullscreen(self):
        out = GraphicsSettings.sanitise({"display": {"mode": "bogus"}})
        assert out["display"]["mode"] == "fullscreen"

    @pytest.mark.parametrize("mode", ["fullscreen", "windowed"])
    def test_valid_modes_preserved(self, mode):
        out = GraphicsSettings.sanitise({"display": {"mode": mode}})
        assert out["display"]["mode"] == mode

    def test_window_size_floored_to_minimums(self):
        out = GraphicsSettings.sanitise({"display": {"windowed_size": [100, 100]}})
        assert out["display"]["windowed_size"] == [640, 480]

    def test_window_size_floats_coerced_to_int(self):
        out = GraphicsSettings.sanitise({"display": {"windowed_size": [1280.0, 720.9]}})
        assert out["display"]["windowed_size"] == [1280, 720]

    def test_window_size_malformed_falls_back(self):
        out = GraphicsSettings.sanitise({"display": {"windowed_size": "nope"}})
        assert out["display"]["windowed_size"] == [1280, 720]

    @pytest.mark.parametrize(
        "raw,expected",
        [(5.0, 1.0), (0.0, 0.25), (0.6, 0.6), (1.0, 1.0), (0.25, 0.25)],
    )
    def test_scale_clamped(self, raw, expected):
        out = GraphicsSettings.sanitise({"render": {"scale": raw}})
        assert out["render"]["scale"] == pytest.approx(expected)

    def test_scale_non_numeric_falls_back(self):
        out = GraphicsSettings.sanitise({"render": {"scale": "big"}})
        assert out["render"]["scale"] == 1.0

    @pytest.mark.parametrize(
        "raw,expected",
        [(0.01, 0.1), (2.0, 1.0), (0.5, 0.5)],
    )
    def test_reflection_scale_clamped(self, raw, expected):
        out = GraphicsSettings.sanitise({"render": {"reflection_scale": raw}})
        assert out["render"]["reflection_scale"] == pytest.approx(expected)

    @pytest.mark.parametrize(
        "raw,expected",
        [(0.1, 0.5), (9.0, 2.0), (1.5, 1.5)],
    )
    def test_mirror_scale_clamped(self, raw, expected):
        out = GraphicsSettings.sanitise({"render": {"mirror_scale": raw}})
        assert out["render"]["mirror_scale"] == pytest.approx(expected)

    @pytest.mark.parametrize("msaa", [0, 2, 4, 8])
    def test_valid_msaa_preserved(self, msaa):
        out = GraphicsSettings.sanitise({"antialiasing": {"msaa": msaa}})
        assert out["antialiasing"]["msaa"] == msaa

    @pytest.mark.parametrize("msaa", [1, 3, 16, "x", None])
    def test_invalid_msaa_defaults_to_zero(self, msaa):
        out = GraphicsSettings.sanitise({"antialiasing": {"msaa": msaa}})
        assert out["antialiasing"]["msaa"] == 0

    @pytest.mark.parametrize(
        "raw,expected",
        [(True, True), (False, False), (1, True), (0, False), ("y", True)],
    )
    def test_fxaa_coerced_to_bool(self, raw, expected):
        out = GraphicsSettings.sanitise({"antialiasing": {"fxaa": raw}})
        assert out["antialiasing"]["fxaa"] is expected

    def test_empty_config_produces_full_defaults(self):
        out = GraphicsSettings.sanitise({})
        assert out["display"]["mode"] == "fullscreen"
        assert out["render"]["scale"] == 1.0
        assert out["render"]["reflection_scale"] == 0.5
        assert out["render"]["mirror_scale"] == 1.0
        assert out["antialiasing"]["msaa"] == 0
        assert out["antialiasing"]["fxaa"] is False


# ---------------------------------------------------------------------------
# GraphicsSettings.load_file
# ---------------------------------------------------------------------------


class TestLoadFile:
    def test_parses_yaml_to_dict(self, tmp_path):
        f = _write_yaml(tmp_path / "g.yaml", {"render": {"scale": 0.5}})
        assert GraphicsSettings.load_file(f) == {"render": {"scale": 0.5}}

    def test_empty_file_returns_empty_dict(self, tmp_path):
        f = tmp_path / "empty.yaml"
        f.write_text("")
        assert GraphicsSettings.load_file(f) == {}


# ---------------------------------------------------------------------------
# GraphicsSettings.load
# ---------------------------------------------------------------------------


class TestLoad:
    def test_user_file_overlays_defaults(self, tmp_path, monkeypatch):
        default = _write_yaml(tmp_path / "default.yaml", _VALID)
        user = _write_yaml(tmp_path / "user.yaml", {"render": {"scale": 0.5}})
        monkeypatch.setattr(gs, "DEFAULT_GRAPHICS_FILE", default)
        monkeypatch.setattr(gs, "GRAPHICS_FILE", user)

        cfg = GraphicsSettings().config
        # Overridden by user...
        assert cfg["render"]["scale"] == 0.5
        # ...everything else from defaults.
        assert cfg["antialiasing"]["msaa"] == 4
        assert cfg["display"]["mode"] == "windowed"

    def test_missing_user_file_uses_defaults(self, tmp_path, monkeypatch):
        default = _write_yaml(tmp_path / "default.yaml", _VALID)
        monkeypatch.setattr(gs, "DEFAULT_GRAPHICS_FILE", default)
        monkeypatch.setattr(gs, "GRAPHICS_FILE", tmp_path / "does_not_exist.yaml")
        assert GraphicsSettings().config == _VALID

    def test_result_is_sanitised(self, tmp_path, monkeypatch):
        default = _write_yaml(tmp_path / "default.yaml", _VALID)
        user = _write_yaml(tmp_path / "user.yaml", {"render": {"scale": 99.0}})
        monkeypatch.setattr(gs, "DEFAULT_GRAPHICS_FILE", default)
        monkeypatch.setattr(gs, "GRAPHICS_FILE", user)
        assert GraphicsSettings().config["render"]["scale"] == 1.0

    def test_malformed_user_file_falls_back_to_defaults(self, tmp_path, monkeypatch):
        default = _write_yaml(tmp_path / "default.yaml", _VALID)
        user = tmp_path / "user.yaml"
        user.write_text("{ this: is: not: valid: yaml")
        monkeypatch.setattr(gs, "DEFAULT_GRAPHICS_FILE", default)
        monkeypatch.setattr(gs, "GRAPHICS_FILE", user)
        # Should not raise; defaults are used.
        assert GraphicsSettings().config == _VALID


# ---------------------------------------------------------------------------
# GraphicsSettings.save
# ---------------------------------------------------------------------------


class TestSave:
    def test_writes_sanitised_config_to_disk(self, tmp_path, monkeypatch):
        default = _write_yaml(tmp_path / "default.yaml", _VALID)
        target = tmp_path / "user.yaml"
        monkeypatch.setattr(gs, "DEFAULT_GRAPHICS_FILE", default)
        monkeypatch.setattr(gs, "GRAPHICS_FILE", target)

        settings = GraphicsSettings()
        settings.save({"render": {"scale": 99.0}})  # out-of-range -> clamped

        on_disk = yaml.safe_load(target.read_text())
        assert on_disk["render"]["scale"] == 1.0
        assert settings.config["render"]["scale"] == 1.0

    def test_save_then_load_round_trips(self, tmp_path, monkeypatch):
        default = _write_yaml(tmp_path / "default.yaml", _VALID)
        target = tmp_path / "user.yaml"
        monkeypatch.setattr(gs, "DEFAULT_GRAPHICS_FILE", default)
        monkeypatch.setattr(gs, "GRAPHICS_FILE", target)

        GraphicsSettings().save(_VALID)
        assert GraphicsSettings().config == _VALID

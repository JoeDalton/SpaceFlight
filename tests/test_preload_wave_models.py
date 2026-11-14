"""
The ship models of a level's waves, loaded while the level loads (a model
first loaded when its wave spawns stalls the game).
"""

import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

from space_flight import DATAFILES_PATH
from space_flight.actors.ship_model import exterior_model_path
from space_flight.game.flight_state import FlightState
from space_flight.game.scenario import WaveSpec


def test_exterior_model_path():
    assert exterior_model_path("cr-90") == (
        DATAFILES_PATH / "models/ships/cr-90/scene.gltf"
    )
    assert exterior_model_path("no-such-ship") is None


def test_every_waves_model_is_loaded_once_a_build_step_each(monkeypatch):
    """The WaveSpec constants of the mission's module: each kind of ship
    loaded once (a mixed wave's too), unknown kinds skipped."""
    module = types.ModuleType("fake_level")
    module.CONVOY = WaveSpec(
        name="convoy", ship_model=[("cr-90", 1), ("gr-75", 2)], bot_type="major_ship"
    )
    module.ESCORT = WaveSpec(name="escort", ship_model="x-wing", size=4)
    module.MORE_ESCORT = WaveSpec(name="more", ship_model="x-wing", size=2)
    module.ODD = WaveSpec(name="odd", ship_model="no-such-ship", size=1)
    module.NOT_A_WAVE = "x-wing"

    def mission(m):
        yield

    mission.__module__ = "fake_level"
    monkeypatch.setitem(sys.modules, "fake_level", module)
    get_asset = MagicMock()
    flight = SimpleNamespace(
        app=SimpleNamespace(asset_manager=SimpleNamespace(get_asset=get_asset))
    )

    steps = list(
        FlightState._preload_wave_models(flight, SimpleNamespace(mission=mission))
    )

    loaded = [call.kwargs["path"] for call in get_asset.call_args_list]
    assert loaded == [
        exterior_model_path("cr-90"),
        exterior_model_path("gr-75"),
        exterior_model_path("x-wing"),
    ]
    assert all(
        call.kwargs["asset_type"] == "model" for call in get_asset.call_args_list
    )
    assert len(steps) == 3

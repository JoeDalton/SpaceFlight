"""The speed dust: its geometry and its per-frame update (the motes move on
the GPU)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from panda3d.core import NodePath, Texture

from space_flight.fx.speed_dust_cloud import (
    MAX_DUST_ALPHA,
    TRAVEL_WRAP_DEPTHS,
    SpeedDustCloud,
)


@pytest.fixture
def game():
    texture_pool = SimpleNamespace(get_texture=lambda: Texture("dust"))
    app = SimpleNamespace(
        asset_manager=SimpleNamespace(get_asset=lambda **_: texture_pool)
    )
    pawn = SimpleNamespace(
        node=NodePath("ship"), speed=np.zeros(3), max_speed_mps=200.0
    )
    return SimpleNamespace(
        app=app,
        player=SimpleNamespace(pawn=pawn),
        method_lists={},
        game_time=MagicMock(get_time_step=lambda: 0.5),
    )


def test_one_geometry_per_colour_and_a_quad_per_mote(game):
    dust = SpeedDustCloud(game, num_particles=40, colors=["blue", "white"])
    assert 1 <= len(dust.particles) <= 2
    quads = sum(
        path.node().get_geom(0).get_vertex_data().get_num_rows() // 4
        for path in dust.particles
    )
    assert quads == 40
    assert game.method_lists[dust.id] == [dust.dust_update]


def test_the_update_moves_the_dust_by_the_distance_flown(game):
    dust = SpeedDustCloud(game, num_particles=4, depth=100.0)
    game.player.pawn.speed = np.array([0.0, 200.0, 0.0])
    dust.dust_update()
    assert dust.travel == pytest.approx(100.0)  # 200 m/s for 0.5 s
    assert dust._travel_input[0] == pytest.approx(100.0)
    assert dust.root.get_color_scale()[3] == pytest.approx(MAX_DUST_ALPHA, abs=1e-3)
    # Kept modulo a whole number of depths
    dust.travel = 100.0 * TRAVEL_WRAP_DEPTHS - 50.0
    dust.dust_update()
    assert dust.travel == pytest.approx(50.0)
    dust.clean()

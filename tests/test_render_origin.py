"""
Unit tests for the floating render origin (space_flight.game.render_origin),
and for what keeps its own coordinates through it: munitions and particle
buffers.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from panda3d.core import GeomVertexReader, NodePath, Shader

from space_flight.fx import ANCHOR_REACH_M, ParticleBuffer
from space_flight.game.render_origin import REBASE_DISTANCE_M, RenderOrigin
from space_flight.weapons import Munition

# The moon's distance: float32 steps are a metre there
FAR = np.array([3.0e6, -9.0e6, 1.234567e6])
# Who fires the test munitions
SHOOTER = SimpleNamespace(id="shooter", team=1, name="shooter")
# A shader object (never compiled: nothing is drawn)
_SHADER = Shader.make(
    Shader.SL_GLSL, "#version 140\nvoid main() {}", "#version 140\nvoid main() {}"
)


def make_origin() -> tuple[RenderOrigin, NodePath, NodePath]:
    """:return: A render origin, its game root, and render above it"""
    render = NodePath("render")
    root = render.attachNewNode("game_root_node")
    return RenderOrigin(root), root, render


# ---------------------------
# Conversions and re-basing
# ---------------------------


def test_starts_at_the_world_origin():
    origin, _, _ = make_origin()

    np.testing.assert_array_equal(origin.origin, np.zeros(3))
    np.testing.assert_array_equal(origin.to_local(FAR), FAR)


def test_conversions_round_trip_in_float64():
    origin, _, _ = make_origin()
    origin.rebase(FAR)
    point = FAR + np.array([0.123456, -7.5, 1e-4])

    np.testing.assert_allclose(origin.to_local(point), point - FAR)
    np.testing.assert_allclose(origin.to_world(origin.to_local(point)), point)


def test_follow_within_reach_only_offsets_the_root():
    origin, root, _ = make_origin()
    player = np.array([REBASE_DISTANCE_M - 1.0, 0.0, 0.0])

    assert origin.follow(player) is False

    np.testing.assert_array_equal(origin.origin, np.zeros(3))
    assert tuple(root.getPos()) == pytest.approx(tuple(-player))


def test_follow_out_of_reach_rebases_onto_the_player():
    origin, root, _ = make_origin()

    assert origin.follow(FAR) is True

    np.testing.assert_array_equal(origin.origin, FAR)
    assert tuple(root.getPos()) == (0.0, 0.0, 0.0)


def test_rebase_keeps_the_roots_children_where_they_are_in_the_world():
    origin, root, _ = make_origin()
    waypoint = root.attachNewNode("waypoint")
    world = np.array([4000.0, 3000.0, -200.0])
    waypoint.setPos(*origin.to_local(world))

    origin.rebase(np.array([4500.0, 2500.0, 0.0]))

    np.testing.assert_allclose(origin.to_world(waypoint.getPos(root)), world, atol=1e-3)


def test_rebase_tells_its_subscribers_the_shift():
    origin, _, _ = make_origin()
    shifts = []
    origin.subscribe(shifts.append)
    origin.rebase(np.array([10.0, 0.0, 0.0]))
    origin.unsubscribe(shifts.append)
    origin.rebase(np.array([30.0, 0.0, 0.0]))

    assert len(shifts) == 1
    np.testing.assert_array_equal(shifts[0], [10.0, 0.0, 0.0])


def test_a_node_far_from_the_world_origin_is_placed_to_the_millimetre():
    """The point of it all: near the player, far from the world's origin,
    render positions are as precise as near the origin."""
    origin, root, render = make_origin()
    player = FAR
    bolt_world = FAR + np.array([12.3456, 80.1234, -3.21])
    origin.follow(player)
    bolt = root.attachNewNode("bolt")
    bolt.setPos(*origin.to_local(bolt_world))

    np.testing.assert_allclose(
        np.array(bolt.getPos(render)), bolt_world - player, atol=1e-3
    )


# ---------------------------
# Munitions coast from float64
# ---------------------------


class _Shot(Munition):
    def _build_visual(self, start_position):
        return self.game.root_node.attachNewNode("shot")

    def _attach_collider(self):
        return self.shot.attachNewNode("collider")


def make_munition_game():
    render = NodePath("render")
    root = render.attachNewNode("game_root_node")
    clock = SimpleNamespace(t=0.0)
    game = MagicMock()
    game.root_node = root
    game.render_origin = RenderOrigin(root)
    game.game_time.get_current_time.side_effect = lambda: clock.t
    game.method_lists = {}
    game.game_objects = {}
    return game, clock


def test_munition_coasts_from_its_launch_across_a_rebase():
    game, clock = make_munition_game()
    game.render_origin.rebase(FAR)
    speed = np.array([0.0, 600.0, 0.0])
    shot = _Shot(
        game=game,
        origin_ship_id=SHOOTER.id,
        origin_ship=SHOOTER,
        power=1.0,
        life_time_s=5.0,
        speed=speed,
        start_position=FAR + np.array([1.0, 2.0, 3.0]),
    )
    assert game.method_lists[shot.id] == [shot.move]

    clock.t = 0.5
    shot.move()
    game.render_origin.rebase(FAR + np.array([0.0, 6000.0, 0.0]))
    clock.t = 1.0
    shot.move()

    expected = FAR + np.array([1.0, 2.0, 3.0]) + speed * 1.0
    np.testing.assert_allclose(shot.impact_position(), expected, atol=1e-3)


def test_munition_unregisters_its_move_on_clean():
    game, _ = make_munition_game()
    shot = _Shot(
        game=game,
        origin_ship_id=SHOOTER.id,
        origin_ship=SHOOTER,
        power=1.0,
        life_time_s=5.0,
        speed=np.zeros(3),
        start_position=np.zeros(3),
    )
    shot_id = shot.id

    shot.clean()

    assert shot_id not in game.method_lists


# ---------------------------
# Particle buffers keep an anchor
# ---------------------------


def make_buffer() -> ParticleBuffer:
    render = NodePath("render")
    root = render.attachNewNode("game_root_node")
    game = MagicMock()
    game.root_node = root
    game.render_origin = RenderOrigin(root)
    game.method_lists = {}
    game.headless = True
    return ParticleBuffer(game=game, shader=_SHADER, columns=[("lifetime", 1)])


def particle_world_position(buffer: ParticleBuffer, slot_index: int) -> np.ndarray:
    """A particle's spawn position, back in the world frame."""
    reader = GeomVertexReader(buffer.vdata, "vertex")
    reader.setRow(slot_index * 4)
    local = np.array(reader.getData3(), dtype=float)
    root = buffer.game.root_node
    return buffer.game.render_origin.to_world(
        np.array(buffer.node_path.getPos(root)) + local
    )


def test_particles_are_written_relative_to_the_anchor():
    buffer = make_buffer()
    buffer.move_anchor(FAR)

    buffer.write_slot(0, pos=FAR + np.array([5.0, 0.0, 0.0]), lifetime=10.0)

    reader = GeomVertexReader(buffer.vdata, "vertex")
    reader.setRow(0)
    assert tuple(reader.getData3()) == pytest.approx((5.0, 0.0, 0.0))


def test_a_far_spawn_moves_the_anchor_keeping_live_particles_in_place():
    buffer = make_buffer()
    first = np.array([10.0, 20.0, 30.0])
    buffer.write_slot(0, pos=first, lifetime=10.0)

    far = np.array([ANCHOR_REACH_M * 3.0, 0.0, 0.0])
    buffer.write_slot(1, pos=far, lifetime=10.0)

    np.testing.assert_array_equal(buffer.anchor, far)
    np.testing.assert_allclose(particle_world_position(buffer, 0), first, atol=1e-3)
    np.testing.assert_allclose(particle_world_position(buffer, 1), far, atol=1e-3)


def test_a_rebase_keeps_particles_in_place():
    buffer = make_buffer()
    spot = np.array([100.0, -50.0, 7.0])
    buffer.write_slot(0, pos=spot, lifetime=10.0)

    buffer.game.render_origin.rebase(np.array([4000.0, 4000.0, 0.0]))

    np.testing.assert_allclose(particle_world_position(buffer, 0), spot, atol=1e-3)

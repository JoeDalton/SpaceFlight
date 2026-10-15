"""
Unit tests for the generic SubSystem (shield generators, ship-mounted turrets).

Instances are built with object.__new__ so individual methods can be
exercised without Panda3D assets or a running game.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
from panda3d.core import NodePath

from space_flight.actors.major_ship.sub_system import SubSystem
from space_flight.fx import spark_fx
from space_flight.weapons import (
    ION,
    ION_CAPACITY_HEALTH_FRACTION,
    ION_DAMAGE_FACTOR,
    ION_DISABLE_DURATION_S,
    ION_LOAD_DECAY_RATE_PS,
)


def make_game_and_parent(team: int = 2):
    """
    Build a mock game and parent ship sufficient to run SubSystem.__init__
    (no loader/traverser needed: a subsystem collider is into-only).
    """
    game = MagicMock()
    game.destructibles.alive_objects = []
    game.method_lists = {}
    game.root_node = NodePath("root")
    parent = SimpleNamespace(
        team=team, node=NodePath("ship"), is_dead=False, speed=np.zeros(3)
    )
    parent.node.reparentTo(game.root_node)
    return game, parent


def make_sub_system_without_init(
    parent=None,
    max_health: float = 1000.0,
    current_health: float = 1000.0,
):
    """
    Build a SubSystem that bypasses __init__ for isolated method testing.
    """
    sub_system = object.__new__(SubSystem)
    sub_system.parent = parent
    sub_system.mounted_on = parent
    sub_system.max_health = max_health
    sub_system.health = current_health
    sub_system.explosion_scale = 10.0
    sub_system.position = np.zeros(3)
    sub_system.is_dead = False
    sub_system.is_clean = False
    return sub_system


# ---------------------------
# apply_damage
# ---------------------------


def test_apply_damage_physical_reduces_health():
    """
    Physical damage is subtracted directly from the subsystem's health.
    """
    sub_system = make_sub_system_without_init(current_health=500.0)

    sub_system.apply_damage(damage=120.0, damage_type="physical")

    assert sub_system.health == pytest.approx(380.0)


def test_apply_damage_unknown_type_raises():
    """
    An unrecognised damage type raises NotImplementedError.
    """
    sub_system = make_sub_system_without_init()

    with pytest.raises(NotImplementedError):
        sub_system.apply_damage(damage=10.0, damage_type="energy")


def test_take_hit_applies_physical_damage():
    """
    take_hit funnels into physical apply_damage, ignoring the impact normal.
    """
    sub_system = make_sub_system_without_init(current_health=200.0)

    sub_system.take_hit(damage=50.0, normal_world_vector=np.array([1.0, 0.0, 0.0]))

    assert sub_system.health == pytest.approx(150.0)


# ---------------------------
# handle_health
# ---------------------------


def test_handle_health_clamps_to_max_and_refreshes_position():
    """
    With a live parent, handle_health clamps health to max and refreshes the
    world position used by the death explosion.
    """
    parent = SimpleNamespace(is_dead=False)
    sub_system = make_sub_system_without_init(
        parent=parent, max_health=1000.0, current_health=1200.0
    )
    sub_system.game = MagicMock()
    sub_system.node = MagicMock()
    sub_system.node.getPos.return_value = (1.0, 2.0, 3.0)

    sub_system.handle_health()

    assert sub_system.health == pytest.approx(1000.0)
    np.testing.assert_allclose(sub_system.position, [1.0, 2.0, 3.0])


def test_handle_health_zeroes_health_when_parent_is_dead():
    """
    A subsystem whose parent ship is dead drops its own health to zero so the
    death handler cleans it up next.
    """
    parent = SimpleNamespace(is_dead=True)
    sub_system = make_sub_system_without_init(parent=parent, current_health=800.0)

    sub_system.handle_health()

    assert sub_system.health == pytest.approx(0.0)


def test_handle_health_zeroes_health_when_parent_is_gone():
    """
    A subsystem whose parent reference is gone drops its health to zero.
    """
    sub_system = make_sub_system_without_init(parent=None, current_health=800.0)

    sub_system.handle_health()

    assert sub_system.health == pytest.approx(0.0)


def test_dead_parent_leads_to_death_via_get_health():
    """
    End-to-end of the teardown contract: once the parent ship is dead,
    handle_health zeroes health and get_health then reports the subsystem as
    dead, which is exactly what Destructibles.handle_deaths checks to clean it.
    """
    parent = SimpleNamespace(is_dead=True)
    sub_system = make_sub_system_without_init(parent=parent, current_health=800.0)

    sub_system.handle_health()

    assert sub_system.get_health() <= 0.0


# ---------------------------
# get_health / play_death
# ---------------------------


def test_get_health_returns_current_health():
    """
    get_health reports the subsystem's current health.
    """
    sub_system = make_sub_system_without_init(current_health=333.0)

    assert sub_system.get_health() == pytest.approx(333.0)


def test_play_death_spawns_explosion_at_position():
    """
    play_death spawns an explosion at the subsystem's last known position, using
    its parent ship's velocity as the base velocity.
    """
    parent = SimpleNamespace(speed=np.array([5.0, 0.0, 0.0]))
    sub_system = make_sub_system_without_init(parent=parent)
    sub_system.position = np.array([10.0, 20.0, 30.0])
    sub_system.explosion_scale = 15.0
    sub_system.game = MagicMock()

    sub_system.play_death()

    sub_system.game.fire_smoke_pool.burst.assert_called_once()
    kwargs = sub_system.game.fire_smoke_pool.burst.call_args.kwargs
    np.testing.assert_allclose(kwargs["position"], [10.0, 20.0, 30.0])
    assert kwargs["scale"] == pytest.approx(15.0)
    np.testing.assert_allclose(kwargs["base_velocity"], [5.0, 0.0, 0.0])


def test_play_death_is_safe_after_clean():
    """
    Calling play_death on an already-cleaned subsystem (game dropped) is a no-op.
    """
    sub_system = make_sub_system_without_init()
    sub_system.game = None

    # Should not raise
    sub_system.play_death()


# ---------------------------
# clean
# ---------------------------


def test_clean_removes_nodes_and_marks_dead():
    """
    clean stops tasks, removes the collision, model and root nodes, and flags the
    subsystem as dead and cleaned. It is idempotent.
    """
    sub_system = make_sub_system_without_init()
    sub_system.game = MagicMock()
    sub_system.game.method_lists = {}
    collision_np = MagicMock()
    sub_system.collision_np = collision_np
    sub_system.model = MagicMock()
    sub_system.node = MagicMock()

    sub_system.clean()

    collision_np.remove_node.assert_called_once()
    assert sub_system.collision_np is None
    assert sub_system.model is None
    assert sub_system.node is None
    assert sub_system.is_dead is True
    assert sub_system.is_clean is True

    # Idempotent: a second call does nothing and does not raise
    sub_system.clean()


# ---------------------------
# targetability (real __init__)
# ---------------------------


def test_subsystem_registers_as_targetable_actor():
    """
    A subsystem tags itself with the "sub_system" category, takes its parent
    ship's team, and registers with the interaction actors so it can be locked
    onto.
    """
    game, parent = make_game_and_parent(team=2)

    sub_system = SubSystem(game=game, parent=parent, hit_box_radius_m=5.0)

    assert sub_system.category == "sub_system"
    assert sub_system.team == 2
    game.interactions.add_actor.assert_called_once_with(sub_system)
    assert sub_system in game.destructibles.alive_objects


def test_clean_deregisters_from_interactions():
    """
    Cleaning a subsystem removes it from the targetable actors.
    """
    game, parent = make_game_and_parent()
    sub_system = SubSystem(game=game, parent=parent, hit_box_radius_m=5.0)
    interactions = game.interactions

    sub_system.clean()

    interactions.remove_actor.assert_called_once()
    assert sub_system.is_clean is True


# ---------------------------
# Box collider
# ---------------------------


def test_sub_system_collides_as_a_sphere_by_default():
    """Without half-extents, the collider is a sphere of hit_box_radius_m."""
    from panda3d.core import CollisionSphere

    game, parent = make_game_and_parent()

    sub_system = SubSystem(game=game, parent=parent, hit_box_radius_m=6.0)

    solid = sub_system.collision_np.node().getSolid(0)
    assert isinstance(solid, CollisionSphere)
    assert solid.getRadius() == pytest.approx(6.0)
    assert sub_system.half_extents_m is None


def test_sub_system_can_collide_as_a_box():
    """
    Given half-extents, the collider is a box of that size centred on the
    mounting point, and hit_box_radius_m becomes its bounding radius.
    """
    from panda3d.core import CollisionBox

    game, parent = make_game_and_parent()

    sub_system = SubSystem(
        game=game, parent=parent, hit_box_radius_m=6.0, half_extents_m=[3.0, 4.0, 12.0]
    )

    solid = sub_system.collision_np.node().getSolid(0)
    assert isinstance(solid, CollisionBox)
    np.testing.assert_allclose(solid.getMin(), [-3.0, -4.0, -12.0])
    np.testing.assert_allclose(solid.getMax(), [3.0, 4.0, 12.0])
    assert sub_system.hit_box_radius_m == pytest.approx(13.0)
    assert sub_system.collision_np.getPythonTag("owner") is sub_system


# ---------------------------
# Ion hits: load, disabling, recovery
# ---------------------------


class FakeClock:
    """A settable game clock with a fixed time step."""

    def __init__(self, dt: float = 0.1):
        self.t = 0.0
        self.dt = dt

    def get_current_time(self) -> float:
        return self.t

    def get_time_step(self) -> float:
        return self.dt


def make_ion_sub_system(
    health: float = 1000.0, ion_capacity: float | None = None
) -> SubSystem:
    """
    A real SubSystem on a mock game with a settable clock.
    """
    game, parent = make_game_and_parent()
    game.game_time = FakeClock()
    sub_system = SubSystem(
        game=game, parent=parent, health=health, ion_capacity=ion_capacity
    )
    return sub_system


def test_ion_capacity_defaults_to_a_fraction_of_health():
    """
    It takes ION_CAPACITY_HEALTH_FRACTION of the damage that would destroy a
    subsystem to disable it with ion hits, unless configured otherwise.
    """
    assert make_ion_sub_system(health=800.0).ion_capacity == pytest.approx(
        ION_CAPACITY_HEALTH_FRACTION * 800.0
    )
    assert make_ion_sub_system(ion_capacity=300.0).ion_capacity == 300.0


def test_ion_hits_load_up_without_harming_health():
    """
    Below its capacity, the ion load leaves the subsystem working and
    unharmed.
    """
    sub_system = make_ion_sub_system(ion_capacity=1000.0)

    sub_system.apply_damage(damage=100.0, damage_type=ION)

    assert sub_system.ion_load == pytest.approx(100.0 * ION_DAMAGE_FACTOR)
    assert not sub_system.is_disabled
    assert sub_system.health == 1000.0


def test_reaching_the_ion_capacity_disables():
    """
    Once the load reaches the capacity, the subsystem is disabled for
    ION_DISABLE_DURATION_S, and the load starts over.
    """
    sub_system = make_ion_sub_system(ion_capacity=300.0)
    sub_system.game.game_time.t = 5.0

    sub_system.apply_damage(damage=300.0 / ION_DAMAGE_FACTOR, damage_type=ION)

    assert sub_system.is_disabled
    assert sub_system.ion_load == 0.0
    assert sub_system.disabled_until_s == pytest.approx(5.0 + ION_DISABLE_DURATION_S)


def test_ion_load_bleeds_off():
    """
    The load decays at ION_LOAD_DECAY_RATE_PS of the capacity per second,
    down to zero.
    """
    sub_system = make_ion_sub_system(ion_capacity=1000.0)
    sub_system.ion_load = 500.0

    sub_system.update_ion()

    assert sub_system.ion_load == pytest.approx(
        500.0 - ION_LOAD_DECAY_RATE_PS * 1000.0 * sub_system.game.game_time.dt
    )
    sub_system.ion_load = 1e-6
    sub_system.update_ion()
    assert sub_system.ion_load == 0.0


def test_disabled_sub_system_crackles_then_comes_back_online():
    """
    While disabled, the subsystem throws ion sparks; once the time is up, it
    comes back online.
    """
    sub_system = make_ion_sub_system(ion_capacity=100.0)
    sub_system.apply_damage(damage=100.0, damage_type=ION)
    clock = sub_system.game.game_time

    sub_system.update_ion()
    spark_call = sub_system.game.spark_fx_pool.spawn.call_args
    assert spark_call.kwargs["preset"] is spark_fx.ION

    clock.t = ION_DISABLE_DURATION_S - 0.01
    sub_system.update_ion()
    assert sub_system.is_disabled

    clock.t = ION_DISABLE_DURATION_S
    sub_system.update_ion()
    assert not sub_system.is_disabled


def test_ion_hits_while_disabled_extend_the_disabling():
    """
    Enough ion damage on a disabled subsystem keeps it down longer, without
    re-running the disabling reaction.
    """
    sub_system = make_ion_sub_system(ion_capacity=100.0)
    sub_system.on_disabled = MagicMock()
    sub_system.apply_damage(damage=100.0, damage_type=ION)
    sub_system.game.game_time.t = 4.0

    sub_system.apply_damage(damage=100.0, damage_type=ION)

    assert sub_system.disabled_until_s == pytest.approx(4.0 + ION_DISABLE_DURATION_S)
    sub_system.on_disabled.assert_called_once()

"""
Unit tests for the Shield's strength/animation/lifecycle logic and geometry
dispatch.

Instances bypass __init__ so the pure logic is testable without a loader or
scene graph. The shader/visual and game are mocked; update drives the
state machine (up -> dying -> down -> appearing -> up) and cooldown-gated
regeneration.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from space_flight.actors.major_ship.shield import (
    _APPEARING,
    _DEATH_DURATION_S,
    _DOWN,
    _DOWN_COOLDOWN_MULT,
    _DYING,
    _REGEN_COOLDOWN_S,
    _UP,
    Shield,
)
from space_flight.utils.state_machine import Cooldown, StateMachine
from space_flight.weapons import ION, ION_DAMAGE_FACTOR


class _Clock:
    """A controllable time source for the shield state machine / cooldown."""

    def __init__(self, t: float = 0.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def make_generator(is_dead: bool = False, health: float = 1000.0):
    """A shield-generator stub: only its alive state matters to the shield."""
    return SimpleNamespace(is_dead=is_dead, health=health)


def make_shield_without_init(
    generators=None,
    mounted_on=None,
    max_health: float = 1000.0,
    current_health: float = 1000.0,
    regen_rate: float = 0.0,
    state: str = _UP,
    now: float = 100.0,
    time_step: float = 0.5,
    last_hit_time: float = -1.0e9,
):
    """
    Build a Shield that bypasses __init__ for isolated method testing.

    The visual/shader side (the :class:`ShieldModel`), the anchor node and the
    game clock are mocked, so only the game-logic state machine is exercised.
    generators is the *full* projecting group (pass some as dead to exercise
    the pro-rata perks); it defaults to a single live generator.
    """
    if generators is None:
        generators = [make_generator()]
    if mounted_on is None:
        mounted_on = SimpleNamespace(is_dead=False, health=1000.0)

    shield = object.__new__(Shield)
    shield.mounted_on = mounted_on
    shield.generators = list(generators)
    shield.initial_generator_count = max(1, len(shield.generators))
    # Base (full-strength) perks + their currently-effective values.
    shield.base_max_health = max_health
    shield.base_regen_rate = regen_rate
    shield.max_health = max_health
    shield.health = current_health
    shield.regen_rate = regen_rate
    shield.is_enabled = state == _UP
    shield.is_dead = False
    shield.is_clean = False

    # Lifecycle / animation state, on a controllable clock.
    clock = _Clock(now)
    shield._clock = clock
    shield.state_sm = StateMachine(initial_state=state, clock=clock)
    shield._u = 1.0 if state in (_DOWN, _APPEARING) else 0.0
    shield._final_death = False
    shield._last_fraction = 1.0
    shield.regen_cooldown = Cooldown(_REGEN_COOLDOWN_S, clock=clock)
    # Place the last hit at last_hit_time (unless the sentinel "never hit").
    if last_hit_time > -1.0e8:
        clock.t = last_hit_time
        shield.regen_cooldown.trigger()
        clock.t = now

    # Mocked presentation (ShieldModel), anchor node, and game clock.
    shield.model = MagicMock()
    shield.collision_np = None
    shield.node = MagicMock()
    shield.node.isEmpty.return_value = False
    shield.game = MagicMock()
    shield.game.game_time.get_current_time.side_effect = clock
    shield.game.game_time.get_time_step.return_value = time_step
    return shield


# ---------------------------
# apply_damage / take_hit
# ---------------------------


def test_apply_damage_reduces_strength():
    shield = make_shield_without_init(current_health=1000.0)

    shield.apply_damage(damage=250.0, damage_type="physical")

    assert shield.health == pytest.approx(750.0)


def test_ion_damage_drains_the_shield_harder():
    shield = make_shield_without_init(current_health=1000.0)

    shield.apply_damage(damage=100.0, damage_type=ION)

    assert shield.health == pytest.approx(1000.0 - 100.0 * ION_DAMAGE_FACTOR)


def test_apply_damage_unknown_type_raises():
    shield = make_shield_without_init()

    with pytest.raises(NotImplementedError):
        shield.apply_damage(damage=10.0, damage_type="energy")


def test_take_hit_absorbs_and_stamps_cooldown():
    """
    take_hit funnels into physical apply_damage and stamps the last-hit time
    (which gates regeneration).
    """
    shield = make_shield_without_init(current_health=500.0, now=42.0)

    shield.take_hit(damage=200.0, normal_world_vector=[1.0, 0.0, 0.0])

    assert shield.health == pytest.approx(300.0)
    # The hit stamped the regen cooldown, so regeneration is now gated.
    assert shield.regen_cooldown.ready() is False


def test_take_hit_with_point_forwards_impact_to_model():
    """
    A hit carrying a world point is forwarded to the model as an impact flash,
    stamped with the current time.
    """
    shield = make_shield_without_init(current_health=500.0, now=7.0)

    shield.take_hit(
        damage=10.0,
        normal_world_vector=[1.0, 0.0, 0.0],
        hit_world_point=(1.0, 2.0, 3.0),
    )

    shield.model.add_impact.assert_called_once()
    args = shield.model.add_impact.call_args.args
    assert args[0] == (1.0, 2.0, 3.0)  # world point
    assert args[2] == pytest.approx(7.0)  # spawn time


# ---------------------------
# regeneration + cooldown
# ---------------------------


def test_no_regen_before_cooldown():
    """
    Regeneration does not start until the cooldown since the last hit elapses.
    """
    shield = make_shield_without_init(
        current_health=100.0, regen_rate=10.0, now=100.0, last_hit_time=95.0
    )  # only 5 s since the last hit (< 10 s)

    shield.update()

    assert shield.health == pytest.approx(100.0)  # untouched


def test_regen_after_cooldown():
    """
    After the cooldown, the strength pool regenerates at regen_rate * dt.
    """
    shield = make_shield_without_init(
        current_health=100.0,
        regen_rate=10.0,
        now=100.0,
        time_step=0.5,
        last_hit_time=100.0 - _REGEN_COOLDOWN_S,  # exactly at the cooldown
    )

    shield.update()

    assert shield.health == pytest.approx(105.0)  # 100 + 10 * 0.5
    assert shield.is_enabled is True


def test_down_shield_uses_double_cooldown():
    """
    A collapsed (down) shield waits twice as long before regenerating.
    """
    # 15 s since the last hit: past the 10 s base cooldown but under the 20 s
    # doubled cooldown that applies while the shield is down.
    now = 100.0
    last_hit = now - (_REGEN_COOLDOWN_S * 1.5)
    shield = make_shield_without_init(
        state=_DOWN,
        current_health=0.0,
        regen_rate=10.0,
        now=now,
        last_hit_time=last_hit,
    )

    shield.update()

    assert shield.health == pytest.approx(0.0)  # still waiting (doubled cooldown)
    assert _DOWN_COOLDOWN_MULT == pytest.approx(2.0)


# ---------------------------
# depletion -> death, regen -> appearance
# ---------------------------


def test_depletion_triggers_death_animation():
    """
    Draining the strength pool collapses the shield: it enters the death (retract)
    animation and stops being functional.
    """
    shield = make_shield_without_init(current_health=0.0, regen_rate=0.0)

    shield.update()

    assert shield.state == _DYING
    assert shield.is_enabled is False


def test_death_animation_completes_to_down():
    """
    The death animation runs to completion, leaving the shield down (hidden, not
    functional) -- but still alive as a Destructible while a generator lives.
    """
    shield = make_shield_without_init(
        state=_DYING, current_health=0.0, time_step=_DEATH_DURATION_S + 0.1
    )

    shield.update()

    assert shield.state == _DOWN
    assert shield.is_enabled is False
    assert shield.get_health() > 0.0  # not a final death -> not cleaned


def test_regen_brings_down_shield_back_via_appearance():
    """
    Once a down shield regenerates any strength (after the doubled cooldown), it
    plays the appearance animation on its way back online.
    """
    now = 500.0
    shield = make_shield_without_init(
        state=_DOWN,
        current_health=0.0,
        regen_rate=10.0,
        now=now,
        time_step=0.5,
        last_hit_time=now - (_REGEN_COOLDOWN_S * _DOWN_COOLDOWN_MULT),  # cooldown met
    )

    shield.update()

    assert shield.health > 0.0
    assert shield.state == _APPEARING
    assert shield.is_enabled is False  # not functional mid-animation


def test_appearance_completes_to_up():
    """
    The appearance animation runs to completion, bringing the shield back up and
    functional.
    """
    shield = make_shield_without_init(
        state=_APPEARING, current_health=200.0, time_step=_DEATH_DURATION_S + 0.1
    )

    shield.update()

    assert shield.state == _UP
    assert shield.is_enabled is True


# ---------------------------
# functional-only-when-up
# ---------------------------


@pytest.mark.parametrize("state", [_DYING, _DOWN, _APPEARING])
def test_shield_not_functional_during_animations(state):
    """
    The shield blocks nothing while dying, down, or appearing.
    """
    shield = make_shield_without_init(state=state, current_health=500.0)

    shield.update()

    assert shield.is_enabled is False


# ---------------------------
# final death (destroyed) + cleanup delay
# ---------------------------


def test_all_generators_destroyed_begins_final_death_but_delays_cleanup():
    """
    Destroying every generator starts the death animation but keeps get_health
    positive until the retraction finishes, delaying cleanup.
    """
    generators = [make_generator(is_dead=True, health=0.0) for _ in range(2)]
    shield = make_shield_without_init(generators=generators, time_step=0.1)

    shield.update()

    assert shield._final_death is True
    assert shield.state == _DYING
    assert shield.get_health() > 0.0  # still alive: animation in progress


def test_shield_survives_while_one_generator_lives():
    """
    Losing some (but not all) generators does not end the shield's life; it only
    reduces its perks (see the pro-rata test below).
    """
    generators = [make_generator(is_dead=True), make_generator(is_dead=False)]
    shield = make_shield_without_init(generators=generators, time_step=0.1)

    shield.update()

    assert shield._final_death is False
    assert shield.get_health() > 0.0


def test_final_death_reports_zero_after_animation():
    """
    Once the terminal death animation completes the shield reports zero health so
    the central death handling cleans it.
    """
    generators = [make_generator(is_dead=True, health=0.0)]
    shield = make_shield_without_init(
        generators=generators, time_step=_DEATH_DURATION_S + 0.1
    )

    shield.update()

    assert shield.state == _DOWN
    assert shield.get_health() == pytest.approx(0.0)


# ---------------------------
# pro-rata perks
# ---------------------------


def test_perks_scale_with_surviving_generators():
    """
    Destroying a generator scales the shield's max strength and regen down pro
    rata (remaining / initial), and clamps current strength to the new maximum.
    """
    # 4 generators, 1 destroyed -> 3/4 of the perks.
    generators = [make_generator() for _ in range(4)]
    generators[0] = make_generator(is_dead=True, health=0.0)
    shield = make_shield_without_init(
        generators=generators,
        max_health=1000.0,
        current_health=1000.0,
        regen_rate=40.0,
    )

    shield.update()

    assert shield.max_health == pytest.approx(750.0)  # 1000 * 3/4
    assert shield.regen_rate == pytest.approx(30.0)  # 40 * 3/4
    assert shield.health == pytest.approx(750.0)  # scaled down with the max


def test_partially_depleted_strength_scales_with_lost_generator():
    """A depleted shield loses the same proportion as the max when a generator dies."""
    generators = [make_generator(), make_generator(is_dead=True, health=0.0)]
    shield = make_shield_without_init(
        generators=generators, max_health=1000.0, current_health=300.0
    )

    shield.update()

    assert shield.max_health == pytest.approx(500.0)
    assert shield.health == pytest.approx(150.0)  # 300 * 1/2


def test_strength_scaling_compounds_over_successive_losses():
    """Generators dying in separate frames compound: 4 -> 3 -> 2 alive halves it."""
    generators = [make_generator() for _ in range(4)]
    shield = make_shield_without_init(
        generators=generators, max_health=1000.0, current_health=400.0
    )

    generators[0].is_dead = True
    shield.update()
    assert shield.health == pytest.approx(300.0)  # 400 * 3/4

    generators[1].is_dead = True
    shield.update()
    assert shield.health == pytest.approx(200.0)  # 400 * 2/4
    assert shield.max_health == pytest.approx(500.0)

    shield.update()  # no further change
    assert shield.health == pytest.approx(200.0)


# ---------------------------
# get_shield_level (fleet-AI facing)
# ---------------------------


def test_get_shield_level_is_current_strength():
    """The shield reports its current strength pool (already pro-rata scaled)."""
    shield = make_shield_without_init(current_health=1234.0)

    assert shield.get_shield_level() == pytest.approx(1234.0)


def test_get_shield_level_never_negative():
    """An over-depleted pool still reports a non-negative level."""
    shield = make_shield_without_init(current_health=-5.0)

    assert shield.get_shield_level() == pytest.approx(0.0)


def test_get_shield_level_zero_after_all_generators_destroyed():
    """
    Once every generator is gone the stale strength pool no longer defends, so
    the level reads zero (hull hits must not spark as shield hits).
    """
    generators = [make_generator(is_dead=True, health=0.0) for _ in range(2)]
    shield = make_shield_without_init(
        generators=generators, current_health=500.0, time_step=0.1
    )

    shield.update()

    assert shield._final_death is True
    assert shield.health > 0.0
    assert shield.get_shield_level() == pytest.approx(0.0)


def test_doomed_ship_reparents_shield_to_survive_node_removal():
    """
    When the ship (our mount) is destroyed, the shield reparents its node to the
    world root so it survives the ship node's removal and can play its death.
    """
    ship = SimpleNamespace(is_dead=False, health=0.0)  # doomed this frame
    shield = make_shield_without_init(mounted_on=ship, time_step=0.1)

    shield.update()

    assert shield._final_death is True
    shield.node.wrtReparentTo.assert_called_once()


def test_get_health_positive_while_alive():
    shield = make_shield_without_init()

    assert shield.get_health() > 0.0


# ---------------------------
# geometry dispatch
# ---------------------------


def test_build_geometry_rejects_unknown_shape():
    """An unrecognised primitive shape type is rejected before any build work."""
    from space_flight.actors.major_ship.shield_model import ShieldModel

    with pytest.raises(ValueError):
        ShieldModel(
            loader=MagicMock(),
            parent=MagicMock(),
            color=(1.0, 1.0, 1.0, 1.0),
            shape={"type": "pyramid"},
        )


# ---------------------------
# impact flash size
# ---------------------------


@pytest.mark.parametrize("radius_m", [50.0, 480.0], ids=["frigate", "star_destroyer"])
def test_impact_flash_keeps_one_world_size_on_any_tube(radius_m):
    """
    The impact flash radius is a fixed size in world metres, whatever the
    bubble's size: a star destroyer's mark matches a frigate's.
    """
    from panda3d.core import NodePath

    from space_flight.actors.major_ship.shield_model import (
        _IMPACT_RADIUS_M,
        ShieldModel,
    )

    model = ShieldModel(
        loader=MagicMock(),
        parent=NodePath("ship"),
        shape={
            "type": "tube",
            "point_a": [0.0, -radius_m, 0.0],
            "point_b": [0.0, radius_m, 0.0],
            "radius_m": radius_m,
        },
    )

    world_radius = model.impact_radius_local * model._geom_scale()
    assert world_radius == pytest.approx(_IMPACT_RADIUS_M)


def test_impact_flash_radius_is_converted_to_a_scaled_geometry():
    """
    On a scaled geometry (e.g. the stock unit sphere scaled to the shield
    radius), the flash radius is given in geometry units, so it still spans the
    same world size.
    """
    from panda3d.core import NodePath

    from space_flight.actors.major_ship.shield_model import ShieldModel

    model = object.__new__(ShieldModel)
    ship = NodePath("ship")
    model.visual = ship.attachNewNode("sphere")
    model.visual.setScale(300.0)
    model.geom_np = model.visual

    assert model._geom_scale() == pytest.approx(300.0)


# ---------------------------
# contains (munitions fired from inside pass through)
# ---------------------------


def make_shield_for_contains(shape_type, ship_pos=(0, 0, 0), ship_heading=0.0, **dims):
    """
    A Shield (bypassing __init__) whose node rides a ship placed in a world
    root, with just the geometry contains() reads.
    """
    from panda3d.core import NodePath

    root = NodePath("root")
    ship = root.attachNewNode("ship")
    ship.setPos(*ship_pos)
    ship.setH(ship_heading)
    shield = object.__new__(Shield)
    shield.game = SimpleNamespace(root_node=root)
    shield.node = ship.attachNewNode("shield_node")
    shield.model = SimpleNamespace(shape_type=shape_type, **dims)
    return shield


@pytest.mark.parametrize(
    "point, inside",
    [
        ((0, 0, 0), True),  # centre
        ((0, 440, 470), True),  # near the wall, along the cylinder
        ((0, 0, 490), False),  # just out of the cylinder
        ((0, 600, 0), True),  # in the front cap
        ((0, 950, 0), False),  # past the front cap
        ((0, -1000, 100), True),  # in the rear cap
    ],
)
def test_contains_a_tube(point, inside):
    """A tube bubble contains the points within its radius of its axis segment."""
    shield = make_shield_for_contains(
        "tube", point_a=(0.0, -550.0, 0.0), point_b=(0.0, 450.0, 0.0), radius_m=480.0
    )

    assert shield.contains(np.array(point, dtype=float)) is inside


def test_contains_follows_the_ship():
    """contains() reads world points relative to the moved, turned ship."""
    shield = make_shield_for_contains(
        "tube",
        ship_pos=(5000, 0, 0),
        ship_heading=90.0,  # the ship's +y axis now points to world -x
        point_a=(0.0, -550.0, 0.0),
        point_b=(0.0, 450.0, 0.0),
        radius_m=480.0,
    )

    assert shield.contains(np.array([5000.0 - 900.0, 0.0, 0.0]))  # front cap
    assert not shield.contains(np.array([5000.0, 900.0, 0.0]))  # abeam, outside
    assert not shield.contains(np.zeros(3))


def test_contains_a_sphere():
    """A sphere bubble contains the points within its radius of the ship."""
    shield = make_shield_for_contains("sphere", radius_m=100.0)

    assert shield.contains(np.array([0.0, 99.0, 0.0]))
    assert not shield.contains(np.array([0.0, 101.0, 0.0]))


def test_contains_nothing_in_a_model_bubble():
    """A shared model has no analytic shape: nothing is inside it."""
    shield = make_shield_for_contains("model")

    assert not shield.contains(np.zeros(3))

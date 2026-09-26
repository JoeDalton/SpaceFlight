"""
All-features reference example for mission scripting.

Not a shipped level: it is not in :data:`space_flight.game.levels.LEVELS` and
nothing in the game imports it. It exercises every feature of
:mod:`space_flight.game.scenario` once, as a companion to
docs/source/scenario_scripting.md -- copy its patterns, not its story, which
makes no narrative sense.

It is run end-to-end, with no live engine, by
tests/test_all_features_example.py.

To turn a module like this into a playable level, add a
``build_<x>_upfront(game)`` (player + scene) and register
``LevelEntry(upfront=..., mission=all_features_mission, description=...)``
in space_flight/game/levels/__init__.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator

from space_flight.game.scenario import WaveSpec
from space_flight.game.scenario.conditions import (
    all_of,
    any_of,
    near,
    near_actor,
    not_,
    reached_waypoint,
)

if TYPE_CHECKING:
    from space_flight.game.scenario import Mission

HOMEGUARD_POINT = [0, -1000, 200]

# A plain wave: a single capital ship, spawned in place (no formation, so a
# larger wave would spawn in a centred line), step-by-step recorded.
HOMEGUARD = WaveSpec(
    name="homeguard",
    ship_model="cr-90",
    size=1,
    bot_type="capital_ship",
    team=1,
    spawn_point=HOMEGUARD_POINT,
    record=True,
)

# In formation, patrolling a looping route. The orientation is a quaternion
# (w, x, y, z); the default, (0, 0, 0, 1), is a 180 degree turn about z.
STRIKE_WAVE = WaveSpec(
    name="strike",
    ship_model="tie-fighter",
    size=4,
    spawn_point=[0, 5000, 500],
    spawn_orientation=[0, 0, 0, 1],
    formation="diamond",
    formation_scale_m=40,
    waypoints=[[0, 0, 500], [0, -5000, 500]],
    loop=True,
)

# No formation of its own: joins the strike wave's formation at spawn time.
REINFORCEMENTS = WaveSpec(
    name="reinforcements",
    ship_model="tie-interceptor",
    size=2,
    spawn_point=[0, 5000, 500],
)

# Mixed composition: (model, count) pairs, size inferred (3 ships). No spawn
# point: it is given at spawn time.
BOARDING_PARTY = WaveSpec(
    name="boarding",
    ship_model=[("tie-bomber", 2), ("tie-interceptor", 1)],
)

# Starts neutral, then gets rerouted, reassigned and retargeted live.
PATROL = WaveSpec(
    name="patrol",
    ship_model="y-wing",
    size=1,
    team=0,
    spawn_point=[500, 0, 500],
    waypoints=[[500, 1000, 500], [500, 2000, 500]],
    loop=False,
)


def all_features_mission(m: Mission) -> Iterator[None]:
    """
    Every Mission / WaveHandle / condition feature, one at a time.

    :param m: The mission
    """
    game = m.game

    # --- handles before spawning, so rules can refer to them ---------------
    homeguard = m.wave(HOMEGUARD)
    strike = m.wave(STRIKE_WAVE)

    # --- reactive rules -------------------------------------------------------

    # A wave state method, passed uncalled, is a condition. any_destroyed
    # fires on the first loss (and stays true after a total wipe).
    hit = m.on(
        homeguard.any_destroyed, lambda: m.speech("We're taking losses!", speaker="Ops")
    )

    # delay: 3s after the home guard is wiped -> defeat. m.delay latches, so
    # it keeps counting even if its condition flickers.
    m.on(
        m.delay(homeguard.all_destroyed, 3),
        lambda: m.defeat("The home guard was destroyed."),
    )

    # once=False: repeats every frame the condition holds. near(): the
    # player close to a fixed point.
    m.on(
        near(game.player, HOMEGUARD_POINT, 500),
        lambda: m.hud("Danger close to the home guard!", display_time_s=1),
        once=False,
    )

    # all_of / any_of / not_: build stateful parts (m.after here) once, when
    # the rule is declared.
    m.on(
        all_of(
            homeguard.alive,
            not_(strike.all_destroyed),
            any_of(m.after(20), strike.alive),
        ),
        lambda: m.hud("Engagement in progress.", display_time_s=1),
        once=False,
    )

    # A rule can be retired: this one never gets the chance to fire.
    never = m.on(m.after(9999), lambda: m.hud("Too late."))
    never.cancel()

    # --- the sequential story ---------------------------------------------------

    homeguard.spawn()
    yield from m.wait(1)  # plain time
    m.speech("Home guard in position.", speaker="Ops")
    m.speech("A line with no speaker.")

    strike.spawn(target=homeguard)  # target: a wave
    yield from m.wait_until(strike.alive)  # a condition

    reinforcements = m.spawn(REINFORCEMENTS, join=strike.formation)
    boarding = m.spawn(BOARDING_PARTY, spawn_point=[200, 5200, 600])
    patrol = m.spawn(PATROL, target=game.player)  # target: a single ship

    # reached_waypoint on a wave (any member), with a timeout: wait_until
    # returns True if the condition was met, False if the time ran out.
    arrived = yield from m.wait_until(reached_waypoint(patrol, 0), timeout=60)
    if not arrived:
        m.hud("The patrol got lost.")

    # Live mutations of a spawned wave.
    patrol.set_waypoints([[500, -1000, 500], [500, -2000, 500]], loop=False)
    patrol.set_team(2)
    patrol.set_targets(boarding)

    # Spawning a handle again adds the same composition to the same wave.
    reinforcements.spawn(join=strike.formation)

    # Player waypoints, with optional radii; setting a new route replaces
    # the previous one, and clear_player_waypoints removes it.
    m.player_waypoints([[0, 1000, 500], [0, 2000, 500]])
    m.player_waypoints([[0, 3000, 500]], arrival_radius_m=200, marker_radius_m=50)

    # near_actor: two moving targets (any pair of live pawns). sustained:
    # an unbroken run of seconds, reset whenever the condition drops. (The
    # timeout below is shorter, so only one of the two endings can happen.)
    close_to_boarding = near_actor(game.player, boarding, 300)
    lost = m.on(
        m.sustained(not_(close_to_boarding), 10),
        lambda: m.defeat("You lost the boarding party."),
    )
    shadowed = yield from m.wait_until(close_to_boarding, timeout=8)
    lost.cancel()
    m.clear_player_waypoints()

    # Reading wave state directly, and a rule's fired flag.
    if not shadowed:
        m.end_level("defeat", "The boarding party got away.")
    elif hit.fired or not homeguard.alive():
        m.victory("Mission complete, with losses.")
    else:
        m.victory("Mission complete: every feature exercised.")

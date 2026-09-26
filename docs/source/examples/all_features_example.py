"""
All-features reference example for the Python Mission API.

This file is **not** a shipped level -- it is not registered in
:mod:`space_flight.game.levels` and nothing in the game ever imports it. Its
only job is to exercise, in one place, every documented feature of
:mod:`space_flight.game.scenario.mission` and its supporting conditions/engine
methods, as a companion to docs/source/scenario_scripting.md. Copy the
*patterns* it demonstrates into a real level's own mission function -- do not
copy the story, which makes no narrative sense (it exists purely to touch
every API surface once).

It is exercised end-to-end, with no live Panda3D engine, by
tests/test_all_features_example.py -- see that file for how the "combat"
below (ships dying, a patrol reaching a waypoint) is simulated in a test.

Wave data lives in the sibling all_features_example.yaml, loaded with
:func:`space_flight.game.scenario.loader.load_waves` exactly as a real level
would.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterator

from space_flight.game.scenario.conditions import (
    AllOf,
    AnyOf,
    Delay,
    after_seconds,
    any_alive,
    fired,
    reached_waypoint,
)
from space_flight.game.scenario.mission import Mission

if TYPE_CHECKING:
    from space_flight.game.flight_state import FlightState

# The home guard's spawn point, reused below for the proximity-warning
# condition -- kept as a constant rather than repeating the YAML's
# spawn_point so the two can never drift apart.
HOMEGUARD_SPAWN_POINT = [0, -1000, 200]


def all_features_mission(m: Mission) -> Iterator[None]:
    """
    Exhaustive walkthrough of the Mission API, one feature at a time.

    Structured like a real mission body (reactive rules registered up front,
    then a sequential story below), but every step exists to demonstrate one
    API surface rather than to make a coherent mission -- see the module
    docstring.

    :param m: The level's :class:`Mission`
    """
    # ==================================================================
    # Reactive rules -- registered up front so they hold no matter where
    # the sequential part below currently is (Mission.on).
    # ==================================================================

    homeguard = m.spawn(m.waves["homeguard"])
    yield from m.wait_until(homeguard.alive_cond())  # let its one ship spawn

    # register_query: a *derived* group, computed live from a predicate over
    # every live actor, with no membership stored anywhere (contrast with an
    # identity group like "homeguard" above, whose members are recorded the
    # moment they spawn).
    m.scenario.register_query(
        "enemy_fighters", lambda actor: getattr(actor, "team", None) == 2
    )

    # register: re-registers already-spawned bots under a second, standing
    # group name. Real levels use this for objects built directly rather than
    # through Mission.spawn (e.g. the player's own starting escort); here we
    # just alias the home guard's ships to show the call.
    homeguard_bots = [pawn.parent for pawn in m.scenario.resolve(m.game, "homeguard")]
    m.scenario.register("vip_ship", homeguard_bots)

    # any_destroyed (fires on the FIRST loss, and stays true after a total
    # wipe too -- see docs/source/scenario_scripting.md#conditions).
    m.on(
        homeguard.any_destroyed_cond(),
        lambda game: m.speech("We're taking losses!", speaker="Ops"),
        name="homeguard_hit",
    )

    # all_destroyed, chained through Delay + fired: a reactive contingency
    # ending, independent of the sequential body's own ending below. (A real
    # level would normally guard against firing *both* endings -- e.g. by
    # having the sequential body check `not m.scenario.has_fired("defeat")`
    # before its own m.victory call. Skipped here since this file's only job
    # is to demonstrate each condition once, and the happy-path test below
    # never lets the home guard actually die.)
    m.on(
        homeguard.all_destroyed_cond(),
        lambda game: None,  # a "marker" trigger: only its fired() state matters
        name="homeguard_wiped",
    )
    m.on(
        Delay(fired("homeguard_wiped"), seconds=3),
        lambda game: m.defeat("The home guard was destroyed.", delay=0),
        name="defeat",
    )

    # near(): warn while the player is close to the home guard's spawn point.
    # once=False makes this a repeating rule -- it fires every frame the
    # condition holds, not just the first time.
    m.on(
        near_home_guard(),
        lambda game: m.hud("Danger close to the home guard!"),
        once=False,
        name="proximity_warning",
    )

    # any_alive over a query group, also repeating: a status ping for as long
    # as any enemy fighter is alive.
    m.on(
        any_alive("enemy_fighters"),
        lambda game: m.hud("Enemy fighters detected.", display_time_s=1),
        once=False,
        name="enemy_ping",
    )

    # AllOf / AnyOf combinators, composed directly (not just via Delay/fired
    # above): logged rather than acted on, purely to show the shape.
    m.on(
        AllOf(homeguard.alive_cond(), any_alive("enemy_fighters")),
        lambda game: m.hud("Engagement in progress.", display_time_s=1),
        once=False,
        name="engagement_ping",
    )
    m.on(
        AnyOf(after_seconds(9999), homeguard.all_destroyed_cond()),
        lambda game: None,
        name="unused_anyof_demo",
    )

    # ==================================================================
    # Sequential part -- yield from these to pause the mission body.
    # ==================================================================

    yield from m.wait(1)  # wait(seconds): plain time-based pause
    m.speech("Home guard in position.", speaker="Ops")

    yield from m.wait_until(3)  # wait_until(bare number) == wait(number)

    # Mission.spawn(target=...): a runtime override, not baked into the wave's
    # YAML (contrast with reinforcements' static `target:` key below).
    strike = m.spawn(m.waves["strike_wave"], target=homeguard)

    # wait_until(condition): a condition callable, not a bare number.
    yield from m.wait_until(strike.alive_cond())

    # Mission.spawn(join=...): attaches to strike's existing formation
    # (continuing from its next free slot) instead of spawning a separate
    # cluster -- reinforcements joining an escort already in flight.
    reinforcements = m.spawn(m.waves["reinforcements"], join=strike.formation)

    # A mixed-composition wave (ship_model given as a list in its YAML).
    boarding = m.spawn(m.waves["boarding_party"])

    # A wave that starts neutral, to be reassigned live below.
    patrol = m.spawn(m.waves["patrol"])

    # reached_waypoint: wait for the patrol to reach its first waypoint.
    yield from m.wait_until(reached_waypoint("patrol", 0))

    # The three "on the fly" asks from issue #85, all live mutations of an
    # already-spawned wave via its WaveHandle:
    patrol.set_waypoints(  # reroute mid-mission
        [[500, -1000, 500], [500, -2000, 500]], loop=False
    )
    patrol.set_team(2)  # change its team mid-mission
    patrol.set_targets(boarding)  # set its primary targets mid-mission

    # allow_respawn: the wave's YAML sets allow_respawn: true, so this second
    # Mission.spawn call on the same wave id succeeds instead of being
    # skipped with a warning.
    m.spawn(m.waves["respawnable_probe"])
    yield from m.wait(1)
    m.spawn(m.waves["respawnable_probe"])

    # player_waypoints: both accepted forms.
    m.player_waypoints([[0, 1000, 500], [0, 2000, 500]])  # bare list of points
    m.player_waypoints(  # mapping form, with optional radii
        {
            "points": [[0, 3000, 500]],
            "arrival_radius_m": 200,
            "marker_radius_m": 50,
        }
    )

    # wait_any / wait_all: both combinators over a set of conditions.
    yield from m.wait_any(reinforcements.alive_cond(), after_seconds(9999))
    yield from m.wait_all(boarding.alive_cond(), patrol.alive_cond())

    # end_level/victory: the sequential body's own, ordinary ending.
    m.victory("Mission complete: every scripted feature exercised without incident.")


def near_home_guard():
    """
    A small condition factory built from :func:`conditions.near`, kept out of
    the mission body just to show that a condition can be composed/wrapped in
    an ordinary function rather than written inline -- there is nothing
    special about it.
    """
    from space_flight.game.scenario.conditions import near

    return near("player", HOMEGUARD_SPAWN_POINT, radius=500)


def build_all_features_level_example(game: "FlightState") -> Iterator[str]:
    """
    Shape of a real level's build function, for reference only.

    A real level does this in its own ``build_<x>_level`` generator, after
    building the player and the scene (see e.g.
    :func:`space_flight.game.levels.intro_level.build_intro_level`). This
    function is not wired into the game or the level registry -- it exists
    only so this file reads, top to bottom, as a complete example.

    :param game: The game/flight state
    """
    from pathlib import Path

    from space_flight.game.scenario import Scenario
    from space_flight.game.scenario.loader import load_waves

    game.scenario = Scenario()
    mission = Mission(game)
    mission.waves = load_waves(Path(__file__).with_suffix(".yaml"))
    game.scenario.schedule(all_features_mission(mission))
    yield "scenario"

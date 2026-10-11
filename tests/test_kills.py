"""
Unit tests for kills.py: who gets credited for a hit, and how the kill log
turns deaths into kills (last hitter, collateral subsystems, crashes, the
player's tally). Engine-free: pawns and subsystems are plain stand-ins.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from mission_fakes import FakeGame, MockBot

from space_flight.game.kills import (
    DamageSource,
    KillLog,
    actor_name,
    credit_hit,
)


def make_ship(name: str, team: int, category: str = "fighter") -> SimpleNamespace:
    """A ship pawn named by its controlling Bot."""
    bot = SimpleNamespace(name=name)
    pawn = SimpleNamespace(
        id=uuid.uuid4(),
        parent=bot,
        team=team,
        category=category,
        health=100.0,
        is_dead=False,
    )
    bot.pawn = pawn
    return pawn


def make_subsystem(host: SimpleNamespace, name: str = "generator") -> SimpleNamespace:
    """A subsystem bolted onto host (its parent is the ship, as a generator)."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        parent=host,
        mounted_on=host,
        name=name,
        team=host.team,
        category="sub_system",
        health=50.0,
    )


@pytest.fixture
def game() -> FakeGame:
    return FakeGame()


# ---------------------------
# Names and sources
# ---------------------------


def test_a_ship_is_named_by_its_bot():
    assert actor_name(make_ship("tie_1", team=2)) == "tie_1"


def test_a_generator_is_named_by_its_ship_and_itself():
    isd = make_ship("isd", team=2, category="capital_ship")
    assert actor_name(make_subsystem(isd, name="hangar_0")) == "isd/hangar_0"


def test_a_turret_is_named_by_its_bot():
    isd = make_ship("isd", team=2, category="capital_ship")
    turret = make_subsystem(isd, name="turret")
    turret.parent = SimpleNamespace(name="isd_turret_3")
    assert actor_name(turret) == "isd_turret_3"


def test_source_tells_the_player_apart(game):
    player_source = DamageSource.of(game.player.pawn, game)
    bot_source = DamageSource.of(MockBot("tie", [0, 0, 0], team=2).pawn, game)

    assert player_source.is_player is True
    assert player_source.team == 1
    assert bot_source.is_player is False
    assert bot_source.name == "tie"


def test_source_survives_its_shooter_being_cleaned(game):
    """Captured at fire time, it keeps the shooter's name once torn down."""
    shooter = make_ship("tie_1", team=2)
    source = DamageSource.of(shooter, game)

    shooter.parent = None  # as Ship.clean does

    assert source.name == "tie_1"
    assert source.actor_id == shooter.id


# ---------------------------
# credit_hit
# ---------------------------


def test_last_hitter_is_credited(game):
    target = make_ship("tie_1", team=2)
    first = DamageSource.of(make_ship("x_1", team=1), game)
    second = DamageSource.of(make_ship("x_2", team=1), game)

    credit_hit(target, first)
    credit_hit(target, second, cause="ram")

    assert target.last_hit_by is second
    assert target.last_hit_cause == "ram"


def test_a_hit_on_a_wreck_does_not_steal_the_kill(game):
    target = make_ship("tie_1", team=2)
    killer = DamageSource.of(make_ship("x_1", team=1), game)
    credit_hit(target, killer)
    target.health = 0.0

    credit_hit(target, DamageSource.of(game.player.pawn, game))

    assert target.last_hit_by is killer


# ---------------------------
# KillLog
# ---------------------------


def test_record_credits_the_last_hitter(game):
    log = KillLog(game)
    victim = make_ship("tie_1", team=2)
    credit_hit(victim, DamageSource.of(game.player.pawn, game))
    game.game_time.t = 12.0

    kill = log.record(victim)

    assert kill.killer.is_player
    assert kill.cause == "weapon"
    assert kill.victim_name == "tie_1"
    assert kill.time_s == 12.0
    assert kill.by_player
    assert log.kill_of(victim.id) is kill


def test_record_takes_a_bot_for_its_pawn(game):
    log = KillLog(game)
    victim = make_ship("tie_1", team=2)

    kill = log.record(victim.parent)

    assert kill.victim_id == victim.id


def test_a_turret_dying_as_bot_and_subsystem_is_logged_once(game):
    log = KillLog(game)
    isd = make_ship("isd", team=2, category="capital_ship")
    turret = make_subsystem(isd, name="turret")
    turret_bot = SimpleNamespace(name="isd_turret_0", pawn=turret)
    turret.parent = turret_bot

    log.record(turret_bot)
    log.record(turret)

    assert len(log.kills) == 1


@pytest.mark.parametrize("category", ["missile", "flare", None])
def test_ordnance_and_shields_are_not_kills(game, category):
    log = KillLog(game)
    victim = make_ship("thing", team=2, category=category)

    assert log.record(victim) is None
    assert log.kills == []


def test_a_subsystem_dying_with_its_ship_credits_the_ships_killer(game):
    log = KillLog(game)
    isd = make_ship("isd", team=2, category="capital_ship")
    generator = make_subsystem(isd)
    # Someone else scratched the generator before the player sank the ship
    credit_hit(generator, DamageSource.of(make_ship("x_1", team=1), game))
    credit_hit(isd, DamageSource.of(game.player.pawn, game))
    log.record(isd)
    isd.is_dead = True  # its clean, at the end of its death

    kill = log.record(generator)

    assert kill.cause == "collateral"
    assert kill.killer.is_player


def test_a_subsystem_shot_down_on_a_live_ship_credits_its_hitter(game):
    log = KillLog(game)
    isd = make_ship("isd", team=2, category="capital_ship")
    generator = make_subsystem(isd)
    credit_hit(generator, DamageSource.of(game.player.pawn, game))

    kill = log.record(generator)

    assert kill.cause == "weapon"
    assert kill.by_player


def test_a_crash_credits_no_one(game):
    log = KillLog(game)
    victim = make_ship("tie_1", team=2)
    victim.last_hit_by = None
    victim.last_hit_cause = "crash"

    kill = log.record(victim)

    assert kill.killer is None
    assert kill.cause == "crash"
    assert not kill.by_player


def test_an_untouched_death_is_unknown(game):
    kill = KillLog(game).record(make_ship("tie_1", team=2))

    assert kill.killer is None
    assert kill.cause == "unknown"


def test_the_players_own_death_is_not_their_kill(game):
    log = KillLog(game)
    credit_hit(game.player.pawn, DamageSource.of(game.player.pawn, game))

    kill = log.record(game.player.pawn)

    assert kill.victim_is_player
    assert not kill.by_player


def test_count_filters_by_victims_and_player(game):
    log = KillLog(game)
    player = DamageSource.of(game.player.pawn, game)
    ally = DamageSource.of(make_ship("x_1", team=1), game)
    ties = [make_ship(f"tie_{i}", team=2) for i in range(3)]
    other = make_ship("bomber", team=2)
    for victim, killer in zip([*ties, other], [player, ally, player, player]):
        credit_hit(victim, killer)
        log.record(victim)

    tie_ids = [tie.id for tie in ties]
    assert log.count() == 4
    assert log.count(victim_ids=tie_ids) == 3
    assert log.count(victim_ids=tie_ids, by_player=True) == 2
    assert log.count(by_player=True) == 3


def test_player_summary_tallies_categories_and_friendly_fire(game):
    log = KillLog(game)
    player = DamageSource.of(game.player.pawn, game)
    isd = make_ship("isd", team=2, category="capital_ship")
    victims = [
        make_ship("tie_1", team=2),
        make_ship("tie_2", team=2),
        make_subsystem(isd),
        make_ship("blue_2", team=1),  # friendly fire
        make_ship("freighter", team=0),  # a neutral: a kill, not friendly fire
    ]
    for victim in victims:
        credit_hit(victim, player)
        log.record(victim)
    # An ally's kill does not count
    tie_3 = make_ship("tie_3", team=2)
    credit_hit(tie_3, DamageSource.of(make_ship("x_1", team=1), game))
    log.record(tie_3)

    assert log.player_summary() == {
        "kills": 5,
        "by_category": {"fighter": 4, "sub_system": 1},
        "friendly": 1,
    }

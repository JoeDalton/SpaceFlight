"""
Tests for the shipped levels' mission bodies, run end-to-end against the
fakes in mission_fakes.py. "Combat" (ships dying, a convoy or leader reaching
a waypoint, the player flying somewhere) is simulated by the test reaching
into the fake world directly.
"""

import numpy as np
import pytest
from mission_fakes import FakeGame, advance, depart_all, kill_all, live, patch_engine

from space_flight.game.kills import DamageSource
from space_flight.game.levels import LEVELS
from space_flight.game.levels import mission1_level as mission1
from space_flight.game.levels import mission2_level as mission2
from space_flight.game.levels import mission3_level as mission3
from space_flight.game.levels.dev_level import dev_mission
from space_flight.game.levels.mission3_level import mission3_mission
from space_flight.game.scenario import Mission
from space_flight.game.scenario.mission import LEVEL_END_DELAY_S


@pytest.fixture
def game():
    return FakeGame()


@pytest.fixture
def spawned(monkeypatch):
    return patch_engine(monkeypatch)


def start(game, body):
    mission = Mission(game)
    game.mission = mission
    mission.run(body)
    return mission


def objective_states(m):
    """Each objective's state, by its text."""
    return {objective.text: objective.state for objective in m.objectives}


def test_every_level_has_an_upfront_and_a_mission():
    for name, entry in LEVELS.items():
        assert callable(entry.upfront), name
        assert callable(entry.mission), name
        assert entry.description, name


# ---------------------------------------------------------------------------
# Dev
# ---------------------------------------------------------------------------


def test_dev_mission_spawns_the_frigate(game, spawned):
    m = start(game, dev_mission)
    advance(game, m, 3)
    assert len(live(game, spawned, "allied_frigate")) == 1


def test_dev_mission_launches_fighters_from_the_star_destroyer(game, spawned):
    """
    The dev mission stocks the star destroyer's hangar from the level's stock
    and launches TIE fighters at the frigate, then TIE bombers.
    """
    from space_flight.game.levels.dev_level import ENEMY_CAPITAL_SHIP_HANGAR_STOCK

    m = start(game, dev_mission)
    advance(game, m, 8)
    (isd,) = live(game, spawned, "enemy_isd")
    hangar = isd.hangars[0]
    assert set(hangar.stock) == set(ENEMY_CAPITAL_SHIP_HANGAR_STOCK)
    hangar.launch_pending()
    assert [bot.pawn_model for bot in hangar.launched] == ["tie-fighter"] * 3
    (frigate,) = live(game, spawned, "allied_frigate")
    assert all(
        bot.tactician.primary_target_ids == [frigate.id] for bot in hangar.launched
    )

    advance(game, m, 20)
    hangar.launch_pending()
    assert [bot.pawn_model for bot in hangar.launched[3:]] == ["tie-bomber"] * 6


# ---------------------------------------------------------------------------
# mission3
# ---------------------------------------------------------------------------


def test_mission3_victory(game, spawned):
    m = start(game, mission3_mission)

    # Transports at 1s, escort at 3s, first wave at 17s.
    advance(game, m, 19)
    assert len(live(game, spawned, "transports")) == 3
    assert len(live(game, spawned, "escort")) == 8
    first_wave = live(game, spawned, "first_wave")
    assert len(first_wave) == 5
    transport_ids = {p.id for p in live(game, spawned, "transports")}
    assert set(first_wave[0].parent.tactician.primary_target_ids) == transport_ids

    # Wiping the first wave brings the third wave ~3s later (well before the
    # 200s fallback); the second wave arrives on its own at 37s.
    kill_all(game, first_wave)
    advance(game, m, 20)  # t ~= 39s
    assert len(live(game, spawned, "third_wave")) == 8
    assert len(live(game, spawned, "second_wave")) == 5

    # Second wave gone + convoy past its last waypoint -> victory 3s later.
    kill_all(game, live(game, spawned, "second_wave"))
    for pawn in live(game, spawned, "transports"):
        pawn.parent.navigator.next_waypoint_idx = 9
    advance(game, m, 1)
    assert game.end_level_calls == []
    advance(game, m, 3 + LEVEL_END_DELAY_S)
    assert game.end_level_calls[-1][0] == "victory"
    assert game.objectives_at_end == {
        "Escort the convoy to the fleet": "complete",
        "Bonus: lose no transport": "complete",
        "Shoot down the bombers": "complete",
        "Clear the TIE-Fighters": "complete",
        "Stop the second bomber wave": "active",
    }


def test_mission3_objectives_count_the_waves_down(game, spawned):
    m = start(game, mission3_mission)
    advance(game, m, 19)
    kill_all(game, live(game, spawned, "first_wave")[:2])
    labels = [objective.label() for objective in m.objectives]
    assert "Shoot down the bombers (2/5)" in labels


def test_mission3_defeat(game, spawned):
    m = start(game, mission3_mission)
    advance(game, m, 4)  # transports and escort spawned
    kill_all(game, live(game, spawned, "transports"))
    advance(game, m, 1)
    assert any("All transports" in text for text, _ in game.hud.chatter)
    advance(game, m, 3 + LEVEL_END_DELAY_S)
    assert game.end_level_calls[-1] == ("defeat", "The convoy has been destroyed.")
    assert game.objectives_at_end["Escort the convoy to the fleet"] == "failed"
    assert game.objectives_at_end["Bonus: lose no transport"] == "failed"


def test_mission3_mourns_each_escort_pilot_by_name(game, spawned):
    m = start(game, mission3_mission)
    advance(game, m, 4)
    escort = live(game, spawned, "escort")

    kill_all(game, escort[:1])  # Red Leader
    advance(game, m, 0.1)
    assert game.hud.chatter[-1][0] == (
        "Red Two: " + mission3.ESCORT_LOSS_LINES[0].format(name="Red Leader")
    )

    kill_all(game, escort[3:4])  # Red Four
    advance(game, m, 0.1)
    assert game.hud.chatter[-1][0] == (
        "Red Two: " + mission3.ESCORT_LOSS_LINES[1].format(name="Red Four")
    )

    kill_all(game, live(game, spawned, "escort"))
    advance(game, m, 0.1)
    assert "all on you" in game.hud.chatter[-1][0]


def play_mission3_to_every_wave(game, m, spawned):
    """Up to every enemy wave flying (the third and fourth ~3s after the first
    is wiped, the second at 30s)."""
    advance(game, m, 19)
    kill_all(game, live(game, spawned, "first_wave"))
    advance(game, m, 20)


def test_mission3_wave_cleared_chatter_knows_what_is_left(game, spawned):
    """The fourth wave of TIE-Fighters downed while the second still flies."""
    m = start(game, mission3_mission)
    play_mission3_to_every_wave(game, m, spawned)

    kill_all(game, live(game, spawned, "fourth_wave"))
    advance(game, m, 0.1)
    speaker, line = mission3.FIGHTER_CLEAR_LINES["more_flying"]
    assert game.hud.chatter[-1][0] == f"{speaker}: {line}"

    kill_all(game, live(game, spawned, "second_wave"))
    advance(game, m, 0.1)
    speaker, line = mission3.FIGHTER_CLEAR_LINES["last"]
    assert game.hud.chatter[-1][0] == f"{speaker}: {line}"


def test_mission3_first_bombers_down_announce_no_all_clear(game, spawned):
    m = start(game, mission3_mission)
    advance(game, m, 19)
    kill_all(game, live(game, spawned, "first_wave"))
    advance(game, m, 0.1)
    speaker, line = mission3.BOMBER_CLEAR_LINES["more_to_come"]
    assert game.hud.chatter[-1][0] == f"{speaker}: {line}"


def test_mission3_every_wave_down_wins_before_the_convoy_arrives(game, spawned):
    m = start(game, mission3_mission)
    play_mission3_to_every_wave(game, m, spawned)
    for wave in ("second_wave", "third_wave", "fourth_wave"):
        kill_all(game, live(game, spawned, wave))
    advance(game, m, 0.1)

    assert set(objective_states(m).values()) == {"complete"}
    assert game.end_level_calls == []

    advance(game, m, mission3.ALL_CLEAR_VICTORY_DELAY_S + LEVEL_END_DELAY_S)
    assert game.end_level_calls == [
        (
            "victory",
            "Every enemy wave destroyed. The convoy is safe. Mission accomplished.",
        )
    ]


def test_mission3_cheers_when_every_wave_is_down(game, spawned):
    m = start(game, mission3_mission)
    advance(game, m, 19)
    kill_all(game, live(game, spawned, "first_wave"))
    advance(game, m, 20)  # the second wave at 37s, the third and fourth ~3s in
    for wave in ("second_wave", "third_wave"):
        kill_all(game, live(game, spawned, wave))
    advance(game, m, 0.1)
    kill_all(game, live(game, spawned, "fourth_wave"))
    advance(game, m, 0.1)

    spoken = [text for text, _ in game.hud.chatter]
    assert any("Our six is clear" in text for text in spoken)
    assert "every last one" in spoken[-1]


# ---------------------------------------------------------------------------
# Mission 1: Rookies
# ---------------------------------------------------------------------------


def reach_formation(game, m, spawned):
    """Play up to the formation spawning; return its live pawns."""
    advance(game, m, 1)
    game.player.pawn.position = np.array(mission1.WAYPOINT_1, dtype=float)
    advance(game, m, 5)  # the 3s intro wait, then 4 ships, one per frame
    return live(game, spawned, "blue")


def finish_circuit(game, m, spawned):
    """Catch up with the formation and fast-forward its circuit."""
    blue = reach_formation(game, m, spawned)
    game.player.pawn.position = blue[0].position.copy()
    advance(game, m, 1)
    blue[0].parent.navigator.next_waypoint_idx = len(mission1.CIRCUIT_WAYPOINTS)
    advance(game, m, 1)
    return blue


def test_mission1_waypoint_to_formation_handoff(game, spawned):
    m = start(game, mission1.mission1_mission)
    advance(game, m, 1)
    intro_route = game.player_waypoints
    assert intro_route.waypoints == [mission1.WAYPOINT_1]
    assert live(game, spawned, "blue") == []

    game.player.pawn.position = np.array(mission1.WAYPOINT_1, dtype=float)
    advance(game, m, 5)

    blue = live(game, spawned, "blue")
    assert len(blue) == 4
    # The leader spawns 1km ahead (+forward) and to the left (-right).
    expected = (
        np.array(mission1.WAYPOINT_1, dtype=float)
        + np.array([0.0, 1.0, 0.0]) * mission1.FORMATION_AHEAD_M
        - np.array([1.0, 0.0, 0.0]) * mission1.FORMATION_LEFT_M
    )
    assert np.allclose(blue[0].position, expected)
    assert intro_route.cleaned is True
    assert any("[R]" in text and "[,]" in text for text, _ in game.hud.hints)
    assert objective_states(m) == {
        "Reach the nav point": "complete",
        "Form up with Blue squadron": "active",
    }


def test_mission1_catch_up_deadline_defeat(game, spawned):
    m = start(game, mission1.mission1_mission)
    reach_formation(game, m, spawned)
    advance(game, m, mission1.CATCH_UP_DEADLINE_S + 2)
    assert game.end_level_calls[-1][0] == "defeat"
    assert "catch up" in game.end_level_calls[-1][1]
    assert game.objectives_at_end["Form up with Blue squadron"] == "failed"


def test_mission1_sustained_separation_defeat(game, spawned):
    m = start(game, mission1.mission1_mission)
    blue = reach_formation(game, m, spawned)
    game.player.pawn.position = blue[0].position.copy()
    advance(game, m, 1)
    assert game.end_level_calls == []

    game.player.pawn.position = blue[0].position + np.array(
        [mission1.FOLLOW_RADIUS_M * 5, 0.0, 0.0]
    )
    advance(game, m, mission1.SUSTAINED_SEPARATION_S + 1 + LEVEL_END_DELAY_S)
    assert game.end_level_calls[-1][0] == "defeat"
    assert "fell too far behind" in game.end_level_calls[-1][1]
    assert game.objectives_at_end["Fly the circuit with Blue squadron"] == "failed"


def test_mission1_any_formation_member_counts(game, spawned):
    """Staying close to a wingman that drifted away from the leader is enough."""
    m = start(game, mission1.mission1_mission)
    blue = reach_formation(game, m, spawned)
    leader, wingman = blue[0], blue[1]
    wingman.position = leader.position + np.array(
        [0.0, mission1.FOLLOW_RADIUS_M * 5, 0.0]
    )
    game.player.pawn.position = wingman.position.copy()
    advance(game, m, mission1.CATCH_UP_DEADLINE_S + mission1.SUSTAINED_SEPARATION_S)
    assert game.end_level_calls == []


def test_mission1_separation_rule_stops_once_the_race_starts(game, spawned):
    m = start(game, mission1.mission1_mission)
    finish_circuit(game, m, spawned)
    game.player.pawn.position = np.array([1e5, 0.0, 0.0])  # far from everyone
    advance(game, m, mission1.SUSTAINED_SEPARATION_S + 1)
    assert game.end_level_calls == []
    assert game.player_waypoints.waypoints == mission1.RACE_WAYPOINTS


def test_mission1_first_place_is_special(game, spawned):
    m = start(game, mission1.mission1_mission)
    blue = finish_circuit(game, m, spawned)
    finish = np.array(mission1.RACE_WAYPOINTS[-1], dtype=float)
    game.player.pawn.position = finish.copy()
    advance(game, m, 1)
    for pawn in blue:
        pawn.position = finish.copy()
    advance(game, m, 1)
    assert game.end_level_calls[-1] == (
        "victory",
        "First across the line! Outstanding flying, rookie!",
    )
    assert set(game.objectives_at_end.values()) == {"complete"}


def test_mission1_middle_place_is_a_plain_victory(game, spawned):
    m = start(game, mission1.mission1_mission)
    blue = finish_circuit(game, m, spawned)
    finish = np.array(mission1.RACE_WAYPOINTS[-1], dtype=float)
    blue[0].position = finish.copy()
    advance(game, m, 1)
    game.player.pawn.position = finish.copy()
    advance(game, m, 1)
    for pawn in blue[1:]:
        pawn.position = finish.copy()
    advance(game, m, 1)
    assert game.end_level_calls[-1][0] == "victory"
    assert "First" not in game.end_level_calls[-1][1]
    assert game.objectives_at_end["Race to the finish marker"] == "complete"
    assert game.objectives_at_end["Bonus: cross the line first"] == "failed"


def test_mission1_last_place_is_still_a_victory(game, spawned):
    """
    The race ends as soon as the player crosses the line, ranked by whoever
    already finished by then -- there is no waiting for stragglers, so
    finishing after every other racer is a plain victory, not a defeat.
    """
    m = start(game, mission1.mission1_mission)
    blue = finish_circuit(game, m, spawned)
    finish = np.array(mission1.RACE_WAYPOINTS[-1], dtype=float)
    for pawn in blue:
        pawn.position = finish.copy()
    advance(game, m, 1)
    game.player.pawn.position = finish.copy()
    advance(game, m, 1 + LEVEL_END_DELAY_S)
    assert game.end_level_calls[-1][0] == "victory"
    assert "First" not in game.end_level_calls[-1][1]


def test_mission1_race_timeout_is_defeat(game, spawned):
    m = start(game, mission1.mission1_mission)
    finish_circuit(game, m, spawned)
    # The player never reaches the finish line.
    advance(game, m, mission1.RACE_TIMEOUT_S + 1)
    assert game.end_level_calls[-1] == (
        "defeat",
        "You didn't reach the finish line in time. Mission failed.",
    )
    assert game.objectives_at_end["Race to the finish marker"] == "failed"


def test_mission1_race_starts_with_the_engine_power_hint(game, spawned):
    m = start(game, mission1.mission1_mission)
    finish_circuit(game, m, spawned)
    assert any("engines" in text for text, _ in game.hud.hints)


def test_mission1_race_banter_runs_while_racing(game, spawned):
    m = start(game, mission1.mission1_mission)
    finish_circuit(game, m, spawned)
    advance(game, m, sum(delay for delay, _, _ in mission1.RACE_CHATTER) + 1)
    spoken = [text for text, _ in game.hud.chatter]
    assert all(
        any(line in text for text in spoken) for _, _, line in mission1.RACE_CHATTER
    )


@pytest.mark.parametrize("player_leads", [True, False])
def test_mission1_comments_on_who_leads_the_race(game, spawned, player_leads):
    m = start(game, mission1.mission1_mission)
    blue = finish_circuit(game, m, spawned)
    if player_leads:
        game.player.pawn.position = np.array(mission1.RACE_WAYPOINTS[1], dtype=float)
    else:
        blue[2].parent.navigator.next_waypoint_idx = 2  # past race waypoint 1
    advance(game, m, 0.1)

    player_line, (speaker, line) = mission1.RACE_GATE_LINES[1]
    if player_leads:
        speaker, line = player_line
    else:
        speaker = mission1.BLUE_NAMES[2]
    assert any(text == f"{speaker}: {line}" for text, _ in game.hud.chatter)


# ---------------------------------------------------------------------------
# Mission 2: Smugglers
# ---------------------------------------------------------------------------

AHEAD_OF_PLAYER = np.array([0.0, 500.0, 0.0])


def scan_now(game, m, pawn):
    """Hold pawn ahead of the player, targeted, until its scan completes."""
    pawn.position = game.player.pawn.position + AHEAD_OF_PLAYER
    game.player.pawn.target = pawn
    advance(game, m, 16)
    game.player.pawn.target = None


def reach_the_reveal(game, m, spawned):
    """Play mission 2 up to the smuggler's reveal; return its pawn."""
    advance(game, m, mission2.INTRO_DELAY_S + 2 * mission2.CONVOY_INTERVAL_S + 1)
    for spec in mission2.CONVOY:
        scan_now(game, m, live(game, spawned, spec.name)[0])
    advance(game, m, 15)
    dorn = live(game, spawned, "Dorn")[0]
    scan_now(game, m, dorn)
    advance(game, m, 0.5)
    return dorn


def test_mission2_is_registered():
    assert LEVELS["Mission 2: Smugglers"].mission is mission2.mission2_mission
    assert "Mission 3: Escort" in LEVELS


def test_mission2_player_takes_point_when_ordered_to_scan(game, spawned):
    m = start(game, mission2.mission2_mission)
    advance(game, m, mission2.INTRO_DELAY_S + 5)
    assert any("take point" in text for text, _ in game.hud.chatter)
    blue = live(game, spawned, "blue")
    formation = blue[0].formation
    assert formation.ship_ids == [game.player.pawn.id, *(p.id for p in blue)]
    assert all(p.parent.navigator.waypoints == [] for p in blue)


def test_mission2_convoy_is_neutral_and_smuggler_waits_for_clear_scans(game, spawned):
    m = start(game, mission2.mission2_mission)
    advance(game, m, mission2.INTRO_DELAY_S + 2 * mission2.CONVOY_INTERVAL_S + 1)
    transports = [live(game, spawned, spec.name)[0] for spec in mission2.CONVOY]
    assert all(t.team == 0 for t in transports)
    assert len(live(game, spawned, "blue")) == 2

    for pawn in transports[:2]:
        scan_now(game, m, pawn)
    advance(game, m, 30)
    assert not live(game, spawned, "Dorn")

    scan_now(game, m, transports[2])
    assert all(t.scan.result == "clear" for t in transports)
    advance(game, m, 15)
    assert len(live(game, spawned, "Dorn")) == 1


def test_mission2_reveal_turns_the_smuggler_and_spawns_ties_behind(game, spawned):
    m = start(game, mission2.mission2_mission)
    game.player.pawn.orientation = np.array([0.0, 0.0, 0.0, 1.0])
    dorn = reach_the_reveal(game, m, spawned)

    assert dorn.scan.result == "contraband"
    assert dorn.team == 2
    ties = live(game, spawned, "tie")
    assert len(ties) == 4
    expected = game.player.pawn.position - game.player.pawn.forward * 1000
    assert np.allclose(ties[0].position, expected)
    tie_bots = [b for b in spawned if b.name.startswith("tie_")]
    assert all(list(b.ini_orientation) == [0.0, 0.0, 0.0, 1.0] for b in tie_bots)
    blue_ids = {p.id for p in live(game, spawned, "blue")}
    assert all(blue_ids <= set(b.tactician.primary_target_ids) for b in tie_bots)
    assert game.end_level_calls == []


def test_mission2_victory_without_losses(game, spawned):
    m = start(game, mission2.mission2_mission)
    dorn = reach_the_reveal(game, m, spawned)
    kill_all(game, [dorn, *live(game, spawned, "tie")])
    advance(game, m, mission2.VICTORY_DELAY_S + 1 + LEVEL_END_DELAY_S)
    assert len(game.end_level_calls) == 1
    outcome, text = game.end_level_calls[0]
    assert outcome == "victory" and "no losses" in text
    assert game.objectives_at_end == {
        "Stay with Blue Leader on patrol": "complete",
        "Scan the transports": "complete",
        "Hold fire on civilians": "complete",
        "Keep Blue flight alive": "complete",
        "Scan the straggler": "complete",
        "Stop the gun-runner": "complete",
        "Destroy the TIEs": "complete",
    }


def test_mission2_victory_with_one_ally_lost(game, spawned):
    m = start(game, mission2.mission2_mission)
    dorn = reach_the_reveal(game, m, spawned)
    kill_all(game, live(game, spawned, "blue")[:1])
    kill_all(game, [dorn, *live(game, spawned, "tie")])
    advance(game, m, mission2.VICTORY_DELAY_S + 1 + LEVEL_END_DELAY_S)
    assert len(game.end_level_calls) == 1
    outcome, text = game.end_level_calls[0]
    assert outcome == "victory" and "lost a pilot" in text


def test_mission2_defeat_when_blue_flight_is_wiped(game, spawned):
    m = start(game, mission2.mission2_mission)
    reach_the_reveal(game, m, spawned)
    kill_all(game, live(game, spawned, "blue"))
    advance(game, m, 1 + LEVEL_END_DELAY_S)
    assert game.end_level_calls == [("defeat", "Blue flight has been wiped out.")]
    # Failed in the tally, though its rule comes after the ending's
    assert game.objectives_at_end["Keep Blue flight alive"] == "failed"


def test_mission2_defeat_when_a_civilian_is_destroyed(game, spawned):
    m = start(game, mission2.mission2_mission)
    advance(game, m, mission2.INTRO_DELAY_S + 1)
    kill_all(game, live(game, spawned, "Aurek"))
    advance(game, m, 1 + LEVEL_END_DELAY_S)
    assert [c[0] for c in game.end_level_calls] == ["defeat"]
    assert "civilian" in game.end_level_calls[0][1]
    assert game.objectives_at_end["Hold fire on civilians"] == "failed"


def test_mission2_warns_when_a_civilian_is_hit(game, spawned):
    m = start(game, mission2.mission2_mission)
    advance(game, m, mission2.INTRO_DELAY_S + 1)
    live(game, spawned, "Aurek")[0].health -= 10
    advance(game, m, 0.1)
    assert any("cease fire" in text for text, _ in game.hud.chatter)
    assert game.end_level_calls == []


def test_mission2_defeat_when_an_unscanned_transport_exits(game, spawned):
    m = start(game, mission2.mission2_mission)
    advance(game, m, mission2.INTRO_DELAY_S + 1)
    live(game, spawned, "Aurek")[0].position = np.array(mission2.EXIT_GATE, float)
    advance(game, m, mission2.DEFEAT_DELAY_S + 1 + LEVEL_END_DELAY_S)
    assert game.end_level_calls == [
        ("defeat", "An unscanned transport slipped through the patrol.")
    ]
    assert game.objectives_at_end["Scan the transports"] == "failed"


def player_hits(game, pawn, damage=10.0):
    """The player's shot landing on pawn."""
    pawn.last_hit_by = DamageSource.of(game.player.pawn, game)
    pawn.health -= damage


def test_mission2_patrol_is_an_objective_until_contact(game, spawned):
    m = start(game, mission2.mission2_mission)
    advance(game, m, 17)
    assert objective_states(m) == {"Stay with Blue Leader on patrol": "active"}
    assert not any("patrol" in text for text, _ in game.hud.messages + game.hud.hints)

    advance(game, m, mission2.INTRO_DELAY_S - 17 + 0.1)
    assert objective_states(m)["Stay with Blue Leader on patrol"] == "complete"


def test_mission2_firing_again_after_the_warning_grounds_the_player(game, spawned):
    m = start(game, mission2.mission2_mission)
    advance(game, m, mission2.INTRO_DELAY_S + 1)
    aurek = live(game, spawned, "Aurek")[0]
    player_hits(game, aurek)
    advance(game, m, 0.1)
    assert any("cease fire" in text for text, _ in game.hud.chatter)

    # Shots still on their way when the order comes are forgiven...
    player_hits(game, aurek)
    advance(game, m, mission2.CEASE_FIRE_GRACE_S + 0.1)
    assert m.ending is None

    # ...but not a hit after that.
    player_hits(game, aurek)
    advance(game, m, 0.1 + LEVEL_END_DELAY_S)
    assert game.end_level_calls[-1][0] == "defeat"
    assert "kept firing on civilians" in game.end_level_calls[-1][1]
    assert game.objectives_at_end["Hold fire on civilians"] == "failed"


def test_mission2_someone_elses_hit_on_a_civilian_is_not_the_players(game, spawned):
    m = start(game, mission2.mission2_mission)
    advance(game, m, mission2.INTRO_DELAY_S + 1)
    aurek = live(game, spawned, "Aurek")[0]
    player_hits(game, aurek)
    advance(game, m, mission2.CEASE_FIRE_GRACE_S + 0.2)

    aurek.last_hit_by = DamageSource.of(live(game, spawned, "blue")[0], game)
    aurek.health -= 10
    advance(game, m, 1)

    assert m.ending is None


def test_mission2_reveal_hints_at_laser_power(game, spawned):
    m = start(game, mission2.mission2_mission)
    reach_the_reveal(game, m, spawned)
    assert any("lasers" in text for text, _ in game.hud.hints)


def test_mission2_scanned_transport_may_exit(game, spawned):
    m = start(game, mission2.mission2_mission)
    advance(game, m, mission2.INTRO_DELAY_S + 1)
    aurek = live(game, spawned, "Aurek")[0]
    scan_now(game, m, aurek)
    aurek.position = np.array(mission2.EXIT_GATE, float)
    advance(game, m, mission2.DEFEAT_DELAY_S + 1)
    assert game.end_level_calls == []


def test_mission2_defeat_when_the_smuggler_jumps_out(game, spawned):
    m = start(game, mission2.mission2_mission)
    dorn = reach_the_reveal(game, m, spawned)
    dorn.position = dorn.position + dorn.forward * mission2.ESCAPE_DISTANCE_M
    advance(game, m, 0.1)
    # At its jump point, it jumps out...
    assert dorn.parent.jump_outs == [None]
    assert game.end_level_calls == []
    # ...and only its departure loses the mission
    depart_all(game, [dorn])
    advance(game, m, mission2.DEFEAT_DELAY_S + 1 + LEVEL_END_DELAY_S)
    assert game.end_level_calls == [
        ("defeat", "The gun-runner escaped with its cargo.")
    ]
    assert game.objectives_at_end["Stop the gun-runner"] == "failed"


def test_mission2_killing_the_revealed_smuggler_is_not_a_civilian_loss(game, spawned):
    m = start(game, mission2.mission2_mission)
    dorn = reach_the_reveal(game, m, spawned)
    kill_all(game, [dorn])
    advance(game, m, 1)
    assert game.end_level_calls == []

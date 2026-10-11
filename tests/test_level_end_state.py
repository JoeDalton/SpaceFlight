"""
Unit tests for the level-end screen's stats lines (space_flight.menus.
level_end_state), and the stats label on the session app's real screen.
"""

import pytest

from space_flight.menus.level_end_state import LevelEndState, stats_lines


def make_stats(kills=0, by_category=None, friendly=0, objectives=(0, 0, 0)) -> dict:
    total, complete, failed = objectives
    return {
        "kills": kills,
        "by_category": by_category or {},
        "friendly": friendly,
        "objectives": {"total": total, "complete": complete, "failed": failed},
    }


@pytest.mark.parametrize(
    "stats, lines",
    [
        (None, []),
        (make_stats(), ["Kills: 0"]),
        (
            make_stats(5, {"fighter": 4, "sub_system": 1}),
            ["Kills: 5 (4 fighters, 1 subsystem)"],
        ),
        (
            make_stats(1, {"capital_ship": 1}, friendly=1),
            ["Kills: 1 (1 capital ship)", "Friendly fire: 1"],
        ),
        (make_stats(objectives=(4, 3, 0)), ["Kills: 0", "Objectives: 3/4"]),
        (
            make_stats(objectives=(4, 2, 1)),
            ["Kills: 0", "Objectives: 2/4, 1 failed"],
        ),
    ],
)
def test_stats_lines(stats, lines):
    assert stats_lines(stats) == lines


def test_screen_shows_the_stats(spaceflight_app):
    stats = make_stats(2, {"fighter": 2}, objectives=(2, 1, 0))
    screen = LevelEndState(spaceflight_app, outcome="victory", stats=stats)
    screen.enter()
    try:
        assert screen.stats_label["text"] == "Kills: 2 (2 fighters)\nObjectives: 1/2"
    finally:
        screen.exit()

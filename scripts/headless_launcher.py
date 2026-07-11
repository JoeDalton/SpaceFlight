"""
Manually run a level headlessly — no window, no audio device, no menus.

Meant as a smoke test / template for optimization loops (bot personality
tuning, navigator strategy search, ...) that drive many simulation runs
without ever opening a display. See ``scripts/launcher.py`` for the normal,
windowed entry point.

Usage:
    poetry run python scripts/headless_launcher.py --level Dev --max-steps 1000
"""

import argparse

from space_flight.headless.harness import DEFAULT_TIME_STEP, HeadlessHarness


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--level",
        default="Dev",
        help='Level to load (as in configuration["selected_level"]),'
        'e.g. "Dev", "Intro", "Race".',
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=10_000,
        help="Safety cap on simulation steps if the level never reaches an outcome.",
    )
    parser.add_argument(
        "--time-step",
        type=float,
        default=DEFAULT_TIME_STEP,
        help="Fixed dt (seconds) applied per simulation step.",
    )
    args = parser.parse_args()

    harness = HeadlessHarness(time_step=args.time_step)
    try:
        with harness.run_level(args.level, max_steps=args.max_steps) as flight_state:
            print(f"Outcome: {flight_state.outcome!r}")
            print(f"Game time: {flight_state.game_time.get_current_time():.2f}s")
            print(f"Player position: {flight_state.player.pawn.node.getPos()}")
    finally:
        harness.destroy()


if __name__ == "__main__":
    main()

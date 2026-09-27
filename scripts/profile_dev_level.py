"""
Profile the CPU cost of the "Dev" level's steady-state simulation loop under
a ~20-ship load, headlessly (no window, no audio device).

Steps the level through an unprofiled warm-up (until the mission's waves have
finished spawning), then profiles a further window of steps with cProfile so
the recorded stats reflect per-frame cost at full ship count rather than the
one-time spawn ramp-up.

Usage:
    poetry run python scripts/profile_dev_level.py
    poetry run python scripts/profile_dev_level.py --steps 900 --warmup-steps 200

View the result with: poetry run snakeviz <output>
"""

import argparse
import cProfile
import pstats
from pathlib import Path

from space_flight.headless.harness import DEFAULT_TIME_STEP, HeadlessHarness


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--level",
        default="Dev",
        help="Level to load, as in configuration['selected_level'].",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=900,
        help="Number of profiled steps (900 = 15 simulated seconds at 60 Hz).",
    )
    parser.add_argument(
        "--warmup-steps",
        type=int,
        default=200,
        help="Unprofiled steps run first, to clear the mission's start delay "
        "and wave spawn ramp-up before profiling begins.",
    )
    parser.add_argument(
        "--output",
        default="profiles/dev_level.prof",
        help="Path to write the cProfile stats file to.",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    harness = HeadlessHarness(time_step=DEFAULT_TIME_STEP)
    try:
        harness.app.configuration["selected_level"] = args.level
        harness.app.state_manager.push(
            harness.app.state_manager.GAME_STATE, headless=True
        )
        flight_state = harness.app.state_manager.get_current()

        for _ in range(args.warmup_steps):
            harness.app.taskMgr.step()

        profiler = cProfile.Profile()
        profiler.enable()
        for _ in range(args.steps):
            harness.app.taskMgr.step()
        profiler.disable()

        profiler.dump_stats(str(output_path))

        print(f"Warm-up steps: {args.warmup_steps}, profiled steps: {args.steps}")
        print(
            f"Live actors at end of profiled window: "
            f"{len(flight_state.interactions.actors_id_dict)}"
        )
        print(f"Profile written to {output_path}")
        print(f"View it with: poetry run snakeviz {output_path}")

        stats = pstats.Stats(profiler)
        stats.sort_stats("cumulative")
        stats.print_stats(30)

        harness.app.state_manager.pop()
    finally:
        harness.destroy()


if __name__ == "__main__":
    main()

"""
Profile the CPU cost of the "Dev" level's steady-state simulation loop under
a ~20-ship load, headlessly (no window, no audio device).

Runs a warm-up (until the mission's waves have spawned), then a timed window
without cProfile (median / p99 / max frame time, to spot periodic spikes),
then a cProfile window, so the stats reflect per-frame cost at full ship count
rather than the spawn ramp-up. See docs/source/performance.md.

Usage:
    poetry run python scripts/profile_dev_level.py
    poetry run python scripts/profile_dev_level.py --steps 900 --warmup-steps 200

View the result with: poetry run snakeviz <output>
"""

import argparse
import cProfile
import pstats
import time
from pathlib import Path

import numpy as np

from space_flight.headless.harness import DEFAULT_TIME_STEP, HeadlessHarness


def main():
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
        "--timing-steps",
        type=int,
        default=900,
        help="Steps timed one by one without the profiler, after the warm-up, "
        "to report median / p99 / max frame time.",
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

        frame_times_ms = np.empty(args.timing_steps)
        for k in range(args.timing_steps):
            start = time.perf_counter()
            harness.app.taskMgr.step()
            frame_times_ms[k] = (time.perf_counter() - start) * 1000.0

        profiler = cProfile.Profile()
        profiler.enable()
        for _ in range(args.steps):
            harness.app.taskMgr.step()
        profiler.disable()

        profiler.dump_stats(str(output_path))

        print(
            f"Warm-up steps: {args.warmup_steps}, timed steps: {args.timing_steps}, "
            f"profiled steps: {args.steps}"
        )
        if args.timing_steps:
            print(
                "Frame time (ms, no profiler): "
                f"median {np.median(frame_times_ms):.2f}, "
                f"p99 {np.percentile(frame_times_ms, 99):.2f}, "
                f"max {frame_times_ms.max():.2f}"
            )
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

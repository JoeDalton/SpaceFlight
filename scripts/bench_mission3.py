"""
Benchmark a level's rendered frames (Mission 3 by default): the real game,
drawn, in an offscreen buffer at a fixed size and render scale 1.0, with no
menus, no input and no wait for the jump key.

It warms up until the level's waves have spawned and the world has finished
loading around the player, then times frames one by one, each waiting for the
GPU (a one-pixel read-back): CPU and GPU in series, so a difference between
two runs is a difference in work. See docs/source/performance.md.

Usage:
    python scripts/bench_mission3.py [--pose still|fly] [--frames 600]
        [--warmup 45] [--size "2560 1440"] [--level "Mission 3: Escort"]
        [--toggle mirror|shadows|model_shader|cirrus ...]
        [--world SECTION.KNOB=VALUE ...] [--profile [FILE]] [--pstats]
        [--prc LINE ...] [--shot FILE]

    --pose      still: the player stays where it spawns; fly: it flies on at
                a fixed throttle
    --toggle    turn a feature off, to measure what it costs: the rear-view
                mirror, the ships' shadows, their model shader, the cirrus
    --world     a WorldBuilder knob over the saved preset, as the graphics
                settings store it (e.g. shadows.object_shadows=false)
    --profile   then profile as many frames with cProfile (stats to FILE,
                default profiles/mission3.prof, top 30 printed)
    --pstats    connect to a running PStats server (pstats, or text-stats
                for a text summary), the GPU's timings included
    --prc       a Panda3D config line over the game's (e.g. "transform-cache
                false")
    --shot      save a screenshot of the last frame

Run each variant at least twice, interleaved, with the GPU in its performance
state (nvidia-smi: P0): two runs of the same tree differ by 0.3-0.5 ms.
"""

from __future__ import annotations

import argparse
import cProfile
import json
import pstats
import statistics
import time
from dataclasses import replace
from pathlib import Path

import yaml
from panda3d.core import Filename, loadPrcFileData

#: Seconds the world may take to finish loading after the warm-up
SETTLE_TIMEOUT_S = 30.0
#: Frames in a row with nothing loading that count as settled
SETTLED_FRAMES = 10
#: A frame slower than this is listed as a spike, milliseconds
SPIKE_MS = 100.0
#: The player's throttle in the "fly" pose
FLY_THROTTLE = 0.6

TOGGLES = ("mirror", "shadows", "model_shader", "cirrus")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--level", default="Mission 3: Escort")
    parser.add_argument("--pose", choices=("still", "fly"), default="still")
    parser.add_argument("--frames", type=int, default=600)
    parser.add_argument("--warmup", type=float, default=45.0, help="seconds")
    parser.add_argument("--size", default="2560 1440")
    parser.add_argument("--toggle", action="append", default=[], choices=TOGGLES)
    parser.add_argument("--world", action="append", default=[])
    parser.add_argument(
        "--profile", nargs="?", const="profiles/mission3.prof", default=None
    )
    parser.add_argument("--pstats", action="store_true")
    parser.add_argument("--prc", action="append", default=[])
    parser.add_argument("--shot", default=None)
    return parser.parse_args()


def world_overrides(pairs: list[str]) -> dict:
    """:return: {section: {knob: value}} from SECTION.KNOB=VALUE pairs"""
    overrides: dict = {}
    for pair in pairs:
        key, _, value = pair.partition("=")
        section, _, knob = key.partition(".")
        overrides.setdefault(section, {})[knob] = yaml.safe_load(value)
    return overrides


def apply_toggles(toggles: list[str]) -> None:
    """Turn features off before the level is built (the mirror is turned off
    once the player exists, see turn_mirror_off)."""
    from space_flight.scenes.scenes import Scene, SceneEarthlike

    if "shadows" in toggles:
        Scene.MODELS_CAST_SHADOWS = False
    if "model_shader" in toggles:
        Scene.MODELS_USE_WORLD_SHADER = False
    if "cirrus" in toggles:
        SceneEarthlike.CLOUDS = replace(SceneEarthlike.CLOUDS, cirrus=None)


def turn_mirror_off(flight) -> None:
    mirror = getattr(flight.player, "rear_view_mirror", None)
    if mirror is not None and mirror.is_mirror_visible:
        mirror.toggle_mirror()


def loading(flight) -> bool:
    """:return: whether the scene's world is still loading around the player"""
    world = getattr(flight.scene, "world", None)
    return world is not None and bool(world.loading)


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]


def main():
    args = parse_args()
    prc = [
        "window-type offscreen",
        f"win-size {args.size}",
        "audio-library-name null",
        "sync-video false",
    ]
    if args.pstats:
        prc += ["want-pstats 1", "pstats-gpu-timing 1"]
    prc += args.prc
    loadPrcFileData("", "\n".join(prc))

    import space_flight.game.flight_state as flight_state
    from space_flight.global_architecture.simulator import (
        SpaceFlightSimulator,
        StateManager,
    )

    flight_state.WAIT_FOR_JUMP_KEY = False
    apply_toggles(args.toggle)
    app = SpaceFlightSimulator(interactive=False)
    config = app.graphics_settings.config
    config["render"]["scale"] = 1.0
    config["antialiasing"].update(msaa=0, fxaa=False)
    world = dict(config.get("world") or {})
    overrides = dict(world.get("overrides") or {})
    for section, knobs in world_overrides(args.world).items():
        overrides[section] = {**overrides.get(section, {}), **knobs}
    config["world"] = {**world, "overrides": overrides}

    app.configuration["selected_level"] = args.level
    app.state_manager.push(StateManager.GAME_STATE)
    # The flight state, under the hyperspace overlay it pushes while it loads
    flight = next(
        state
        for state in app.state_manager.stack
        if isinstance(state, flight_state.FlightState)
    )

    # Warm up: the waves spawn, then the world settles around the player
    start = time.perf_counter()
    while time.perf_counter() - start < args.warmup:
        app.taskMgr.step()
    if "mirror" in args.toggle:
        turn_mirror_off(flight)
    if args.pose == "fly":
        flight.player.throttle = FLY_THROTTLE
    # The read-back region first: its first read-back sets it up (a frame
    # of about a second, not the game's)
    win = app.win
    probe = win.make_display_region(0, 1 / win.get_x_size(), 0, 1 / win.get_y_size())
    probe.get_screenshot()
    quiet, settle_start = 0, time.perf_counter()
    while quiet < SETTLED_FRAMES and time.perf_counter() - settle_start < (
        SETTLE_TIMEOUT_S
    ):
        app.taskMgr.step()
        quiet = 0 if loading(flight) else quiet + 1
    settled = quiet >= SETTLED_FRAMES

    times, spikes = [], []
    actors = flight.interactions.actors_id_dict
    for index in range(args.frames):
        before = len(actors)
        frame_start = time.perf_counter()
        app.taskMgr.step()
        probe.get_screenshot()  # waits for the GPU
        elapsed = (time.perf_counter() - frame_start) * 1e3
        times.append(elapsed)
        if elapsed > SPIKE_MS:
            spikes.append((index, round(elapsed, 1), len(actors) - before))

    if args.shot:
        win.save_screenshot(Filename.from_os_specific(args.shot))
    ships = len(flight.interactions.actors_id_dict)
    scene_world = getattr(flight.scene, "world", None)
    tracked = len(scene_world.tracked.nodes) if scene_world is not None else 0
    summary = {
        "level": args.level,
        "pose": args.pose,
        "toggles": args.toggle,
        "world": args.world,
        "size": args.size,
        "settled": settled,
        "actors": ships,
        "tracked": tracked,
        "frames": len(times),
        "mean_ms": round(statistics.fmean(times), 2),
        "median_ms": round(statistics.median(times), 2),
        "p95_ms": round(percentile(times, 0.95), 2),
        "p99_ms": round(percentile(times, 0.99), 2),
        "max_ms": round(max(times), 2),
        # (frame, ms, actors spawned that frame) of the frames over SPIKE_MS
        "spikes": spikes,
    }
    print("BENCH " + json.dumps(summary), flush=True)

    if args.profile:
        output = Path(args.profile)
        output.parent.mkdir(parents=True, exist_ok=True)
        profiler = cProfile.Profile()
        profiler.enable()
        for _ in range(args.frames):
            app.taskMgr.step()
            probe.get_screenshot()
        profiler.disable()
        profiler.dump_stats(output)
        stats = pstats.Stats(profiler)
        stats.sort_stats("tottime").print_stats(30)
        stats.sort_stats("cumulative").print_stats(30)


if __name__ == "__main__":
    main()

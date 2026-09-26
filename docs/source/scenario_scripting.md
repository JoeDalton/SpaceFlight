# Scenario scripting

A level's scripted events — when enemy waves arrive, what they attack, mission
objectives — are written directly in Python, using the **Mission API**
(`space_flight.game.scenario.mission`). Wave *data* (sizes, ship models, spawn
points, ...) stays declarative, in a YAML file next to the level.

Each level's `.py` file points at its own sibling `.yaml`, e.g.
[`intro_level.py`](../../src/space_flight/game/levels/intro_level.py) /
[`intro_level.yaml`](../../src/space_flight/game/levels/intro_level.yaml) for
the intro level.

> A legacy YAML `triggers:` DSL still exists in the engine (see
> [Legacy: the YAML trigger DSL](#legacy-the-yaml-trigger-dsl), below) and
> remains fully supported by `loader.py`, but the three shipped levels
> (Dev, Intro, Mission 1: Rookies) are now all written with the Mission API, which is the
> primary way to author a mission going forward.

## Mental model

The engine underneath is unchanged and still built on three ideas:

- **Trigger** — a rule: *when* a condition becomes true, run an *action*.
- **Condition** — a question answered every frame: "has 50 s passed?", "is the
  first wave wiped out?". Conditions compose.
- **Action** — something that happens: spawn a wave, show a HUD message.

What changes with the Mission API is how you *write* the mission: instead of a
YAML list of `when`/`then` rules, you write a plain Python generator function
— the **mission body** — that reads top to bottom like a script, using
`yield from` to wait for time or conditions to pass. Rules that must hold no
matter where the mission body currently is (e.g. "defeat if all transports
die, whenever that happens") are registered separately as **reactive rules**.

## A worked example

> An all-features reference example exercising every feature described on
> this page in one file — the Mission API
> ([`all_features_example.py`](examples/all_features_example.py) /
> [`.yaml`](examples/all_features_example.yaml)) and, separately, the legacy
> DSL ([`all_features_example_trigger_dsl.yaml`](examples/all_features_example_trigger_dsl.yaml))
> — is run end-to-end by
> [`tests/test_all_features_example.py`](../../tests/test_all_features_example.py).
> It is not a shipped level; copy its *patterns*, not its story, into a real
> level.

This mirrors the intro level's actual mission (trimmed):

```python
from space_flight.game.scenario import Scenario
from space_flight.game.scenario.conditions import Delay, all_destroyed, fired
from space_flight.game.scenario.loader import load_waves
from space_flight.game.scenario.mission import Mission


def intro_mission(m: Mission):
    # --- reactive rules, live for the whole mission -------------------------
    def _spawn_third_wave(game):
        m.hud("Enemy reinforcements detected!")
        m.spawn(m.waves["third_wave"])

    m.on(
        Delay(all_destroyed("first_wave"), seconds=3),
        _spawn_third_wave,
        name="third_wave",
    )
    m.on(
        all_destroyed("transports"),
        lambda game: m.defeat("The convoy has been destroyed."),
        name="all_transports_destroyed",
    )

    # --- the sequential part -------------------------------------------------
    yield from m.wait(0.1)
    transports = m.spawn(m.waves["transports"])

    yield from m.wait(0.9)  # total: 1.0s
    escort = m.spawn(m.waves["escort"])
    m.speech("Red squadron standing by.", speaker="Red Leader")

    yield from m.wait(9)  # total: 10s
    m.hud("First wave")
    m.spawn(m.waves["first_wave"], target=transports)


def build_intro_level(game):
    ...
    game.scenario = Scenario()
    mission = Mission(game)
    mission.waves = load_waves(Path(__file__).with_suffix(".yaml"))
    game.scenario.schedule(intro_mission(mission))
    yield "scenario"
```

Wave data (`m.waves["transports"]`, etc.) is loaded with
[`load_waves`](../../src/space_flight/game/scenario/loader.py), which reads
just the `waves:` section of the level's YAML file — see
[Wave data](#wave-data), below, for its format (unchanged from before).

## Mission

A [`Mission`](../../src/space_flight/game/scenario/mission.py) wraps a
`Scenario` (created directly, with no `triggers:` to load) and the
`FlightState`. One `Mission` per level; its mission body is scheduled as a job
on the scenario (`game.scenario.schedule(mission_body(mission))`), so it is
advanced one step per frame exactly like the wave-spawning jobs underneath it.

### Spawning: `Mission.spawn`

```python
handle = m.spawn(wave_cfg, *, target=None, join=None)
```

- `wave_cfg` is a wave dict — the same shape as a YAML `waves:` entry (see
  [Wave data](#wave-data)) — validated immediately: a missing required key or
  an unknown key raises a `ValueError` naming the wave id and the key, rather
  than failing confusingly mid-spawn.
- `target=` a `WaveHandle` (or a bare group name) makes this wave's ships
  attack it, overriding any `target` already in `wave_cfg`.
- `join=` an existing, live `Formation` (e.g. `other_handle.formation`) makes
  this wave's ships attach to it — continuing from its next free slot —
  instead of creating a new formation, even if `wave_cfg` declares one of its
  own. Handy for reinforcements joining an escort already in flight.
- Returns a [`WaveHandle`](#wavehandle) — a handle to the (spawning) wave, one
  ship per frame exactly as before.

A wave's `ship_model` can also be a list of `{ship_model, count}` entries for a
mixed-composition wave (e.g. a strike group of fighters escorted by a couple
of bombers); `size` is then optional (inferred as the sum of the counts).

### `WaveHandle`

Everything reads live state from the scenario, so a handle stays valid for the
wave's whole lifetime:

| Member | Type | Meaning |
|---|---|---|
| `.alive` | `bool` | at least one member is currently alive |
| `.all_destroyed` | `bool` | spawned and now has no live members |
| `.any_destroyed` | `bool` | spawned and has lost at least one member (stays true after a total wipe too) |
| `.formation` | `Formation \| None` | the wave's live formation, if it has one |
| `.all_destroyed_cond()` | `Condition` | same as `.all_destroyed`, as a condition callable — use with `wait_until` / `on` |
| `.any_destroyed_cond()` | `Condition` | same as `.any_destroyed`, as a condition callable |
| `.alive_cond()` | `Condition` | same as `.alive`, as a condition callable |
| `.set_targets(other)` | method | every live member attacks every live member of `other` (a `WaveHandle` or group name) |
| `.set_team(team)` | method | reassigns every live member's team, correctly cascading a capital ship's sub-systems, shield, and mounted turrets/tractor beams |
| `.set_waypoints(points, loop=True)` | method | gives every live member a new patrol/route path |

### Sequencing: `wait` / `wait_until` / `wait_any` / `wait_all`

`yield from` one of these inside a mission body to pause the sequence:

```python
yield from m.wait(10)                      # 10 game-seconds
yield from m.wait_until(wave.all_destroyed_cond())
yield from m.wait_until(30)                # bare number == wait(30)
yield from m.wait_any(cond_a, cond_b)      # either condition
yield from m.wait_all(cond_a, cond_b)      # both conditions
```

### Reactive rules: `Mission.on`

```python
m.on(condition, action, once=True, name=None)
```

Registers an ordinary `Trigger` on the scenario (checked every frame,
independently of wherever the mission body's own sequence currently is). Use
this for a rule like "defeat if all transports die" that must hold throughout,
as opposed to something the mission body itself sequentially waits on.
`condition` and `action` are the same callables described below (any function
from [`conditions.py`](../../src/space_flight/game/scenario/conditions.py) or
your own `condition(game) -> bool` / `action(game) -> None`). `name` lets a
later condition depend on this rule having fired (`conditions.fired(name)`),
exactly as in the legacy DSL.

### Thin action wrappers

`m.hud(text, display_time_s=2.5)`, `m.speech(text, speaker=None,
display_time_s=4.0)`, `m.player_waypoints(cfg)`, `m.end_level(outcome,
text="")`, `m.victory(text="")`, `m.defeat(text="", delay=0)` — each a thin
wrapper over the matching function in
[`actions.py`](../../src/space_flight/game/scenario/actions.py). `m.defeat`'s
`delay` schedules the ending via the game's delayed-method manager instead of
ending immediately — useful when calling it from a reactive `m.on` action,
where there is no generator to `yield from` a `wait` in.

## Wave data

Unchanged from before: a wave dict describes a group of bots, keyed by its
group id in YAML (or given as `cfg["id"]` directly in Python):

```yaml
waves:
  first_wave:
    size: 5                       # number of ships
    ship_model: tie-bomber        # pawn model
    bot_type: fighter             # fighter | capital_ship (default: fighter)
    team: 2                       # default: 2
    spawn_point: [300, 6000, 500] # world position of the formation leader
    spawn_orientation: [0, 0, 0, 1]  # quaternion (w, x, y, z); this is the default
    formation: { scale_m: 30, shape: arrowhead }  # arrowhead | diamond | around_diamond
    waypoints:                    # optional patrol path
      - [300, 0, 500]
      - [300, -6000, 500]
    loop: true                    # loop the waypoints (default: true)
    target: transports            # group name to attack (optional)
    hud_text: "Enemy ships incoming!"  # shown when the wave begins (optional)
    hud_time_s: 2.5               # how long hud_text shows
    allow_respawn: false          # see "Spawning once", below
    record: false                 # record each bot via game.record
```

Only `size` (or a mixed `ship_model` list), `ship_model`, and `spawn_point` are
required (`id` is implicit — the YAML key, or the `id` key when spawning from
Python directly).

`spawn_orientation` is handed straight to Panda3D's `Quat`, so its components
are in (w, x, y, z) order. The default `[0, 0, 0, 1]` is therefore **not** the
identity but a 180° turn about z.

`target` is resolved as each ship spawns: the ship is aimed at whichever
members of the target group are alive at that moment, so that group must
already exist (or pass `target=` to `Mission.spawn` instead, which is
resolved the same way).

Turrets and tractor beams are not waves: they are spawned from their host
capital ship's config (see [docs/subsystems.md](subsystems.md)).

### Formation spawning

When a wave declares a `formation` (or is spawned with `join=` an existing
one), ships spawn **in formation**: the leader at `spawn_point` (or the
formation's next free slot for a joining wave), each wingman at its slot
offset from there. Ships beyond the formation's capacity (e.g. `size: 12` in
an 8-slot diamond) fall back to a centred line. A wave with no formation (and
no `join=`) spawns entirely in a centred line.

### Spawning is spread across frames

A wave spawns **one ship per frame**, so a large wave never freezes the
simulation on one long loading frame. There is nothing to configure — it is how
every wave spawns.

### Spawning once

A wave id is an *identity group*: by default it spawns **at most once**, even if
`Mission.spawn` (or the legacy `spawn` action) is called on it twice. A second
attempt is skipped with a warning. Set `allow_respawn: true` for the rare case
where re-spawning the same composition into the same group is intended.

## Conditions

Conditions are unchanged, and still live in
[`conditions.py`](../../src/space_flight/game/scenario/conditions.py) — the
Mission API just calls them directly instead of the YAML loader building them
from a `when:` node:

| Condition | Signature | True when |
|---|---|---|
| `after_seconds` | `after_seconds(seconds)` | the game clock passes that time |
| `all_destroyed` | `all_destroyed(group)` | the group has spawned **and** all members are dead |
| `any_destroyed` | `any_destroyed(group)` | the group has spawned and at least one member has died (stays true after a total wipe too) |
| `any_alive` | `any_alive(group)` | at least one member of the group is alive |
| `reached_waypoint` | `reached_waypoint(group, index)` | any live member of `group` has reached waypoint `index` (0-based; its navigator's next-waypoint index is > `index`) |
| `near` | `near(who, point, radius)` | `who` is within `radius` of `point` (`who` is `"player"` or a group; for a group, any live member) |
| `near_actor` | `near_actor(who_a, who_b, radius)` | the nearest pair between `who_a`'s and `who_b`'s live members is within `radius` — the live-actor equivalent of `near`, for two *moving* groups (e.g. "is the player still close to the escort leader?") instead of a group and a fixed point |
| `fired` | `fired(trigger_name)` | the named trigger (from `Mission.on(..., name=...)` or the legacy DSL) has already fired |

```python
after_seconds(50)
all_destroyed("first_wave")
reached_waypoint("transports", 5)
near("player", [0, 2000, 500], radius=350)
near_actor("player", "escort_leader", radius=200)
fired("blockade_past")
```

`all_destroyed` is deliberately **false before the group has ever spawned**, so
a chained event cannot fire against a wave that does not exist yet.

> `reached_waypoint` reads the navigator's waypoint index, which resets to 0 at
> the end of each lap of a looping patrol and after the last waypoint of a
> non-looping path — so it is unambiguous only on the first pass. `index` is
> 0-based: `index=0` means "reached the first waypoint", and it is only true
> from the moment that waypoint is actually reached (not from mission start).

### Combinators

```python
Delay(inner, seconds)      # `seconds` after `inner` first becomes true
Sustained(inner, seconds)  # `inner` has held true for an UNBROKEN `seconds`
Not(inner)                 # `inner` is false
AllOf(*conds)              # every sub-condition is true
AnyOf(*conds)              # any sub-condition is true
```

`Delay` is what expresses "X, then wait, then…". It **latches**: once `inner`
becomes true the timer is armed and keeps running even if `inner` flickers
back to false.

`Sustained` is `Delay`'s mirror image: it **resets** the moment `inner` goes
false, instead of latching. Use it for "further than 200m for 10 *consecutive*
seconds" rather than "3 seconds after first going out of range" (which is what
`Delay` would give you):

```python
# defeat if the player drifts more than 200m from the escort leader for a
# full, unbroken 10 seconds -- a momentary dip back inside 200m resets the timer
Sustained(Not(near_actor("player", "escort_leader", 200)), seconds=10)
```

```python
# 3 seconds after the first wave is wiped out
Delay(all_destroyed("first_wave"), seconds=3)

# 3 seconds after the `blockade_past` trigger fired
Delay(fired("blockade_past"), seconds=3)

# convoy reached waypoint 5 AND the second wave is gone
AllOf(reached_waypoint("transports", 5), all_destroyed("second_wave"))
```

## Groups

A **group** is a named set of actors. Two kinds:

- **Identity groups** — a specific cohort. Every wave is one (its id is the
  group name). A group built directly can still be registered by name:

  ```python
  game.scenario.register(name="transports", bots=transport_bots)
  ```

- **Query groups** — derived live from a predicate (e.g. "all team-2 ships"),
  registered with `register_query`; no membership is stored.

Names are the only thing that crosses between wave data and conditions/rules:
a wave's YAML key is what a `WaveHandle`'s `.name`, `target=`, or a bare
`all_destroyed("that_name")` refers to. Dead members drop out of every query
automatically.

## Patterns and pitfalls

### One wave, one spawn call

The one-shot guard lives on the **wave id**, not on how many times you call
`spawn`. Two `m.on` rules (or a rule and the sequential body) that both
`m.spawn` the same wave id would each attempt it once → the second is skipped
with a warning (see [Spawning once](#spawning-once)), but the clean fix is to
have only one place ever spawn a given wave id.

If a wave should arrive via either of two conditions, use **one** rule with
`AnyOf`:

```python
# third wave arrives at 200s OR 3s after the first wave is wiped — once
def _spawn_third_wave(game):
    m.hud("Reinforcements detected!")
    m.spawn(m.waves["third_wave"])

m.on(
    AnyOf(after_seconds(200), Delay(all_destroyed("first_wave"), seconds=3)),
    _spawn_third_wave,
    name="third_wave",
)
```

### Sequential vs. reactive

Put a rule in the sequential mission body (`yield from m.wait...`) when it is
strictly ordered relative to the rest of the mission ("after the first wave
arrives, wait for it to die, then bring in the second"). Register it with
`m.on` instead when it must hold regardless of where the sequence currently is
("if all transports die, defeat — whenever that happens, even while the body
is off waiting on something else entirely").

### Chaining events

Because a condition can reference a group, events chain naturally: an action
spawns `first_wave`; a reactive rule watches `all_destroyed("first_wave")` to
launch reinforcements; another watches the convoy's progress for a mission
objective. Keep each rule independent and let the conditions order them.

## Extending the vocabulary

New conditions and actions are still small Python factories:

- a **condition** is any callable `condition(game) -> bool` — see
  [`conditions.py`](../../src/space_flight/game/scenario/conditions.py);
- an **action** is any callable `action(game) -> None` — see
  [`actions.py`](../../src/space_flight/game/scenario/actions.py).

With the Mission API these need no separate wiring step: just call them
directly (`m.on(my_condition(...), my_action(...))`) or write a plain
`lambda game: ...` inline. Resist adding a new condition/action factory before
you have a couple of real uses for it.

## Legacy: the YAML trigger DSL

The engine still supports the original, fully-declarative YAML DSL —
[`loader.py`](../../src/space_flight/game/scenario/loader.py)'s
`load_scenario` turns a `triggers:` section into `Trigger` objects with no
Python beyond the level's build function. It remains handy for a level whose
whole mission is a handful of independent, purely time/condition-driven rules
with nothing sequential about them:

```yaml
waves:
  first_wave:
    size: 5
    ship_model: tie-bomber
    spawn_point: [300, 6000, 500]

triggers:
  - name: first_wave            # optional; used in logs and by `fired`
    when: { after_seconds: 50 } # a condition
    then: { spawn: first_wave } # an action
    once: true                  # optional; false runs the action every
                                 # frame the condition holds
```

A `when` or `then` node is a **single-key mapping**: the key chooses the
condition/action (`after_seconds`, `all_destroyed`, `any_destroyed`,
`any_alive`, `reached_waypoint`, `near`, `fired`, `delay`, `all_of`, `any_of`
for conditions; `spawn`, `hud_text`, `speech`, `player_waypoints`, `end_level`,
`all` for actions — the same vocabulary described above), the value is its
argument. See the git history of this file for the DSL's full former
documentation and worked examples if you need them; none of the three shipped
levels use it any more, but `loader.py` and its tests are unaffected.

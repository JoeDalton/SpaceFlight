# Mission scripting

A level's scripted events — when enemy waves arrive, what they attack, the
objectives and how the level ends — are written in plain Python, in the
level's own module under
[`game/levels/`](https://github.com/JoeDalton/SpaceFlight/tree/main/src/space_flight/game/levels/), using
[`game/scenario/`](https://github.com/JoeDalton/SpaceFlight/tree/main/src/space_flight/game/scenario/).

> [`all_features_example.py`](examples/all_features_example.py) exercises
> the features on this page in one file (all but scanning, `damaged`,
> `follow`, `orientation=` and `m.schedule`), and is run end-to-end by
> [`tests/test_all_features_example.py`](../../tests/test_all_features_example.py).
> It is not a shipped level: copy its patterns, not its story.

## Mental model

- A **mission body** is a generator function taking the `Mission`. It reads
  top to bottom like a script, and `yield from`s the mission's waits to let
  time pass.
- A **reactive rule** (`m.on(condition, action)`) holds wherever the body
  currently is: "defeat if all transports die — whenever that happens".
- A **condition** is any zero-argument callable returning a bool, checked
  once per frame. An **action** is a zero-argument callable, usually a
  lambda calling the mission's action methods.
- A **wave** is a group of bots: declared as a `WaveSpec` constant, spawned
  through a `WaveHandle` that tracks its members.

Each frame, the mission first fires its due rules, then advances the body
and every other job (spawning waves, scans, `m.schedule`d generators) by one
step.

## A level, end to end

Trimmed from [`mission3_level.py`](../../src/space_flight/game/levels/mission3_level.py):

```python
TRANSPORTS = WaveSpec(
    name="transports",
    ship_model="cr-90",
    size=3,
    bot_type="major_ship",
    team=1,
    spawn_point=[0, -2000, 200],
    formation="arrowhead",
    formation_scale_m=150,
    waypoints=[[0, 0, 200], [0, 3000, 200], [7000, 3000, 200]],
)
FIRST_WAVE = WaveSpec(name="first_wave", ship_model="tie-bomber", size=5, ...)
THIRD_WAVE = WaveSpec(name="third_wave", ship_model="tie-bomber", size=8, ...)


def build_mission3_upfront(game):
    # The player, then the scene's up-front objects (game/levels/common.py)
    build_upfront(
        game,
        scene_name="earthlike_planet",
        player_ship_type="a-wing",
        player_position=[0, -2600, 250],
    )


def mission3_mission(m: Mission) -> Iterator[None]:
    # Handles first, so rules can refer to waves that haven't spawned yet.
    transports = m.wave(TRANSPORTS)
    first_wave = m.wave(FIRST_WAVE)
    third_wave = m.wave(THIRD_WAVE)

    # Reactive rules, live for the whole mission.
    def spawn_third_wave():
        m.hud("Enemy reinforcements detected!")
        third_wave.spawn(target=transports)

    m.on(any_of(m.after(200), m.delay(first_wave.all_destroyed, 3)), spawn_third_wave)
    m.on(
        m.delay(transports.all_destroyed, 3),
        lambda: m.defeat("The convoy has been destroyed."),
    )

    # The sequential part.
    yield from m.wait(0.1)
    transports.spawn()
    yield from m.wait(10)
    m.hud("First wave")
    first_wave.spawn(target=transports)
```

The level is then registered in
[`game/levels/__init__.py`](../../src/space_flight/game/levels/__init__.py):

```python
"Mission 3: Escort": LevelEntry(
    upfront=build_mission3_upfront,
    mission=mission3_mission,
    description="...",
),
```

`FlightState` calls the upfront function on a black screen, builds the rest
of the scene during the hyperspace animation, then creates the level's
`Mission` (`game.mission`) and starts the body (see
[docs/game.md](game.md#levels)).

## Waves

### `WaveSpec`

A frozen dataclass, checked as soon as the level module is imported: an
unknown field raises `TypeError`; a missing `size` for a single model, or a
`size` given for a mixed wave, raises `ValueError`.

| Field | Default | Meaning |
|---|---|---|
| `name` | required | Names the bots (`<name>_<i>`) |
| `ship_model` | required | A pawn model, or `(model, count)` pairs for a mixed wave |
| `size` | `None` | Number of ships; required for a single model, inferred for a mixed wave |
| `spawn_point` | `None` | Leader's world position; may instead be given at spawn time |
| `bot_type` | `"fighter"` | `"fighter"` or `"major_ship"` (the ship config picks an escort ship or a scripted capital ship) |
| `team` | `2` | |
| `spawn_orientation` | `(0, 0, 0, 1)` | Quaternion `(w, x, y, z)`, passed straight to Panda3D — the default is a 180° turn about z, **not** the identity |
| `formation` | `None` | `"arrowhead"`, `"diamond"`, `"around_diamond"`; `None` spawns in a centred line |
| `formation_scale_m` | `30` | Slot spacing |
| `waypoints` | `()` | Route given to every ship |
| `loop` | `True` | Whether the route loops |
| `record` | `False` | Step-by-step-record every bot of the wave |
| `hyperspace` | `True` | Whether the ships drop in from hyperspace (see [Hyperspace](#hyperspace)); `False` for ships already on stage when the level starts |
| `spawn_speed_mps` | `50` | Initial speed, along the spawn heading; a hyperspace drop lands at this speed |
| `loadouts` | `{}` | Fighters' weapons by ship model, e.g. `{"x-wing": ION_X_WING}` (see [loadouts](actors.md#loadouts)); models missing keep their default loadout |

Turrets and tractor beams are not waves: they are spawned from their host
capital ship's config (see [docs/subsystems.md](subsystems.md)).

### Spawning

```python
wave = m.wave(SPEC)                       # a handle, not spawned yet
wave.spawn(spawn_point=None, target=None, join=None, orientation=None,
           hyperspace=None)
wave = m.spawn(SPEC, spawn_point=..., target=..., join=...)   # both at once
```

- **One ship per frame**: a large wave never stalls the simulation on one
  long frame. No ship exists yet when `spawn()` returns, so wait with
  `m.wait_until(wave.alive)` before reading `wave.pawns()`.
- `spawn_point=` overrides the spec's, e.g. when it depends on the player's
  position at that moment.
- `orientation=` overrides the spec's `spawn_orientation` (a `(w, x, y, z)`
  quaternion), e.g. `game.player.pawn.orientation` to spawn ships flying the
  same way as the player.
- `target=` makes the ships attack a wave, the player, or any single ship
  (see [`who`](#who)). It is resolved as each ship spawns, against whatever
  is alive then.
- `join=` attaches the ships to an existing, live formation (e.g.
  `escort.formation`) instead of creating the spec's own. Each ship takes
  the formation's next free slot as it spawns, so a wave can join another
  that is still spawning.
- `hyperspace=` overrides the spec's `hyperspace` flag.
- Calling `spawn()` again on the same handle spawns the same composition
  again into the same wave.
- Fighters launched from a carrier's hangar make a wave too, with
  `m.launch(hangar, ...)` (see [Capital ships and hangars](#capital-ships-and-hangars)).

### `WaveHandle`

State is read live, so a handle stays valid for the whole mission, before
and after the wave exists:

| Member | Meaning |
|---|---|
| `alive()` | at least one member is alive |
| `all_destroyed()` | spawned, and every member is dead (false before spawning, and if any member [jumped out](#hyperspace) instead); for a [launched wave](#capital-ships-and-hangars), once the launch is over |
| `any_destroyed()` | spawned, and at least one member has died (stays true after a total wipe) |
| `any_jumped_out()` / `all_jumped_out()` | at least one / every member left the level through [hyperspace](#hyperspace) |
| `pawns()` | the live members, in spawn order (the formation leader first) |
| `destroyed_count()` | how many members have died so far (e.g. an [objective](#objectives)'s progress); an escape is not a kill |
| `jumped_out_count()` | how many members jumped out so far |
| `formation` | the wave's `Formation`, once spawned (or `None`) |
| `set_targets(who)` | every live member attacks every live pawn of `who` |
| `jump_out(spool_s=None)` | every live member leaves the level through [hyperspace](#hyperspace) |
| `set_team(team)` | reassigns every live member, cascading a major ship's cached team to its sub-systems, shield and mounted turrets/tractor beams (not to fighters it already launched) |
| `set_waypoints(points, loop=True)` | gives every live member a new route; only the formation leader flies it, wingmen hold formation |
| `follow(leader)` | every live member forms up on `leader` (e.g. `game.player`), which takes the formation's lead slot; members drop their routes, so none patrols a stale one if it takes the lead. Scripted capital ships are left out and keep their routes |
| `break_formation()` | every live member leaves the formation and flies its own route (e.g. before a race) |

`alive`, `all_destroyed`, `any_destroyed`, `any_jumped_out` and
`all_jumped_out` are plain methods. Call one to
get a bool; pass it **uncalled** to use it as a condition:
`m.on(wave.all_destroyed, ...)`.

### Hyperspace

Wave ships drop in from hyperspace: each is drawn rushing in from far behind
along its heading, then brakes hard onto its spawn point, landing at its
`spawn_speed_mps`. The members of a wave start a fraction of a second apart.
The drop is cosmetic: meanwhile the ship collides with nothing, nothing can
target it and it targets nothing, and its AI waits. It counts as alive
throughout (`wave.alive()` is true from its first frame).

`wave.jump_out()` (or `m.jump_out(who)`) is the way out: the AI is silenced
and the ship flies straight on for `spool_s` (2 s by default), spooling up
its hyperdrive — still a target, so the player can still destroy it. Then it
jumps, the drop played backwards, and leaves the level alive: it explodes
nowhere, counts as no kill, and its turrets, subsystems and shield leave with
it. `wave.any_jumped_out` tells an escape from a kill:

```python
m.on(near(smuggler, jump_point, 400), smuggler.jump_out)
m.on(smuggler.any_jumped_out, lambda: m.defeat("The gun-runner escaped."))
```

The transit's distances, durations and sharpness are set in
[`actors/hyperspace.py`](../../src/space_flight/actors/hyperspace.py).
Fighters launched from a hangar do not drop in, and the player cannot jump
out.

### Capital ships and hangars

A `WaveSpec` with `bot_type="major_ship"` spawns the ship type's class, picked
by its config's `ship_class`: an **escort ship** (frigate, corvette, transport)
fights on its own like any bot; a **capital ship** (star destroyer) is
scripted. It has no tactician: it always patrols the `waypoints` it is given
(`WaveSpec.waypoints`, `set_waypoints`, `reached_waypoint` work as for any
ship), without avoiding obstacles, and ignores targets; its turrets still
fight on their own. With no route left, it holds its heading. Its turn radius
is over a kilometre: give it widely spaced waypoints.

A major ship whose config declares `hangars` launches fighters on request,
through its `Hangar` subsystems (see [subsystems.md](subsystems.md#hangar)).
What a hangar holds is up to the level: declare the stock in the level module,
as fighters per type, and hand it to the hangar once the ship has spawned.
Then `m.launch` launches fighters from it **as a wave**:

```python
ENEMY_CAPITAL_SHIP_HANGAR_STOCK = {"tie-fighter": 12, "tie-bomber": 6}

def my_mission(m: Mission) -> Iterator[None]:
    isd = m.spawn(ENEMY_CAPITAL_SHIP)
    frigate = m.spawn(ALLIED_FRIGATE)
    yield from m.wait(5)  # the star destroyer has spawned
    hangar = isd.pawns()[0].hangars[0]
    hangar.set_stock(ENEMY_CAPITAL_SHIP_HANGAR_STOCK)
    squadron = m.launch(hangar, "tie-fighter", 3, target=frigate)
    m.on(squadron.all_destroyed, lambda: m.hud("TIE squadron destroyed"))
```

`m.launch(hangar, fighter_type, count=None, target=None, name=None,
formation="arrowhead", formation_scale_m=Formation.FIGHTER_SCALE_M,
loadout=None)` returns a `WaveHandle` of the launched fighters (its spec:
`fighter_type`, `count`, the hangar's team, the formation, the loadout; named
`<hangar>_<type>` by default):

- `count` fighters of `fighter_type` (the hangar's group size by default)
  leave the bay one at a time, as long as that type's stock lasts, and join
  the wave as they launch. A type not in the stock raises; an empty type
  launches nothing.
- `formation=` and `formation_scale_m=` set the fighters' formation, as for a
  `WaveSpec`: `"arrowhead"` (30 m slots) by default, `"diamond"`,
  `"around_diamond"`, or `None` for none. The first fighter out leads; the
  wave's `formation` is theirs.
- `target=` works as for `spawn()`: it is resolved as each fighter launches,
  so fighters leaving the bay later attack whatever is alive then.
- `loadout=` arms the fighters otherwise than their default (see
  [loadouts](actors.md#loadouts)).
- `all_destroyed()` only reads true once the launch is over (every fighter
  launched, or what was left cancelled), so never between two launches; it
  is true at once if nothing could be launched. The wave's `launch_order` is
  the hangar request behind it.
- Everything else is a plain wave: a condition, a target, `set_targets`,
  `follow`, `break_formation`... It has no spawn point, so it cannot be
  `spawn()`ed: its fighters only come from the hangar.
- Launches wait while the hangar has its maximum of fighters out, or while
  the game's actor slots run low. Destroying the hangar, or its ship, cancels
  what is left to launch.

At a lower level, `hangar.launch(fighter_type, count=None, on_launched=None,
primary_target_ids=(), formation="arrowhead", formation_scale_m=...,
loadout=None)` queues
the same request and returns its `LaunchOrder`
(the launched pawn `ids`, `done`, `cancelled`): `m.launch` wraps it
(`WaveHandle.launch_from(hangar, target)`).

## Sequencing

```python
yield from m.wait(10)                                  # 10 game-seconds
yield from m.wait_until(wave.all_destroyed)            # until a condition holds
ok = yield from m.wait_until(cond, timeout=30)         # True if met, False on timeout
m.schedule(chatter())                                  # run another generator alongside
```

`m.schedule(job)` steps any generator once per frame next to the body, e.g.
radio chatter that must not hold back the main sequence (see
[`mission1_level.py`](../../src/space_flight/game/levels/mission1_level.py)).
`m.dialogue(lines, stop=None)` is such a generator: it plays
`(delay, speaker, line)` tuples in turn, and ends early once `stop` is true.

## Reactive rules

```python
rule = m.on(condition, action, once=True)
rule.cancel()   # stop checking it
rule.fired      # whether its action has run
```

With `once=False`, the action runs every frame the condition holds.
`m.say_when(condition, text, speaker=None)` is the rule playing one line of
speech.

## Conditions

### `who`

Every condition or method taking a `who` accepts:

- a `WaveHandle` (any of its live members);
- the player or a bot (`game.player`, its pawn);
- a single pawn (e.g. `leader = wave.pawns()[0]`);
- a list or tuple of any of these (e.g. `[escort, game.player]`).

### Available conditions

| Condition | True when |
|---|---|
| `m.after(seconds)` | `seconds` have passed **from now** |
| `m.delay(cond, seconds)` | `seconds` after `cond` first became true — it **latches**, so a flicker back to false doesn't reset it |
| `m.sustained(cond, seconds)` | `cond` has held for an **unbroken** `seconds` — it resets whenever `cond` goes false |
| `near(who, point, radius)` | any live pawn of `who` is within `radius` of a fixed point |
| `near_actor(a, b, radius)` | the nearest pair of live pawns between `a` and `b` is within `radius` (two moving targets) |
| `reached_waypoint(who, index)` | any live bot of `who` has reached its waypoint `index` (0-based) |
| `damaged(who)` | any live pawn of `who` has lost health or shield since the condition first saw it (stateful: build it once) |
| `being_hit(who, by_player=False)` | any live pawn of `who` lost health or shield since the previous frame — a fresh hit, even on a regenerating shield; only the player's hits if `by_player` (stateful: build it once) |
| `scan.complete` / `scan.started` / `scan.progress_at_least(x)` | see [Scanning](#scanning) |
| `wave.alive` / `wave.all_destroyed` / `wave.any_destroyed` / `wave.any_jumped_out` / `wave.all_jumped_out` | see [`WaveHandle`](#wavehandle) |
| `objective.done` / `objective.failed` / `objective.active` | see [Objectives](#objectives) |
| `all_of(*conds)` / `any_of(*conds)` / `not_(cond)` | combinations |
| any `lambda: ...` | whatever it returns |

`m.delay` expresses "X, then wait, then…"; `m.sustained` expresses "for 10
*consecutive* seconds":

```python
# defeat 3s after the convoy is wiped out
m.on(m.delay(transports.all_destroyed, 3), lambda: m.defeat("..."))

# defeat if the player stays more than 300m from every escort ship for 20s
close = near_actor(game.player, escort, 300)
m.on(m.sustained(not_(close), 20), lambda: m.defeat("..."))
```

> `reached_waypoint` reads the navigator's waypoint index, which resets to 0
> at the end of each lap of a looping route and after the last waypoint of a
> non-looping one — so it is unambiguous only on the first pass.

## Scanning

```python
scan = m.scan(who, contraband=False, duration_s=15, range_m=1000,
              cone_deg=10, decay_ratio=0.5)
yield from m.wait_until(scan.complete)
```

`m.scan` makes every pawn of `who` scannable by the player from now on (a
wave that has not spawned yet is picked up as its ships appear). A pawn's
scan progresses while it is the player's target, within `range_m` and
within `cone_deg` of the player's nose, completing after `duration_s` of
it; otherwise it drains at `decay_ratio` times the fill rate. Once
complete it is frozen with its result, `"clear"` or `"contraband"`.

The state lives on the pawn itself, as `pawn.scan` (a `ScanState`:
`progress` from 0 to 1, `result`, `complete`, `status_text`), which is all
the targeting HUD reads to draw its progress bar (see
[docs/ui.md](ui.md)). The returned `ScanHandle`'s `complete()` (every live
pawn of `who` scanned), `started()` (some progress) and
`progress_at_least(x)` are conditions.

## Objectives

```python
escort = m.objective("Escort the convoy to the fleet",
                     done=reached_waypoint(transports, LAST_WAYPOINT),
                     failed=transports.all_destroyed)
m.objective("Shoot down the bombers", progress=bombers.destroyed_count, goal=5)
```

`m.objective(text, done=None, failed=None, progress=None, goal=None)` adds a
line to the HUD's objectives checklist (top left), in the order they are
given. It is ticked once `done` holds and crossed out once `failed` holds,
whichever comes first; it then stays as it is. With `progress` (a callable
counting up, e.g. `wave.destroyed_count` or `m.kills(...)`) and `goal`, the
line shows `"(n/goal)"` and, by default, is ticked when the count reaches
the goal; the count freezes once the objective is settled. A line blinks
for a moment when it is added, ticked or failed. Keep the text short: the
checklist is a reminder, while `m.hud` / `m.speech` explain.

The returned `Objective` can also be settled by the body, `complete()` or
`fail()` (no-ops once settled), or taken off the list, `remove()`. Its
`done()`, `failed()` and `active()` are conditions.

**Objectives never end the level**: they only show the player what to do.
End it as before, with `m.victory` / `m.defeat`, usually on the same
conditions. The level-end screen counts the objectives completed, so an
objective that holds until the end (a rule of engagement, "keep X alive")
needs ticking by the body before a victory. Ending the level first settles
any objective whose condition holds that very frame, so a defeat rule
declared before the objective on the same condition still counts it failed;
the objectives are then frozen, and the level-end screen follows 2 seconds
later (`LEVEL_END_DELAY_S`), so the player sees their final state.

A "bonus" objective is just one whose failure doesn't end the level, e.g.
`m.objective("Bonus: lose no transport", done=arrived, failed=transports.any_destroyed)`.

## Kills

The game logs who killed whom (`game.kill_log`, see
[`kills.py`](../../src/space_flight/game/kills.py)): the last ship to hit a
pawn or subsystem before it died gets the kill, whether by weapon or by
ramming it. A fatal crash into terrain credits no one; a subsystem brought
down with its ship credits that ship's killer.

`m.kills(victims=None, by_player=False)` is a live counter of the logged
kills of `victims` (a `who`, read on each call so a wave still spawning is
counted in full, including members already dead), only the player's if
`by_player`. It suits an objective's progress:

```python
m.objective("Shoot down 2 TIEs yourself",
            progress=m.kills([squadron, bombers], by_player=True), goal=2)
```

The level-end screen shows the player's kills, by category, and their
friendly fire.

## Actions

| Method | Effect |
|---|---|
| `m.hud(text)` | HUD banner message |
| `m.hint(text)` | tutorial hint, in place of the banner but smaller and wrapped; the texts, with the player's key bindings, come from [`game/levels/hints.py`](../../src/space_flight/game/levels/hints.py) |
| `m.speech(text, speaker=None)` | subtitle (`"speaker: text"`); audio is a logging stub for now |
| `m.player_waypoints(points, arrival_radius_m=None, marker_radius_m=None)` | a route of targetable waypoint markers for the player, replacing any previous one |
| `m.clear_player_waypoints()` | removes it |
| `m.jump_out(who, spool_s=None)` | every live bot of `who` leaves the level through [hyperspace](#hyperspace) |
| `m.victory(text)` / `m.defeat(text)` / `m.end_level(outcome, text)` | ends the level (`"victory"`, `"defeat"` or `"death"`): freezes the objectives, then shows the level-end screen, with the player's kills and objectives, 2 seconds later. Only the first ending counts |

How long each stays up is set in [`ui/hud.py`](../../src/space_flight/ui/hud.py)
(`CHATTER_DISPLAY_S`, `HINT_DISPLAY_S`, `EVENT_DISPLAY_S`). Chatter and
hints/banners take turns, never on screen together: a subtitle waits for a
hint or banner to time out, and the other way round, while a new subtitle
cuts the previous one short (as does a new hint or banner). Messages
waiting their turn are shown in order. HUD text, hints and speech are
skipped headless.

## Patterns and pitfalls

### Sequential vs. reactive

Put a step in the body when it is strictly ordered relative to the rest
("after the first wave arrives, wait for it to die, then bring in the
second"). Use `m.on` when it must hold wherever the body currently is.

### Build stateful conditions once

`m.after`, `m.delay` and `m.sustained` keep a timer (and `damaged` a
baseline), so each must be built once, when the rule is declared. Pass them to `m.on`, `m.wait_until`,
`all_of` or `any_of` directly, or name them first:

```python
wiped = m.delay(first_wave.all_destroyed, 3)
m.on(lambda: timeout() or wiped(), spawn_reinforcements)   # fine
m.on(lambda: m.delay(first_wave.all_destroyed, 3)(), ...)  # never fires: a fresh timer every frame
```

### Refer to a wave before it spawns

A rule registered up front may need a wave that spawns later: create its
handle with `m.wave(SPEC)` first, then call `spawn()` on it when the time
comes. Its state methods are simply false until then.

### Only one ending

The body and a rule can each end the level, e.g. a rule-driven defeat while
the body later reaches a victory. Only the first ending counts: later calls
are ignored. Still, cancel a rule once it no longer applies
(`rule.cancel()`), so its other actions (a speech line...) don't play
during the ending.

### Extending

A new condition is just a function returning a zero-argument callable (see
[`conditions.py`](../../src/space_flight/game/scenario/conditions.py)); a
new action is just a function or a lambda. Nothing needs registering.

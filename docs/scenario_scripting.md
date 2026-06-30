# Scenario scripting

A level's scripted events — when enemy waves arrive, what they attack, mission
objectives — are written declaratively in a YAML file next to the level, and run
by a generic engine. You tune most things without touching Python.

Each level points at its own file, e.g.
[`intro_level.yaml`](../src/space_flight/game/levels/intro_level.yaml) for the
intro level.

## Mental model

The engine is built on three ideas:

- **Trigger** — a rule: *when* a condition becomes true, run an *action*.
- **Condition** — a question answered every frame: "has 50 s passed?", "is the
  first wave wiped out?". Conditions compose.
- **Action** — something that happens: spawn a wave, show a HUD message.

Triggers fire **once** by default. Membership and liveness are tracked for you,
so you never write "has this already happened" flags.

## File structure

```yaml
waves:        # reusable spawn definitions, keyed by the group id they spawn into
  first_wave:
    size: 5
    ship_model: tie-bomber
    spawn_point: [300, 6000, 500]
    # ...

triggers:     # the mission rules
  - name: first_wave            # optional, for logging
    when: { after_seconds: 50 } # a condition
    then: { spawn: first_wave } # an action
```

A `when` or `then` node is always a **single-key mapping**: the key chooses the
condition/action, the value is its argument.

## Waves

A wave entry describes a group of bots. Its **key is the group id** — that same
name is what conditions and targets refer to elsewhere.

```yaml
waves:
  first_wave:
    size: 5                       # number of ships
    ship_model: tie-bomber        # pawn model
    bot_type: fighter             # fighter | capital_ship | turret (default: fighter)
    team: 2                       # default: 2
    spawn_point: [300, 6000, 500] # world position of the formation leader
    spawn_orientation: [0, 0, 0, 1]
    formation: { scale_m: 30, shape: arrowhead }  # arrowhead | diamond | around_diamond
    waypoints:                    # optional patrol path
      - [300, 0, 500]
      - [300, -6000, 500]
    loop: true                    # loop the waypoints (default: true)
    target: transports            # group name to attack (optional)
    hud_text: "Enemy ships incoming!"  # shown when the wave begins (optional)
    allow_respawn: false          # see "Spawning once", below
```

Only `id` (the key), `size`, `ship_model`, and `spawn_point` are required.

### Formation spawning

When a wave declares a `formation`, ships spawn **in formation**: the leader at
`spawn_point`, each wingman at its slot offset from there. Ships beyond the
formation's capacity (e.g. `size: 12` in an 8-slot diamond) fall back to a
centred line. A wave with no `formation` spawns entirely in a centred line.

### Spawning is spread across frames

A wave spawns **one ship per frame**, so a large wave never freezes the
simulation on one long loading frame. There is nothing to configure — it is how
every wave spawns.

### Spawning once

A wave id is an *identity group*: by default it spawns **at most once**, even if
several triggers point at it. A second attempt is skipped with a warning. This
is a safety net — see [One wave, one trigger](#one-wave-one-trigger). Set
`allow_respawn: true` for the rare case where re-spawning the same composition
into the same group is intended.

## Conditions (`when`)

### Leaf conditions

| Condition | Argument | True when |
|---|---|---|
| `after_seconds` | seconds | the game clock passes that time |
| `all_destroyed` | group name | the group has spawned **and** all members are dead |
| `any_alive` | group name | at least one member of the group is alive |
| `reached_waypoint` | `{who, index}` | the (first live) member of `who` has reached waypoint `index` |
| `near` | `{who, point, radius}` | `who` is within `radius` of `point` (`who` is `player` or a group; for a group, any live member) |
| `fired` | trigger name | the named trigger has already fired |

```yaml
when: { after_seconds: 50 }
when: { all_destroyed: first_wave }
when: { reached_waypoint: { who: transports, index: 5 } }
when: { near: { who: player, point: [0, 2000, 500], radius: 350 } }
when: { fired: blockade_past }
```

`fired` is how you chain a trigger off another by name (most often wrapped in
`delay`, below). Every condition — including the inner `after` of a `delay` — is a
single-key mapping like these; there is no bare-string form.

`all_destroyed` is deliberately **false before the group has ever spawned**, so a
chained event cannot fire against a wave that does not exist yet.

> `reached_waypoint` reads the navigator's waypoint index, which resets each lap
> on a looping patrol — so it is unambiguous only on the first lap.

### Combinators

Combinators nest, so you can build up arbitrarily complex conditions:

| Combinator | Argument | True when |
|---|---|---|
| `all_of` | list of conditions | every sub-condition is true |
| `any_of` | list of conditions | any sub-condition is true |
| `delay` | `{after, seconds}` | `seconds` have elapsed since `after` first became true |

`delay` is what expresses "X, then wait, then…". It **latches**: once `after`
becomes true the timer is armed and keeps running even if `after` flickers back
to false.

```yaml
# 3 seconds after the first wave is wiped out
when:
  delay:
    after: { all_destroyed: first_wave }
    seconds: 3

# 3 seconds after the `blockade_past` trigger fired
when:
  delay:
    after: { fired: blockade_past }
    seconds: 3

# convoy reached waypoint 5 AND the second wave is gone
when:
  all_of:
    - { reached_waypoint: { who: transports, index: 5 } }
    - { all_destroyed: second_wave }
```

## Actions (`then`)

| Action | Argument | Effect |
|---|---|---|
| `spawn` | wave id | spawn the wave defined under `waves:` |
| `hud_text` | string, or `{text, display_time_s}` | show a HUD banner |
| `speech` | string, or `{text, speaker, display_time_s}` | play a voice line and show it as a subtitle |
| `player_waypoints` | list of points, or `{points, arrival_radius_m, marker_radius_m}` | guide the player with targetable waypoint spheres |
| `end_level` | outcome string, or `{outcome, text}` | end the level with a `victory`/`defeat`/`death` screen |
| `all` | list of actions | run several actions in order |

```yaml
then: { spawn: first_wave }
then: { hud_text: "Reinforcements detected!" }
then: { end_level: victory }                 # outcome only
then: { end_level: { outcome: defeat, text: "The convoy was lost." } }
then:
  speech:
    speaker: "Gold Leader"
    text: "Gold squadron reporting in."
    display_time_s: 5
then:
  all:
    - { hud_text: "Reinforcements detected!" }
    - { spawn: third_wave }
```

`speech` shows a subtitle near the bottom of the screen (prefixed with `speaker`
when given). The audio playback itself is currently stubbed — only the subtitle
is rendered.

`player_waypoints` shows the player's route one waypoint at a time as a
semi-transparent sphere; flying within `arrival_radius_m` (default 350) of the
current waypoint reveals the next. The marker is a neutral actor (bots ignore
it) and is shown and targetable only while the player's **"Waypoints"** target
filter is active — selecting that filter lets the player lock onto it.

```yaml
then:
  player_waypoints:
    points:
      - [0, 2000, 500]
      - [3000, 4000, 600]
```

`end_level` summons the terminal level-end screen. `outcome` is `victory`,
`defeat`, or `death` (which picks the title and tint); `text` is the
level-specific explanation shown beneath it. The same screen is used when the
player's ship is destroyed (`death`).

## Groups

A **group** is a named set of actors. Two kinds:

- **Identity groups** — a specific cohort. Every wave is one (its id is the
  group name). Standing groups built in the level (the convoy, its escort) are
  registered by name in the level's Python build code:

  ```python
  game.scenario.register(name="transports", bots=game.transport_bots)
  ```

- **Query groups** — derived live from a predicate (e.g. "all team-2 ships").
  Registered in Python with `register_query`; no membership is stored.

Names are the only thing that crosses between YAML and Python: the YAML refers to
`transports`, the engine resolves that to whichever transports are currently
alive. Dead members drop out of every query automatically.

## Patterns and pitfalls

### One wave, one trigger

The one-shot guard lives on the **trigger**, not the wave. Two triggers that both
`spawn` the same wave would each fire once → the wave spawns twice. (The
`allow_respawn: false` default catches this and skips the second spawn, but the
clean fix is to not write it that way.)

If a wave should arrive via either of two conditions, use **one** trigger with
`any_of`:

```yaml
# third wave arrives at 200s OR 3s after the first wave is wiped — once
- name: third_wave
  when:
    any_of:
      - { after_seconds: 200 }
      - delay:
          after: { all_destroyed: first_wave }
          seconds: 3
  then:
    all:
      - { hud_text: "Reinforcements detected!" }
      - { spawn: third_wave }
```

### Chaining events

Because a condition can reference a group, events chain naturally: an action
spawns `first_wave`; another trigger watches `all_destroyed: first_wave` to
launch reinforcements; a third watches the convoy's progress for a mission
objective. Keep each rule independent and let the conditions order them.

## Extending the vocabulary

New conditions and actions are small Python factories:

- a **condition** is any callable `condition(game) -> bool` — see
  [`conditions.py`](../src/space_flight/game/scenario/conditions.py);
- an **action** is any callable `action(game) -> None` — see
  [`actions.py`](../src/space_flight/game/scenario/actions.py).

After writing the factory, wire its YAML keyword into the matching `_build_*`
function in [`loader.py`](../src/space_flight/game/scenario/loader.py). Resist
adding a keyword before you have a couple of real uses for it.

# {py:mod}`space_flight.weapons.bomb_launcher`

```{py:module} space_flight.weapons.bomb_launcher
```

```{autodoc2-docstring} space_flight.weapons.bomb_launcher
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`BombLauncher <space_flight.weapons.bomb_launcher.BombLauncher>`
  - ```{autodoc2-docstring} space_flight.weapons.bomb_launcher.BombLauncher
    :summary:
    ```
* - {py:obj}`Bomb <space_flight.weapons.bomb_launcher.Bomb>`
  - ```{autodoc2-docstring} space_flight.weapons.bomb_launcher.Bomb
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`BOMB_SPEED_MPS <space_flight.weapons.bomb_launcher.BOMB_SPEED_MPS>`
  - ```{autodoc2-docstring} space_flight.weapons.bomb_launcher.BOMB_SPEED_MPS
    :summary:
    ```
* - {py:obj}`BOMB_RANGE_M <space_flight.weapons.bomb_launcher.BOMB_RANGE_M>`
  - ```{autodoc2-docstring} space_flight.weapons.bomb_launcher.BOMB_RANGE_M
    :summary:
    ```
* - {py:obj}`BOMB_DAMAGE <space_flight.weapons.bomb_launcher.BOMB_DAMAGE>`
  - ```{autodoc2-docstring} space_flight.weapons.bomb_launcher.BOMB_DAMAGE
    :summary:
    ```
* - {py:obj}`BASE_RELOAD_S <space_flight.weapons.bomb_launcher.BASE_RELOAD_S>`
  - ```{autodoc2-docstring} space_flight.weapons.bomb_launcher.BASE_RELOAD_S
    :summary:
    ```
* - {py:obj}`BOMB_VISUAL_RADIUS_M <space_flight.weapons.bomb_launcher.BOMB_VISUAL_RADIUS_M>`
  - ```{autodoc2-docstring} space_flight.weapons.bomb_launcher.BOMB_VISUAL_RADIUS_M
    :summary:
    ```
* - {py:obj}`BOMB_COLLISION_RADIUS_M <space_flight.weapons.bomb_launcher.BOMB_COLLISION_RADIUS_M>`
  - ```{autodoc2-docstring} space_flight.weapons.bomb_launcher.BOMB_COLLISION_RADIUS_M
    :summary:
    ```
* - {py:obj}`BOMB_COLOR <space_flight.weapons.bomb_launcher.BOMB_COLOR>`
  - ```{autodoc2-docstring} space_flight.weapons.bomb_launcher.BOMB_COLOR
    :summary:
    ```
````

### API

````{py:data} BOMB_SPEED_MPS
:canonical: space_flight.weapons.bomb_launcher.BOMB_SPEED_MPS
:value: >
   75.0

```{autodoc2-docstring} space_flight.weapons.bomb_launcher.BOMB_SPEED_MPS
```

````

````{py:data} BOMB_RANGE_M
:canonical: space_flight.weapons.bomb_launcher.BOMB_RANGE_M
:value: >
   500.0

```{autodoc2-docstring} space_flight.weapons.bomb_launcher.BOMB_RANGE_M
```

````

````{py:data} BOMB_DAMAGE
:canonical: space_flight.weapons.bomb_launcher.BOMB_DAMAGE
:value: >
   4000.0

```{autodoc2-docstring} space_flight.weapons.bomb_launcher.BOMB_DAMAGE
```

````

````{py:data} BASE_RELOAD_S
:canonical: space_flight.weapons.bomb_launcher.BASE_RELOAD_S
:value: >
   0.5

```{autodoc2-docstring} space_flight.weapons.bomb_launcher.BASE_RELOAD_S
```

````

````{py:data} BOMB_VISUAL_RADIUS_M
:canonical: space_flight.weapons.bomb_launcher.BOMB_VISUAL_RADIUS_M
:value: >
   0.5

```{autodoc2-docstring} space_flight.weapons.bomb_launcher.BOMB_VISUAL_RADIUS_M
```

````

````{py:data} BOMB_COLLISION_RADIUS_M
:canonical: space_flight.weapons.bomb_launcher.BOMB_COLLISION_RADIUS_M
:value: >
   0.5

```{autodoc2-docstring} space_flight.weapons.bomb_launcher.BOMB_COLLISION_RADIUS_M
```

````

````{py:data} BOMB_COLOR
:canonical: space_flight.weapons.bomb_launcher.BOMB_COLOR
:value: >
   (1.0, 0.4, 0.7, 1.0)

```{autodoc2-docstring} space_flight.weapons.bomb_launcher.BOMB_COLOR
```

````

`````{py:class} BombLauncher(game, parent, parent_node=None)
:canonical: space_flight.weapons.bomb_launcher.BombLauncher

Bases: {py:obj}`space_flight.weapons.Weapon`

```{autodoc2-docstring} space_flight.weapons.bomb_launcher.BombLauncher
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.weapons.bomb_launcher.BombLauncher.__init__
```

````{py:method} launch() -> bool
:canonical: space_flight.weapons.bomb_launcher.BombLauncher.launch

```{autodoc2-docstring} space_flight.weapons.bomb_launcher.BombLauncher.launch
```

````

`````

`````{py:class} Bomb(game, origin_ship_id, power: float, life_time_s: float, speed: numpy.ndarray, start_position, origin_ship=None)
:canonical: space_flight.weapons.bomb_launcher.Bomb

Bases: {py:obj}`space_flight.weapons.Munition`

```{autodoc2-docstring} space_flight.weapons.bomb_launcher.Bomb
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.weapons.bomb_launcher.Bomb.__init__
```

````{py:method} _build_visual(start_position)
:canonical: space_flight.weapons.bomb_launcher.Bomb._build_visual

````

````{py:method} _attach_collider()
:canonical: space_flight.weapons.bomb_launcher.Bomb._attach_collider

````

`````

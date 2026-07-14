# {py:mod}`space_flight.weapons`

```{py:module} space_flight.weapons
```

```{autodoc2-docstring} space_flight.weapons
:allowtitles:
```

## Submodules

```{toctree}
:titlesonly:
:maxdepth: 1

space_flight.weapons.bomb_launcher
space_flight.weapons.laser_cannon
```

## Package Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`Weapon <space_flight.weapons.Weapon>`
  - ```{autodoc2-docstring} space_flight.weapons.Weapon
    :summary:
    ```
* - {py:obj}`Munition <space_flight.weapons.Munition>`
  - ```{autodoc2-docstring} space_flight.weapons.Munition
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`LOGGER <space_flight.weapons.LOGGER>`
  - ```{autodoc2-docstring} space_flight.weapons.LOGGER
    :summary:
    ```
````

### API

````{py:data} LOGGER
:canonical: space_flight.weapons.LOGGER
:value: >
   'getLogger(...)'

```{autodoc2-docstring} space_flight.weapons.LOGGER
```

````

`````{py:class} Weapon(game, parent, parent_node=None, fire_delay: float = 0.0)
:canonical: space_flight.weapons.Weapon

```{autodoc2-docstring} space_flight.weapons.Weapon
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.weapons.Weapon.__init__
```

````{py:method} _ready_to_fire() -> bool
:canonical: space_flight.weapons.Weapon._ready_to_fire

```{autodoc2-docstring} space_flight.weapons.Weapon._ready_to_fire
```

````

````{py:method} _spawn_munition(munition_class, start_position, speed, power: float, life_time_s: float, **munition_kwargs) -> None
:canonical: space_flight.weapons.Weapon._spawn_munition

```{autodoc2-docstring} space_flight.weapons.Weapon._spawn_munition
```

````

````{py:method} clean() -> None
:canonical: space_flight.weapons.Weapon.clean

```{autodoc2-docstring} space_flight.weapons.Weapon.clean
```

````

````{py:method} __del__()
:canonical: space_flight.weapons.Weapon.__del__

```{autodoc2-docstring} space_flight.weapons.Weapon.__del__
```

````

`````

`````{py:class} Munition(game, origin_ship_id, power: float, life_time_s: float, speed: numpy.ndarray, start_position, origin_ship=None)
:canonical: space_flight.weapons.Munition

```{autodoc2-docstring} space_flight.weapons.Munition
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.weapons.Munition.__init__
```

````{py:method} _build_visual(start_position) -> panda3d.core.NodePath
:canonical: space_flight.weapons.Munition._build_visual
:abstractmethod:

```{autodoc2-docstring} space_flight.weapons.Munition._build_visual
```

````

````{py:method} _attach_collider() -> panda3d.core.NodePath
:canonical: space_flight.weapons.Munition._attach_collider
:abstractmethod:

```{autodoc2-docstring} space_flight.weapons.Munition._attach_collider
```

````

````{py:method} _clean_extra() -> None
:canonical: space_flight.weapons.Munition._clean_extra

```{autodoc2-docstring} space_flight.weapons.Munition._clean_extra
```

````

````{py:method} clean(remove_from_game_objects: bool = True) -> None
:canonical: space_flight.weapons.Munition.clean

```{autodoc2-docstring} space_flight.weapons.Munition.clean
```

````

````{py:method} __del__()
:canonical: space_flight.weapons.Munition.__del__

```{autodoc2-docstring} space_flight.weapons.Munition.__del__
```

````

`````

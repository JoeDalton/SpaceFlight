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

space_flight.weapons.ordnance_launcher
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

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`build_ordnance_sphere <space_flight.weapons.build_ordnance_sphere>`
  - ```{autodoc2-docstring} space_flight.weapons.build_ordnance_sphere
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

````{py:function} build_ordnance_sphere(game: space_flight.game.flight_state.FlightState, parent_node: panda3d.core.NodePath, radius_m: float, color: tuple[float, float, float, float]) -> panda3d.core.NodePath
:canonical: space_flight.weapons.build_ordnance_sphere

```{autodoc2-docstring} space_flight.weapons.build_ordnance_sphere
```
````

`````{py:class} Weapon(game: space_flight.game.flight_state.FlightState, parent: space_flight.actors.fighter.Fighter | space_flight.actors.capital_ship.turret.Turret, parent_node: panda3d.core.NodePath | None = None, fire_delay: float = 0.0)
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

````{py:method} restart_reload()
:canonical: space_flight.weapons.Weapon.restart_reload

```{autodoc2-docstring} space_flight.weapons.Weapon.restart_reload
```

````

````{py:method} _spawn_munition(munition_class: type[space_flight.weapons.Munition], start_position: panda3d.core.Point3, speed: numpy.ndarray, power: float, life_time_s: float, **munition_kwargs: typing.Any)
:canonical: space_flight.weapons.Weapon._spawn_munition

```{autodoc2-docstring} space_flight.weapons.Weapon._spawn_munition
```

````

````{py:method} clean()
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

`````{py:class} Munition(game: space_flight.game.flight_state.FlightState, origin_ship_id: uuid.UUID, power: float, life_time_s: float, speed: numpy.ndarray, start_position: panda3d.core.Point3, origin_ship: space_flight.actors.fighter.Fighter | space_flight.actors.capital_ship.turret.Turret | None = None)
:canonical: space_flight.weapons.Munition

```{autodoc2-docstring} space_flight.weapons.Munition
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.weapons.Munition.__init__
```

````{py:method} _build_visual(start_position: panda3d.core.Point3) -> panda3d.core.NodePath
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

````{py:method} _clean_extra()
:canonical: space_flight.weapons.Munition._clean_extra

```{autodoc2-docstring} space_flight.weapons.Munition._clean_extra
```

````

````{py:method} on_impact()
:canonical: space_flight.weapons.Munition.on_impact

```{autodoc2-docstring} space_flight.weapons.Munition.on_impact
```

````

````{py:method} impact_position() -> panda3d.core.Point3
:canonical: space_flight.weapons.Munition.impact_position

```{autodoc2-docstring} space_flight.weapons.Munition.impact_position
```

````

````{py:method} clean(remove_from_game_objects: bool = True)
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

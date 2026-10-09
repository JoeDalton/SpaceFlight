# {py:mod}`space_flight.ai.missile.missile_navigator`

```{py:module} space_flight.ai.missile.missile_navigator
```

```{autodoc2-docstring} space_flight.ai.missile.missile_navigator
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`MissileNavigator <space_flight.ai.missile.missile_navigator.MissileNavigator>`
  - ```{autodoc2-docstring} space_flight.ai.missile.missile_navigator.MissileNavigator
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_ZERO3 <space_flight.ai.missile.missile_navigator._ZERO3>`
  - ```{autodoc2-docstring} space_flight.ai.missile.missile_navigator._ZERO3
    :summary:
    ```
````

### API

````{py:data} _ZERO3
:canonical: space_flight.ai.missile.missile_navigator._ZERO3
:value: >
   'zeros(...)'

```{autodoc2-docstring} space_flight.ai.missile.missile_navigator._ZERO3
```

````

`````{py:class} MissileNavigator(game: space_flight.game.flight_state.FlightState, pawn: space_flight.actors.ordnance.Ordnance, personality: dict = Personality.MISSILE_DEFAULT, debug: bool = False)
:canonical: space_flight.ai.missile.missile_navigator.MissileNavigator

Bases: {py:obj}`space_flight.ai.generic.generic_navigator.GenericNavigator`

```{autodoc2-docstring} space_flight.ai.missile.missile_navigator.MissileNavigator
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.ai.missile.missile_navigator.MissileNavigator.__init__
```

````{py:method} navigate(intent: space_flight.ai.Intent, target_dict: dict) -> tuple[numpy.ndarray, float]
:canonical: space_flight.ai.missile.missile_navigator.MissileNavigator.navigate

```{autodoc2-docstring} space_flight.ai.missile.missile_navigator.MissileNavigator.navigate
```

````

````{py:method} pursue(target: typing.Any) -> tuple[numpy.ndarray, float]
:canonical: space_flight.ai.missile.missile_navigator.MissileNavigator.pursue

```{autodoc2-docstring} space_flight.ai.missile.missile_navigator.MissileNavigator.pursue
```

````

````{py:method} find_target(target_id: uuid.UUID | None) -> space_flight.actors.pawn.Pawn | None
:canonical: space_flight.ai.missile.missile_navigator.MissileNavigator.find_target

```{autodoc2-docstring} space_flight.ai.missile.missile_navigator.MissileNavigator.find_target
```

````

`````

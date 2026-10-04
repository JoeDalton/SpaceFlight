# {py:mod}`space_flight.ai.target_lock`

```{py:module} space_flight.ai.target_lock
```

```{autodoc2-docstring} space_flight.ai.target_lock
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`TargetLock <space_flight.ai.target_lock.TargetLock>`
  - ```{autodoc2-docstring} space_flight.ai.target_lock.TargetLock
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`LOGGER <space_flight.ai.target_lock.LOGGER>`
  - ```{autodoc2-docstring} space_flight.ai.target_lock.LOGGER
    :summary:
    ```
* - {py:obj}`_ACQUIRING <space_flight.ai.target_lock._ACQUIRING>`
  - ```{autodoc2-docstring} space_flight.ai.target_lock._ACQUIRING
    :summary:
    ```
* - {py:obj}`_LOCKED <space_flight.ai.target_lock._LOCKED>`
  - ```{autodoc2-docstring} space_flight.ai.target_lock._LOCKED
    :summary:
    ```
````

### API

````{py:data} LOGGER
:canonical: space_flight.ai.target_lock.LOGGER
:value: >
   'getLogger(...)'

```{autodoc2-docstring} space_flight.ai.target_lock.LOGGER
```

````

````{py:data} _ACQUIRING
:canonical: space_flight.ai.target_lock._ACQUIRING
:value: >
   'acquiring'

```{autodoc2-docstring} space_flight.ai.target_lock._ACQUIRING
```

````

````{py:data} _LOCKED
:canonical: space_flight.ai.target_lock._LOCKED
:value: >
   'locked'

```{autodoc2-docstring} space_flight.ai.target_lock._LOCKED
```

````

`````{py:class} TargetLock(game: space_flight.game.flight_state.FlightState, parent: space_flight.actors.fighter.Fighter | space_flight.actors.capital_ship.turret.Turret, lock_delay_s: float = 1.0, cone_angle_deg: float = 30.0)
:canonical: space_flight.ai.target_lock.TargetLock

```{autodoc2-docstring} space_flight.ai.target_lock.TargetLock
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.ai.target_lock.TargetLock.__init__
```

````{py:method} configure(lock_delay_s: float = 1.0, cone_angle_deg: float = 30.0)
:canonical: space_flight.ai.target_lock.TargetLock.configure

```{autodoc2-docstring} space_flight.ai.target_lock.TargetLock.configure
```

````

````{py:property} is_locked
:canonical: space_flight.ai.target_lock.TargetLock.is_locked
:type: bool

```{autodoc2-docstring} space_flight.ai.target_lock.TargetLock.is_locked
```

````

````{py:property} elapsed_time_s
:canonical: space_flight.ai.target_lock.TargetLock.elapsed_time_s
:type: float

```{autodoc2-docstring} space_flight.ai.target_lock.TargetLock.elapsed_time_s
```

````

````{py:method} _restart()
:canonical: space_flight.ai.target_lock.TargetLock._restart

```{autodoc2-docstring} space_flight.ai.target_lock.TargetLock._restart
```

````

````{py:method} reset()
:canonical: space_flight.ai.target_lock.TargetLock.reset

```{autodoc2-docstring} space_flight.ai.target_lock.TargetLock.reset
```

````

````{py:method} update()
:canonical: space_flight.ai.target_lock.TargetLock.update

```{autodoc2-docstring} space_flight.ai.target_lock.TargetLock.update
```

````

````{py:method} clean()
:canonical: space_flight.ai.target_lock.TargetLock.clean

```{autodoc2-docstring} space_flight.ai.target_lock.TargetLock.clean
```

````

`````

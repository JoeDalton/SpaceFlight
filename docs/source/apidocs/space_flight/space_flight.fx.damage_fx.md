# {py:mod}`space_flight.fx.damage_fx`

```{py:module} space_flight.fx.damage_fx
```

```{autodoc2-docstring} space_flight.fx.damage_fx
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`DamageFX <space_flight.fx.damage_fx.DamageFX>`
  - ```{autodoc2-docstring} space_flight.fx.damage_fx.DamageFX
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_hull_jitter <space_flight.fx.damage_fx._hull_jitter>`
  - ```{autodoc2-docstring} space_flight.fx.damage_fx._hull_jitter
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`DEFAULT_SMOKE_HEALTH_FRAC <space_flight.fx.damage_fx.DEFAULT_SMOKE_HEALTH_FRAC>`
  - ```{autodoc2-docstring} space_flight.fx.damage_fx.DEFAULT_SMOKE_HEALTH_FRAC
    :summary:
    ```
* - {py:obj}`DEFAULT_FIRE_HEALTH_FRAC <space_flight.fx.damage_fx.DEFAULT_FIRE_HEALTH_FRAC>`
  - ```{autodoc2-docstring} space_flight.fx.damage_fx.DEFAULT_FIRE_HEALTH_FRAC
    :summary:
    ```
* - {py:obj}`_SMOKE_VELOCITY_DRAG <space_flight.fx.damage_fx._SMOKE_VELOCITY_DRAG>`
  - ```{autodoc2-docstring} space_flight.fx.damage_fx._SMOKE_VELOCITY_DRAG
    :summary:
    ```
* - {py:obj}`_SeveritySpec <space_flight.fx.damage_fx._SeveritySpec>`
  - ```{autodoc2-docstring} space_flight.fx.damage_fx._SeveritySpec
    :summary:
    ```
* - {py:obj}`_SEVERITY <space_flight.fx.damage_fx._SEVERITY>`
  - ```{autodoc2-docstring} space_flight.fx.damage_fx._SEVERITY
    :summary:
    ```
````

### API

````{py:data} DEFAULT_SMOKE_HEALTH_FRAC
:canonical: space_flight.fx.damage_fx.DEFAULT_SMOKE_HEALTH_FRAC
:value: >
   None

```{autodoc2-docstring} space_flight.fx.damage_fx.DEFAULT_SMOKE_HEALTH_FRAC
```

````

````{py:data} DEFAULT_FIRE_HEALTH_FRAC
:canonical: space_flight.fx.damage_fx.DEFAULT_FIRE_HEALTH_FRAC
:value: >
   None

```{autodoc2-docstring} space_flight.fx.damage_fx.DEFAULT_FIRE_HEALTH_FRAC
```

````

````{py:data} _SMOKE_VELOCITY_DRAG
:canonical: space_flight.fx.damage_fx._SMOKE_VELOCITY_DRAG
:value: >
   0.12

```{autodoc2-docstring} space_flight.fx.damage_fx._SMOKE_VELOCITY_DRAG
```

````

````{py:data} _SeveritySpec
:canonical: space_flight.fx.damage_fx._SeveritySpec
:value: >
   'namedtuple(...)'

```{autodoc2-docstring} space_flight.fx.damage_fx._SeveritySpec
```

````

````{py:data} _SEVERITY
:canonical: space_flight.fx.damage_fx._SEVERITY
:value: >
   None

```{autodoc2-docstring} space_flight.fx.damage_fx._SEVERITY
```

````

`````{py:class} DamageFX(game: space_flight.game.flight_state.FlightState, owner: typing.Any, smoke_health_frac: float = DEFAULT_SMOKE_HEALTH_FRAC, fire_health_frac: float = DEFAULT_FIRE_HEALTH_FRAC)
:canonical: space_flight.fx.damage_fx.DamageFX

```{autodoc2-docstring} space_flight.fx.damage_fx.DamageFX
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.fx.damage_fx.DamageFX.__init__
```

````{py:method} _severity() -> int
:canonical: space_flight.fx.damage_fx.DamageFX._severity

```{autodoc2-docstring} space_flight.fx.damage_fx.DamageFX._severity
```

````

````{py:method} update() -> None
:canonical: space_flight.fx.damage_fx.DamageFX.update

```{autodoc2-docstring} space_flight.fx.damage_fx.DamageFX.update
```

````

````{py:method} clean() -> None
:canonical: space_flight.fx.damage_fx.DamageFX.clean

```{autodoc2-docstring} space_flight.fx.damage_fx.DamageFX.clean
```

````

`````

````{py:function} _hull_jitter(severity: int) -> numpy.ndarray
:canonical: space_flight.fx.damage_fx._hull_jitter

```{autodoc2-docstring} space_flight.fx.damage_fx._hull_jitter
```
````

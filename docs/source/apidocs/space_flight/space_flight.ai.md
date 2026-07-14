# {py:mod}`space_flight.ai`

```{py:module} space_flight.ai
```

```{autodoc2-docstring} space_flight.ai
:allowtitles:
```

## Subpackages

```{toctree}
:titlesonly:
:maxdepth: 3

space_flight.ai.tracking_mount
```

## Submodules

```{toctree}
:titlesonly:
:maxdepth: 1

space_flight.ai.interactions
space_flight.ai.collision_sensor
space_flight.ai.formation
space_flight.ai.auto_aim
```

## Package Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`Intent <space_flight.ai.Intent>`
  - ```{autodoc2-docstring} space_flight.ai.Intent
    :summary:
    ```
* - {py:obj}`AttackMode <space_flight.ai.AttackMode>`
  - ```{autodoc2-docstring} space_flight.ai.AttackMode
    :summary:
    ```
* - {py:obj}`Personality <space_flight.ai.Personality>`
  - ```{autodoc2-docstring} space_flight.ai.Personality
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`TARGET_DISTANCE_TOLERANCE_M <space_flight.ai.TARGET_DISTANCE_TOLERANCE_M>`
  - ```{autodoc2-docstring} space_flight.ai.TARGET_DISTANCE_TOLERANCE_M
    :summary:
    ```
* - {py:obj}`INTERACT_MAX_DISTANCE_M <space_flight.ai.INTERACT_MAX_DISTANCE_M>`
  - ```{autodoc2-docstring} space_flight.ai.INTERACT_MAX_DISTANCE_M
    :summary:
    ```
* - {py:obj}`REFERENCE_ERROR_VELOCITY_MPS <space_flight.ai.REFERENCE_ERROR_VELOCITY_MPS>`
  - ```{autodoc2-docstring} space_flight.ai.REFERENCE_ERROR_VELOCITY_MPS
    :summary:
    ```
* - {py:obj}`ROLL_TOLERANCE <space_flight.ai.ROLL_TOLERANCE>`
  - ```{autodoc2-docstring} space_flight.ai.ROLL_TOLERANCE
    :summary:
    ```
* - {py:obj}`HALF_PI <space_flight.ai.HALF_PI>`
  - ```{autodoc2-docstring} space_flight.ai.HALF_PI
    :summary:
    ```
* - {py:obj}`LOGGER <space_flight.ai.LOGGER>`
  - ```{autodoc2-docstring} space_flight.ai.LOGGER
    :summary:
    ```
````

### API

````{py:data} TARGET_DISTANCE_TOLERANCE_M
:canonical: space_flight.ai.TARGET_DISTANCE_TOLERANCE_M
:value: >
   1.0

```{autodoc2-docstring} space_flight.ai.TARGET_DISTANCE_TOLERANCE_M
```

````

````{py:data} INTERACT_MAX_DISTANCE_M
:canonical: space_flight.ai.INTERACT_MAX_DISTANCE_M
:value: >
   10000.0

```{autodoc2-docstring} space_flight.ai.INTERACT_MAX_DISTANCE_M
```

````

````{py:data} REFERENCE_ERROR_VELOCITY_MPS
:canonical: space_flight.ai.REFERENCE_ERROR_VELOCITY_MPS
:value: >
   100

```{autodoc2-docstring} space_flight.ai.REFERENCE_ERROR_VELOCITY_MPS
```

````

````{py:data} ROLL_TOLERANCE
:canonical: space_flight.ai.ROLL_TOLERANCE
:value: >
   0.01

```{autodoc2-docstring} space_flight.ai.ROLL_TOLERANCE
```

````

````{py:data} HALF_PI
:canonical: space_flight.ai.HALF_PI
:value: >
   None

```{autodoc2-docstring} space_flight.ai.HALF_PI
```

````

````{py:data} LOGGER
:canonical: space_flight.ai.LOGGER
:value: >
   'getLogger(...)'

```{autodoc2-docstring} space_flight.ai.LOGGER
```

````

`````{py:class} Intent(*args, **kwds)
:canonical: space_flight.ai.Intent

Bases: {py:obj}`enum.Enum`

```{autodoc2-docstring} space_flight.ai.Intent
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.ai.Intent.__init__
```

````{py:attribute} ENGAGE
:canonical: space_flight.ai.Intent.ENGAGE
:value: >
   'auto(...)'

```{autodoc2-docstring} space_flight.ai.Intent.ENGAGE
```

````

````{py:attribute} EVADE
:canonical: space_flight.ai.Intent.EVADE
:value: >
   'auto(...)'

```{autodoc2-docstring} space_flight.ai.Intent.EVADE
```

````

````{py:attribute} DISENGAGE
:canonical: space_flight.ai.Intent.DISENGAGE
:value: >
   'auto(...)'

```{autodoc2-docstring} space_flight.ai.Intent.DISENGAGE
```

````

````{py:attribute} REGROUP
:canonical: space_flight.ai.Intent.REGROUP
:value: >
   'auto(...)'

```{autodoc2-docstring} space_flight.ai.Intent.REGROUP
```

````

````{py:attribute} PATROL
:canonical: space_flight.ai.Intent.PATROL
:value: >
   'auto(...)'

```{autodoc2-docstring} space_flight.ai.Intent.PATROL
```

````

````{py:attribute} FORMATION
:canonical: space_flight.ai.Intent.FORMATION
:value: >
   'auto(...)'

```{autodoc2-docstring} space_flight.ai.Intent.FORMATION
```

````

````{py:attribute} IDLE
:canonical: space_flight.ai.Intent.IDLE
:value: >
   'auto(...)'

```{autodoc2-docstring} space_flight.ai.Intent.IDLE
```

````

`````

`````{py:class} AttackMode(*args, **kwds)
:canonical: space_flight.ai.AttackMode

Bases: {py:obj}`enum.Enum`

```{autodoc2-docstring} space_flight.ai.AttackMode
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.ai.AttackMode.__init__
```

````{py:attribute} PURSUIT
:canonical: space_flight.ai.AttackMode.PURSUIT
:value: >
   'auto(...)'

```{autodoc2-docstring} space_flight.ai.AttackMode.PURSUIT
```

````

````{py:attribute} STRAFE
:canonical: space_flight.ai.AttackMode.STRAFE
:value: >
   'auto(...)'

```{autodoc2-docstring} space_flight.ai.AttackMode.STRAFE
```

````

````{py:attribute} ORBIT
:canonical: space_flight.ai.AttackMode.ORBIT
:value: >
   'auto(...)'

```{autodoc2-docstring} space_flight.ai.AttackMode.ORBIT
```

````

````{py:attribute} BOMB
:canonical: space_flight.ai.AttackMode.BOMB
:value: >
   'auto(...)'

```{autodoc2-docstring} space_flight.ai.AttackMode.BOMB
```

````

`````

`````{py:class} Personality
:canonical: space_flight.ai.Personality

```{autodoc2-docstring} space_flight.ai.Personality
```

````{py:attribute} FIGHTER_DEFAULT
:canonical: space_flight.ai.Personality.FIGHTER_DEFAULT
:value: >
   None

```{autodoc2-docstring} space_flight.ai.Personality.FIGHTER_DEFAULT
```

````

````{py:attribute} TURRET_DEFAULT
:canonical: space_flight.ai.Personality.TURRET_DEFAULT
:value: >
   None

```{autodoc2-docstring} space_flight.ai.Personality.TURRET_DEFAULT
```

````

````{py:attribute} TRACTOR_BEAM_DEFAULT
:canonical: space_flight.ai.Personality.TRACTOR_BEAM_DEFAULT
:value: >
   None

```{autodoc2-docstring} space_flight.ai.Personality.TRACTOR_BEAM_DEFAULT
```

````

````{py:attribute} CAPITAL_SHIP_DEFAULT
:canonical: space_flight.ai.Personality.CAPITAL_SHIP_DEFAULT
:value: >
   None

```{autodoc2-docstring} space_flight.ai.Personality.CAPITAL_SHIP_DEFAULT
```

````

`````

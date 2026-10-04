# {py:mod}`space_flight.weapons.ordnance_launcher`

```{py:module} space_flight.weapons.ordnance_launcher
```

```{autodoc2-docstring} space_flight.weapons.ordnance_launcher
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`OrdnanceLauncher <space_flight.weapons.ordnance_launcher.OrdnanceLauncher>`
  - ```{autodoc2-docstring} space_flight.weapons.ordnance_launcher.OrdnanceLauncher
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_read_ordnance_configuration <space_flight.weapons.ordnance_launcher._read_ordnance_configuration>`
  - ```{autodoc2-docstring} space_flight.weapons.ordnance_launcher._read_ordnance_configuration
    :summary:
    ```
* - {py:obj}`load_ordnance_configuration <space_flight.weapons.ordnance_launcher.load_ordnance_configuration>`
  - ```{autodoc2-docstring} space_flight.weapons.ordnance_launcher.load_ordnance_configuration
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`LOGGER <space_flight.weapons.ordnance_launcher.LOGGER>`
  - ```{autodoc2-docstring} space_flight.weapons.ordnance_launcher.LOGGER
    :summary:
    ```
* - {py:obj}`ORDNANCE_PATH <space_flight.weapons.ordnance_launcher.ORDNANCE_PATH>`
  - ```{autodoc2-docstring} space_flight.weapons.ordnance_launcher.ORDNANCE_PATH
    :summary:
    ```
* - {py:obj}`ORDNANCE_TYPES <space_flight.weapons.ordnance_launcher.ORDNANCE_TYPES>`
  - ```{autodoc2-docstring} space_flight.weapons.ordnance_launcher.ORDNANCE_TYPES
    :summary:
    ```
* - {py:obj}`SECONDARY_TYPES <space_flight.weapons.ordnance_launcher.SECONDARY_TYPES>`
  - ```{autodoc2-docstring} space_flight.weapons.ordnance_launcher.SECONDARY_TYPES
    :summary:
    ```
* - {py:obj}`LAUNCH_DIRECTIONS <space_flight.weapons.ordnance_launcher.LAUNCH_DIRECTIONS>`
  - ```{autodoc2-docstring} space_flight.weapons.ordnance_launcher.LAUNCH_DIRECTIONS
    :summary:
    ```
* - {py:obj}`DAMAGE_TYPES <space_flight.weapons.ordnance_launcher.DAMAGE_TYPES>`
  - ```{autodoc2-docstring} space_flight.weapons.ordnance_launcher.DAMAGE_TYPES
    :summary:
    ```
````

### API

````{py:data} LOGGER
:canonical: space_flight.weapons.ordnance_launcher.LOGGER
:value: >
   'getLogger(...)'

```{autodoc2-docstring} space_flight.weapons.ordnance_launcher.LOGGER
```

````

````{py:data} ORDNANCE_PATH
:canonical: space_flight.weapons.ordnance_launcher.ORDNANCE_PATH
:value: >
   None

```{autodoc2-docstring} space_flight.weapons.ordnance_launcher.ORDNANCE_PATH
```

````

````{py:data} ORDNANCE_TYPES
:canonical: space_flight.weapons.ordnance_launcher.ORDNANCE_TYPES
:value: >
   ('bomb', 'rocket', 'missile', 'flare')

```{autodoc2-docstring} space_flight.weapons.ordnance_launcher.ORDNANCE_TYPES
```

````

````{py:data} SECONDARY_TYPES
:canonical: space_flight.weapons.ordnance_launcher.SECONDARY_TYPES
:value: >
   ('bomb', 'rocket', 'missile')

```{autodoc2-docstring} space_flight.weapons.ordnance_launcher.SECONDARY_TYPES
```

````

````{py:data} LAUNCH_DIRECTIONS
:canonical: space_flight.weapons.ordnance_launcher.LAUNCH_DIRECTIONS
:value: >
   ('forward', 'down', 'backward')

```{autodoc2-docstring} space_flight.weapons.ordnance_launcher.LAUNCH_DIRECTIONS
```

````

````{py:data} DAMAGE_TYPES
:canonical: space_flight.weapons.ordnance_launcher.DAMAGE_TYPES
:value: >
   ('physical',)

```{autodoc2-docstring} space_flight.weapons.ordnance_launcher.DAMAGE_TYPES
```

````

````{py:function} _read_ordnance_configuration(name: str) -> dict
:canonical: space_flight.weapons.ordnance_launcher._read_ordnance_configuration

```{autodoc2-docstring} space_flight.weapons.ordnance_launcher._read_ordnance_configuration
```
````

````{py:function} load_ordnance_configuration(name: str) -> dict
:canonical: space_flight.weapons.ordnance_launcher.load_ordnance_configuration

```{autodoc2-docstring} space_flight.weapons.ordnance_launcher.load_ordnance_configuration
```
````

`````{py:class} OrdnanceLauncher(game: space_flight.game.flight_state.FlightState, parent: space_flight.actors.fighter.Fighter, name: str, stock: int)
:canonical: space_flight.weapons.ordnance_launcher.OrdnanceLauncher

Bases: {py:obj}`space_flight.weapons.Weapon`

```{autodoc2-docstring} space_flight.weapons.ordnance_launcher.OrdnanceLauncher
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.weapons.ordnance_launcher.OrdnanceLauncher.__init__
```

````{py:property} display_name
:canonical: space_flight.weapons.ordnance_launcher.OrdnanceLauncher.display_name
:type: str

```{autodoc2-docstring} space_flight.weapons.ordnance_launcher.OrdnanceLauncher.display_name
```

````

````{py:method} launch_direction_vector() -> numpy.ndarray
:canonical: space_flight.weapons.ordnance_launcher.OrdnanceLauncher.launch_direction_vector

```{autodoc2-docstring} space_flight.weapons.ordnance_launcher.OrdnanceLauncher.launch_direction_vector
```

````

````{py:method} initial_velocity() -> numpy.ndarray
:canonical: space_flight.weapons.ordnance_launcher.OrdnanceLauncher.initial_velocity

```{autodoc2-docstring} space_flight.weapons.ordnance_launcher.OrdnanceLauncher.initial_velocity
```

````

````{py:method} launch(target_id: uuid.UUID | None = None) -> bool
:canonical: space_flight.weapons.ordnance_launcher.OrdnanceLauncher.launch

```{autodoc2-docstring} space_flight.weapons.ordnance_launcher.OrdnanceLauncher.launch
```

````

````{py:property} is_locked
:canonical: space_flight.weapons.ordnance_launcher.OrdnanceLauncher.is_locked
:type: bool

```{autodoc2-docstring} space_flight.weapons.ordnance_launcher.OrdnanceLauncher.is_locked
```

````

````{py:method} clean()
:canonical: space_flight.weapons.ordnance_launcher.OrdnanceLauncher.clean

```{autodoc2-docstring} space_flight.weapons.ordnance_launcher.OrdnanceLauncher.clean
```

````

`````

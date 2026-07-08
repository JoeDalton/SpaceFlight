# {py:mod}`space_flight.global_architecture.simulator`

```{py:module} space_flight.global_architecture.simulator
```

```{autodoc2-docstring} space_flight.global_architecture.simulator
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`StateManager <space_flight.global_architecture.simulator.StateManager>`
  - ```{autodoc2-docstring} space_flight.global_architecture.simulator.StateManager
    :summary:
    ```
* - {py:obj}`SpaceFlightSimulator <space_flight.global_architecture.simulator.SpaceFlightSimulator>`
  - ```{autodoc2-docstring} space_flight.global_architecture.simulator.SpaceFlightSimulator
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`LOGGER <space_flight.global_architecture.simulator.LOGGER>`
  - ```{autodoc2-docstring} space_flight.global_architecture.simulator.LOGGER
    :summary:
    ```
````

### API

````{py:data} LOGGER
:canonical: space_flight.global_architecture.simulator.LOGGER
:value: >
   'getLogger(...)'

```{autodoc2-docstring} space_flight.global_architecture.simulator.LOGGER
```

````

`````{py:class} StateManager(app)
:canonical: space_flight.global_architecture.simulator.StateManager

```{autodoc2-docstring} space_flight.global_architecture.simulator.StateManager
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.global_architecture.simulator.StateManager.__init__
```

````{py:attribute} SPLASH_STATE
:canonical: space_flight.global_architecture.simulator.StateManager.SPLASH_STATE
:value: >
   None

```{autodoc2-docstring} space_flight.global_architecture.simulator.StateManager.SPLASH_STATE
```

````

````{py:attribute} MAIN_MENU_STATE
:canonical: space_flight.global_architecture.simulator.StateManager.MAIN_MENU_STATE
:value: >
   None

```{autodoc2-docstring} space_flight.global_architecture.simulator.StateManager.MAIN_MENU_STATE
```

````

````{py:attribute} LEVEL_SELECTION_MENU_STATE
:canonical: space_flight.global_architecture.simulator.StateManager.LEVEL_SELECTION_MENU_STATE
:value: >
   None

```{autodoc2-docstring} space_flight.global_architecture.simulator.StateManager.LEVEL_SELECTION_MENU_STATE
```

````

````{py:attribute} PAUSE_MENU_STATE
:canonical: space_flight.global_architecture.simulator.StateManager.PAUSE_MENU_STATE
:value: >
   None

```{autodoc2-docstring} space_flight.global_architecture.simulator.StateManager.PAUSE_MENU_STATE
```

````

````{py:attribute} SETTINGS_STATE
:canonical: space_flight.global_architecture.simulator.StateManager.SETTINGS_STATE
:value: >
   None

```{autodoc2-docstring} space_flight.global_architecture.simulator.StateManager.SETTINGS_STATE
```

````

````{py:attribute} INPUT_SETTINGS_STATE
:canonical: space_flight.global_architecture.simulator.StateManager.INPUT_SETTINGS_STATE
:value: >
   None

```{autodoc2-docstring} space_flight.global_architecture.simulator.StateManager.INPUT_SETTINGS_STATE
```

````

````{py:attribute} GRAPHICS_SETTINGS_STATE
:canonical: space_flight.global_architecture.simulator.StateManager.GRAPHICS_SETTINGS_STATE
:value: >
   None

```{autodoc2-docstring} space_flight.global_architecture.simulator.StateManager.GRAPHICS_SETTINGS_STATE
```

````

````{py:attribute} RADIAL_MENU_STATE
:canonical: space_flight.global_architecture.simulator.StateManager.RADIAL_MENU_STATE
:value: >
   None

```{autodoc2-docstring} space_flight.global_architecture.simulator.StateManager.RADIAL_MENU_STATE
```

````

````{py:attribute} LEVEL_END_STATE
:canonical: space_flight.global_architecture.simulator.StateManager.LEVEL_END_STATE
:value: >
   None

```{autodoc2-docstring} space_flight.global_architecture.simulator.StateManager.LEVEL_END_STATE
```

````

````{py:attribute} GAME_STATE
:canonical: space_flight.global_architecture.simulator.StateManager.GAME_STATE
:value: >
   None

```{autodoc2-docstring} space_flight.global_architecture.simulator.StateManager.GAME_STATE
```

````

````{py:attribute} LOADING_STATE
:canonical: space_flight.global_architecture.simulator.StateManager.LOADING_STATE
:value: >
   None

```{autodoc2-docstring} space_flight.global_architecture.simulator.StateManager.LOADING_STATE
```

````

````{py:attribute} HYPERSPACE_LOADING_STATE
:canonical: space_flight.global_architecture.simulator.StateManager.HYPERSPACE_LOADING_STATE
:value: >
   None

```{autodoc2-docstring} space_flight.global_architecture.simulator.StateManager.HYPERSPACE_LOADING_STATE
```

````

````{py:method} push(state_class: space_flight.global_architecture.base_state.BaseState, **kwargs)
:canonical: space_flight.global_architecture.simulator.StateManager.push

```{autodoc2-docstring} space_flight.global_architecture.simulator.StateManager.push
```

````

````{py:method} pop()
:canonical: space_flight.global_architecture.simulator.StateManager.pop

```{autodoc2-docstring} space_flight.global_architecture.simulator.StateManager.pop
```

````

````{py:method} replace(state_class: space_flight.global_architecture.base_state.BaseState)
:canonical: space_flight.global_architecture.simulator.StateManager.replace

```{autodoc2-docstring} space_flight.global_architecture.simulator.StateManager.replace
```

````

````{py:method} get_current()
:canonical: space_flight.global_architecture.simulator.StateManager.get_current

```{autodoc2-docstring} space_flight.global_architecture.simulator.StateManager.get_current
```

````

````{py:method} clear()
:canonical: space_flight.global_architecture.simulator.StateManager.clear

```{autodoc2-docstring} space_flight.global_architecture.simulator.StateManager.clear
```

````

`````

`````{py:class} SpaceFlightSimulator()
:canonical: space_flight.global_architecture.simulator.SpaceFlightSimulator

Bases: {py:obj}`direct.showbase.ShowBase.ShowBase`

```{autodoc2-docstring} space_flight.global_architecture.simulator.SpaceFlightSimulator
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.global_architecture.simulator.SpaceFlightSimulator.__init__
```

````{py:method} input_task(task)
:canonical: space_flight.global_architecture.simulator.SpaceFlightSimulator.input_task

```{autodoc2-docstring} space_flight.global_architecture.simulator.SpaceFlightSimulator.input_task
```

````

`````

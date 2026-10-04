# {py:mod}`space_flight.global_architecture.gameplay_settings`

```{py:module} space_flight.global_architecture.gameplay_settings
```

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`GameplaySettings <space_flight.global_architecture.gameplay_settings.GameplaySettings>`
  - ```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.GameplaySettings
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_clamp <space_flight.global_architecture.gameplay_settings._clamp>`
  - ```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings._clamp
    :summary:
    ```
* - {py:obj}`_load_file <space_flight.global_architecture.gameplay_settings._load_file>`
  - ```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings._load_file
    :summary:
    ```
* - {py:obj}`load_presets <space_flight.global_architecture.gameplay_settings.load_presets>`
  - ```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.load_presets
    :summary:
    ```
* - {py:obj}`_with_preset <space_flight.global_architecture.gameplay_settings._with_preset>`
  - ```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings._with_preset
    :summary:
    ```
* - {py:obj}`_default_config <space_flight.global_architecture.gameplay_settings._default_config>`
  - ```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings._default_config
    :summary:
    ```
* - {py:obj}`gameplay_config <space_flight.global_architecture.gameplay_settings.gameplay_config>`
  - ```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.gameplay_config
    :summary:
    ```
* - {py:obj}`auto_aim_params <space_flight.global_architecture.gameplay_settings.auto_aim_params>`
  - ```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.auto_aim_params
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`LOGGER <space_flight.global_architecture.gameplay_settings.LOGGER>`
  - ```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.LOGGER
    :summary:
    ```
* - {py:obj}`GAMEPLAY_FILE <space_flight.global_architecture.gameplay_settings.GAMEPLAY_FILE>`
  - ```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.GAMEPLAY_FILE
    :summary:
    ```
* - {py:obj}`PRESETS_FILE <space_flight.global_architecture.gameplay_settings.PRESETS_FILE>`
  - ```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.PRESETS_FILE
    :summary:
    ```
* - {py:obj}`DEFAULT_PRESET <space_flight.global_architecture.gameplay_settings.DEFAULT_PRESET>`
  - ```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.DEFAULT_PRESET
    :summary:
    ```
* - {py:obj}`CUSTOM_PRESET <space_flight.global_architecture.gameplay_settings.CUSTOM_PRESET>`
  - ```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.CUSTOM_PRESET
    :summary:
    ```
* - {py:obj}`SIDES <space_flight.global_architecture.gameplay_settings.SIDES>`
  - ```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.SIDES
    :summary:
    ```
* - {py:obj}`_AUTO_AIM_LIMITS <space_flight.global_architecture.gameplay_settings._AUTO_AIM_LIMITS>`
  - ```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings._AUTO_AIM_LIMITS
    :summary:
    ```
* - {py:obj}`_DEVIATION_LIMITS <space_flight.global_architecture.gameplay_settings._DEVIATION_LIMITS>`
  - ```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings._DEVIATION_LIMITS
    :summary:
    ```
* - {py:obj}`_DAMAGE_MULTIPLIER_LIMITS <space_flight.global_architecture.gameplay_settings._DAMAGE_MULTIPLIER_LIMITS>`
  - ```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings._DAMAGE_MULTIPLIER_LIMITS
    :summary:
    ```
* - {py:obj}`_COLLISION_DAMAGE_MULTIPLIER_LIMITS <space_flight.global_architecture.gameplay_settings._COLLISION_DAMAGE_MULTIPLIER_LIMITS>`
  - ```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings._COLLISION_DAMAGE_MULTIPLIER_LIMITS
    :summary:
    ```
````

### API

````{py:data} LOGGER
:canonical: space_flight.global_architecture.gameplay_settings.LOGGER
:value: >
   'getLogger(...)'

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.LOGGER
```

````

````{py:data} GAMEPLAY_FILE
:canonical: space_flight.global_architecture.gameplay_settings.GAMEPLAY_FILE
:value: >
   None

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.GAMEPLAY_FILE
```

````

````{py:data} PRESETS_FILE
:canonical: space_flight.global_architecture.gameplay_settings.PRESETS_FILE
:value: >
   None

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.PRESETS_FILE
```

````

````{py:data} DEFAULT_PRESET
:canonical: space_flight.global_architecture.gameplay_settings.DEFAULT_PRESET
:value: >
   'normal'

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.DEFAULT_PRESET
```

````

````{py:data} CUSTOM_PRESET
:canonical: space_flight.global_architecture.gameplay_settings.CUSTOM_PRESET
:value: >
   'custom'

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.CUSTOM_PRESET
```

````

````{py:data} SIDES
:canonical: space_flight.global_architecture.gameplay_settings.SIDES
:value: >
   ('player', 'bots')

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.SIDES
```

````

````{py:data} _AUTO_AIM_LIMITS
:canonical: space_flight.global_architecture.gameplay_settings._AUTO_AIM_LIMITS
:value: >
   None

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings._AUTO_AIM_LIMITS
```

````

````{py:data} _DEVIATION_LIMITS
:canonical: space_flight.global_architecture.gameplay_settings._DEVIATION_LIMITS
:value: >
   (0.0, 5.0, 0.0)

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings._DEVIATION_LIMITS
```

````

````{py:data} _DAMAGE_MULTIPLIER_LIMITS
:canonical: space_flight.global_architecture.gameplay_settings._DAMAGE_MULTIPLIER_LIMITS
:value: >
   (0.1, 5.0, 1.0)

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings._DAMAGE_MULTIPLIER_LIMITS
```

````

````{py:data} _COLLISION_DAMAGE_MULTIPLIER_LIMITS
:canonical: space_flight.global_architecture.gameplay_settings._COLLISION_DAMAGE_MULTIPLIER_LIMITS
:value: >
   (0.0, 5.0, 1.0)

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings._COLLISION_DAMAGE_MULTIPLIER_LIMITS
```

````

````{py:function} _clamp(value, limits: tuple[float, float, float]) -> float
:canonical: space_flight.global_architecture.gameplay_settings._clamp

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings._clamp
```
````

````{py:function} _load_file(path: pathlib.Path) -> dict
:canonical: space_flight.global_architecture.gameplay_settings._load_file

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings._load_file
```
````

````{py:function} load_presets() -> dict[str, dict]
:canonical: space_flight.global_architecture.gameplay_settings.load_presets

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.load_presets
```
````

`````{py:class} GameplaySettings()
:canonical: space_flight.global_architecture.gameplay_settings.GameplaySettings

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.GameplaySettings
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.GameplaySettings.__init__
```

````{py:method} load() -> dict
:canonical: space_flight.global_architecture.gameplay_settings.GameplaySettings.load

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.GameplaySettings.load
```

````

````{py:method} resolve(config: dict) -> dict
:canonical: space_flight.global_architecture.gameplay_settings.GameplaySettings.resolve

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.GameplaySettings.resolve
```

````

````{py:method} save(config: dict)
:canonical: space_flight.global_architecture.gameplay_settings.GameplaySettings.save

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.GameplaySettings.save
```

````

````{py:method} sanitise(config: dict) -> dict
:canonical: space_flight.global_architecture.gameplay_settings.GameplaySettings.sanitise
:staticmethod:

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.GameplaySettings.sanitise
```

````

`````

````{py:function} _with_preset(preset: str, values: dict) -> dict
:canonical: space_flight.global_architecture.gameplay_settings._with_preset

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings._with_preset
```
````

````{py:function} _default_config() -> dict
:canonical: space_flight.global_architecture.gameplay_settings._default_config

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings._default_config
```
````

````{py:function} gameplay_config(game) -> dict
:canonical: space_flight.global_architecture.gameplay_settings.gameplay_config

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.gameplay_config
```
````

````{py:function} auto_aim_params(game, side: str) -> dict
:canonical: space_flight.global_architecture.gameplay_settings.auto_aim_params

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.auto_aim_params
```
````

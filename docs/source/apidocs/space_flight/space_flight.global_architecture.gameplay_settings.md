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

* - {py:obj}`side_paths <space_flight.global_architecture.gameplay_settings.side_paths>`
  - ```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.side_paths
    :summary:
    ```
* - {py:obj}`_get_path <space_flight.global_architecture.gameplay_settings._get_path>`
  - ```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings._get_path
    :summary:
    ```
* - {py:obj}`_set_path <space_flight.global_architecture.gameplay_settings._set_path>`
  - ```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings._set_path
    :summary:
    ```
* - {py:obj}`_clean <space_flight.global_architecture.gameplay_settings._clean>`
  - ```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings._clean
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
* - {py:obj}`LIMITS <space_flight.global_architecture.gameplay_settings.LIMITS>`
  - ```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.LIMITS
    :summary:
    ```
* - {py:obj}`FLAGS <space_flight.global_architecture.gameplay_settings.FLAGS>`
  - ```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.FLAGS
    :summary:
    ```
* - {py:obj}`PLAYER_ONLY <space_flight.global_architecture.gameplay_settings.PLAYER_ONLY>`
  - ```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.PLAYER_ONLY
    :summary:
    ```
* - {py:obj}`_MISSING <space_flight.global_architecture.gameplay_settings._MISSING>`
  - ```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings._MISSING
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

````{py:data} LIMITS
:canonical: space_flight.global_architecture.gameplay_settings.LIMITS
:value: >
   None

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.LIMITS
```

````

````{py:data} FLAGS
:canonical: space_flight.global_architecture.gameplay_settings.FLAGS
:value: >
   (('auto_aim', 'enabled'), ('lead_indicator',))

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.FLAGS
```

````

````{py:data} PLAYER_ONLY
:canonical: space_flight.global_architecture.gameplay_settings.PLAYER_ONLY
:value: >
   (('collision_damage_multiplier',), ('lead_indicator',))

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.PLAYER_ONLY
```

````

````{py:data} _MISSING
:canonical: space_flight.global_architecture.gameplay_settings._MISSING
:value: >
   'object(...)'

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings._MISSING
```

````

````{py:function} side_paths(side: str) -> list[tuple]
:canonical: space_flight.global_architecture.gameplay_settings.side_paths

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings.side_paths
```
````

````{py:function} _get_path(section, path: tuple)
:canonical: space_flight.global_architecture.gameplay_settings._get_path

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings._get_path
```
````

````{py:function} _set_path(section: dict, path: tuple, value)
:canonical: space_flight.global_architecture.gameplay_settings._set_path

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings._set_path
```
````

````{py:function} _clean(path: tuple, value, fallback)
:canonical: space_flight.global_architecture.gameplay_settings._clean

```{autodoc2-docstring} space_flight.global_architecture.gameplay_settings._clean
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

````{py:method} sanitise(config: dict, fallback: dict) -> dict
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

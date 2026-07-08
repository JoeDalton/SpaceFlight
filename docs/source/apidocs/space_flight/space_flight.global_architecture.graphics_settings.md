# {py:mod}`space_flight.global_architecture.graphics_settings`

```{py:module} space_flight.global_architecture.graphics_settings
```

```{autodoc2-docstring} space_flight.global_architecture.graphics_settings
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`GraphicsSettings <space_flight.global_architecture.graphics_settings.GraphicsSettings>`
  - ```{autodoc2-docstring} space_flight.global_architecture.graphics_settings.GraphicsSettings
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`_deep_merge <space_flight.global_architecture.graphics_settings._deep_merge>`
  - ```{autodoc2-docstring} space_flight.global_architecture.graphics_settings._deep_merge
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`LOGGER <space_flight.global_architecture.graphics_settings.LOGGER>`
  - ```{autodoc2-docstring} space_flight.global_architecture.graphics_settings.LOGGER
    :summary:
    ```
* - {py:obj}`GRAPHICS_FILE <space_flight.global_architecture.graphics_settings.GRAPHICS_FILE>`
  - ```{autodoc2-docstring} space_flight.global_architecture.graphics_settings.GRAPHICS_FILE
    :summary:
    ```
* - {py:obj}`DEFAULT_GRAPHICS_FILE <space_flight.global_architecture.graphics_settings.DEFAULT_GRAPHICS_FILE>`
  - ```{autodoc2-docstring} space_flight.global_architecture.graphics_settings.DEFAULT_GRAPHICS_FILE
    :summary:
    ```
* - {py:obj}`_VALID_MODES <space_flight.global_architecture.graphics_settings._VALID_MODES>`
  - ```{autodoc2-docstring} space_flight.global_architecture.graphics_settings._VALID_MODES
    :summary:
    ```
* - {py:obj}`_VALID_MSAA <space_flight.global_architecture.graphics_settings._VALID_MSAA>`
  - ```{autodoc2-docstring} space_flight.global_architecture.graphics_settings._VALID_MSAA
    :summary:
    ```
* - {py:obj}`_MIN_SCALE <space_flight.global_architecture.graphics_settings._MIN_SCALE>`
  - ```{autodoc2-docstring} space_flight.global_architecture.graphics_settings._MIN_SCALE
    :summary:
    ```
* - {py:obj}`_MAX_SCALE <space_flight.global_architecture.graphics_settings._MAX_SCALE>`
  - ```{autodoc2-docstring} space_flight.global_architecture.graphics_settings._MAX_SCALE
    :summary:
    ```
* - {py:obj}`_MIN_REFLECTION <space_flight.global_architecture.graphics_settings._MIN_REFLECTION>`
  - ```{autodoc2-docstring} space_flight.global_architecture.graphics_settings._MIN_REFLECTION
    :summary:
    ```
* - {py:obj}`_MAX_REFLECTION <space_flight.global_architecture.graphics_settings._MAX_REFLECTION>`
  - ```{autodoc2-docstring} space_flight.global_architecture.graphics_settings._MAX_REFLECTION
    :summary:
    ```
* - {py:obj}`_MIN_MIRROR <space_flight.global_architecture.graphics_settings._MIN_MIRROR>`
  - ```{autodoc2-docstring} space_flight.global_architecture.graphics_settings._MIN_MIRROR
    :summary:
    ```
* - {py:obj}`_MAX_MIRROR <space_flight.global_architecture.graphics_settings._MAX_MIRROR>`
  - ```{autodoc2-docstring} space_flight.global_architecture.graphics_settings._MAX_MIRROR
    :summary:
    ```
````

### API

````{py:data} LOGGER
:canonical: space_flight.global_architecture.graphics_settings.LOGGER
:value: >
   'getLogger(...)'

```{autodoc2-docstring} space_flight.global_architecture.graphics_settings.LOGGER
```

````

````{py:data} GRAPHICS_FILE
:canonical: space_flight.global_architecture.graphics_settings.GRAPHICS_FILE
:value: >
   None

```{autodoc2-docstring} space_flight.global_architecture.graphics_settings.GRAPHICS_FILE
```

````

````{py:data} DEFAULT_GRAPHICS_FILE
:canonical: space_flight.global_architecture.graphics_settings.DEFAULT_GRAPHICS_FILE
:value: >
   None

```{autodoc2-docstring} space_flight.global_architecture.graphics_settings.DEFAULT_GRAPHICS_FILE
```

````

````{py:data} _VALID_MODES
:canonical: space_flight.global_architecture.graphics_settings._VALID_MODES
:value: >
   ('fullscreen', 'windowed')

```{autodoc2-docstring} space_flight.global_architecture.graphics_settings._VALID_MODES
```

````

````{py:data} _VALID_MSAA
:canonical: space_flight.global_architecture.graphics_settings._VALID_MSAA
:value: >
   (0, 2, 4, 8)

```{autodoc2-docstring} space_flight.global_architecture.graphics_settings._VALID_MSAA
```

````

````{py:data} _MIN_SCALE
:canonical: space_flight.global_architecture.graphics_settings._MIN_SCALE
:value: >
   0.25

```{autodoc2-docstring} space_flight.global_architecture.graphics_settings._MIN_SCALE
```

````

````{py:data} _MAX_SCALE
:canonical: space_flight.global_architecture.graphics_settings._MAX_SCALE
:value: >
   1.0

```{autodoc2-docstring} space_flight.global_architecture.graphics_settings._MAX_SCALE
```

````

````{py:data} _MIN_REFLECTION
:canonical: space_flight.global_architecture.graphics_settings._MIN_REFLECTION
:value: >
   0.1

```{autodoc2-docstring} space_flight.global_architecture.graphics_settings._MIN_REFLECTION
```

````

````{py:data} _MAX_REFLECTION
:canonical: space_flight.global_architecture.graphics_settings._MAX_REFLECTION
:value: >
   1.0

```{autodoc2-docstring} space_flight.global_architecture.graphics_settings._MAX_REFLECTION
```

````

````{py:data} _MIN_MIRROR
:canonical: space_flight.global_architecture.graphics_settings._MIN_MIRROR
:value: >
   0.5

```{autodoc2-docstring} space_flight.global_architecture.graphics_settings._MIN_MIRROR
```

````

````{py:data} _MAX_MIRROR
:canonical: space_flight.global_architecture.graphics_settings._MAX_MIRROR
:value: >
   2.0

```{autodoc2-docstring} space_flight.global_architecture.graphics_settings._MAX_MIRROR
```

````

````{py:function} _deep_merge(base: dict, override: dict) -> dict
:canonical: space_flight.global_architecture.graphics_settings._deep_merge

```{autodoc2-docstring} space_flight.global_architecture.graphics_settings._deep_merge
```
````

`````{py:class} GraphicsSettings()
:canonical: space_flight.global_architecture.graphics_settings.GraphicsSettings

```{autodoc2-docstring} space_flight.global_architecture.graphics_settings.GraphicsSettings
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.global_architecture.graphics_settings.GraphicsSettings.__init__
```

````{py:method} load_file(path) -> dict
:canonical: space_flight.global_architecture.graphics_settings.GraphicsSettings.load_file
:staticmethod:

```{autodoc2-docstring} space_flight.global_architecture.graphics_settings.GraphicsSettings.load_file
```

````

````{py:method} load() -> dict
:canonical: space_flight.global_architecture.graphics_settings.GraphicsSettings.load

```{autodoc2-docstring} space_flight.global_architecture.graphics_settings.GraphicsSettings.load
```

````

````{py:method} save(config: dict)
:canonical: space_flight.global_architecture.graphics_settings.GraphicsSettings.save

```{autodoc2-docstring} space_flight.global_architecture.graphics_settings.GraphicsSettings.save
```

````

````{py:method} reset_to_default() -> dict
:canonical: space_flight.global_architecture.graphics_settings.GraphicsSettings.reset_to_default

```{autodoc2-docstring} space_flight.global_architecture.graphics_settings.GraphicsSettings.reset_to_default
```

````

````{py:method} sanitise(config: dict) -> dict
:canonical: space_flight.global_architecture.graphics_settings.GraphicsSettings.sanitise
:staticmethod:

```{autodoc2-docstring} space_flight.global_architecture.graphics_settings.GraphicsSettings.sanitise
```

````

`````

# {py:mod}`space_flight.global_architecture.idle_inhibitor`

```{py:module} space_flight.global_architecture.idle_inhibitor
```

```{autodoc2-docstring} space_flight.global_architecture.idle_inhibitor
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`IdleInhibitor <space_flight.global_architecture.idle_inhibitor.IdleInhibitor>`
  - ```{autodoc2-docstring} space_flight.global_architecture.idle_inhibitor.IdleInhibitor
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`LOGGER <space_flight.global_architecture.idle_inhibitor.LOGGER>`
  - ```{autodoc2-docstring} space_flight.global_architecture.idle_inhibitor.LOGGER
    :summary:
    ```
* - {py:obj}`_APP_NAME <space_flight.global_architecture.idle_inhibitor._APP_NAME>`
  - ```{autodoc2-docstring} space_flight.global_architecture.idle_inhibitor._APP_NAME
    :summary:
    ```
* - {py:obj}`_REASON <space_flight.global_architecture.idle_inhibitor._REASON>`
  - ```{autodoc2-docstring} space_flight.global_architecture.idle_inhibitor._REASON
    :summary:
    ```
* - {py:obj}`_ES_CONTINUOUS <space_flight.global_architecture.idle_inhibitor._ES_CONTINUOUS>`
  - ```{autodoc2-docstring} space_flight.global_architecture.idle_inhibitor._ES_CONTINUOUS
    :summary:
    ```
* - {py:obj}`_ES_DISPLAY_REQUIRED <space_flight.global_architecture.idle_inhibitor._ES_DISPLAY_REQUIRED>`
  - ```{autodoc2-docstring} space_flight.global_architecture.idle_inhibitor._ES_DISPLAY_REQUIRED
    :summary:
    ```
````

### API

````{py:data} LOGGER
:canonical: space_flight.global_architecture.idle_inhibitor.LOGGER
:value: >
   'getLogger(...)'

```{autodoc2-docstring} space_flight.global_architecture.idle_inhibitor.LOGGER
```

````

````{py:data} _APP_NAME
:canonical: space_flight.global_architecture.idle_inhibitor._APP_NAME
:value: >
   'SpaceFlight'

```{autodoc2-docstring} space_flight.global_architecture.idle_inhibitor._APP_NAME
```

````

````{py:data} _REASON
:canonical: space_flight.global_architecture.idle_inhibitor._REASON
:value: >
   'Playing'

```{autodoc2-docstring} space_flight.global_architecture.idle_inhibitor._REASON
```

````

````{py:data} _ES_CONTINUOUS
:canonical: space_flight.global_architecture.idle_inhibitor._ES_CONTINUOUS
:value: >
   2147483648

```{autodoc2-docstring} space_flight.global_architecture.idle_inhibitor._ES_CONTINUOUS
```

````

````{py:data} _ES_DISPLAY_REQUIRED
:canonical: space_flight.global_architecture.idle_inhibitor._ES_DISPLAY_REQUIRED
:value: >
   2

```{autodoc2-docstring} space_flight.global_architecture.idle_inhibitor._ES_DISPLAY_REQUIRED
```

````

`````{py:class} IdleInhibitor()
:canonical: space_flight.global_architecture.idle_inhibitor.IdleInhibitor

```{autodoc2-docstring} space_flight.global_architecture.idle_inhibitor.IdleInhibitor
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.global_architecture.idle_inhibitor.IdleInhibitor.__init__
```

````{py:property} active
:canonical: space_flight.global_architecture.idle_inhibitor.IdleInhibitor.active
:type: bool

```{autodoc2-docstring} space_flight.global_architecture.idle_inhibitor.IdleInhibitor.active
```

````

````{py:method} acquire()
:canonical: space_flight.global_architecture.idle_inhibitor.IdleInhibitor.acquire

```{autodoc2-docstring} space_flight.global_architecture.idle_inhibitor.IdleInhibitor.acquire
```

````

````{py:method} release()
:canonical: space_flight.global_architecture.idle_inhibitor.IdleInhibitor.release

```{autodoc2-docstring} space_flight.global_architecture.idle_inhibitor.IdleInhibitor.release
```

````

````{py:method} _call_linux(method: str, signature: str, body: tuple)
:canonical: space_flight.global_architecture.idle_inhibitor.IdleInhibitor._call_linux

```{autodoc2-docstring} space_flight.global_architecture.idle_inhibitor.IdleInhibitor._call_linux
```

````

````{py:method} _acquire_linux()
:canonical: space_flight.global_architecture.idle_inhibitor.IdleInhibitor._acquire_linux

```{autodoc2-docstring} space_flight.global_architecture.idle_inhibitor.IdleInhibitor._acquire_linux
```

````

````{py:method} _release_linux()
:canonical: space_flight.global_architecture.idle_inhibitor.IdleInhibitor._release_linux

```{autodoc2-docstring} space_flight.global_architecture.idle_inhibitor.IdleInhibitor._release_linux
```

````

````{py:method} _close_linux_connection()
:canonical: space_flight.global_architecture.idle_inhibitor.IdleInhibitor._close_linux_connection

```{autodoc2-docstring} space_flight.global_architecture.idle_inhibitor.IdleInhibitor._close_linux_connection
```

````

````{py:method} _set_execution_state(flags: int)
:canonical: space_flight.global_architecture.idle_inhibitor.IdleInhibitor._set_execution_state
:staticmethod:

```{autodoc2-docstring} space_flight.global_architecture.idle_inhibitor.IdleInhibitor._set_execution_state
```

````

````{py:method} _acquire_windows()
:canonical: space_flight.global_architecture.idle_inhibitor.IdleInhibitor._acquire_windows

```{autodoc2-docstring} space_flight.global_architecture.idle_inhibitor.IdleInhibitor._acquire_windows
```

````

````{py:method} _release_windows()
:canonical: space_flight.global_architecture.idle_inhibitor.IdleInhibitor._release_windows

```{autodoc2-docstring} space_flight.global_architecture.idle_inhibitor.IdleInhibitor._release_windows
```

````

````{py:method} _acquire_macos()
:canonical: space_flight.global_architecture.idle_inhibitor.IdleInhibitor._acquire_macos

```{autodoc2-docstring} space_flight.global_architecture.idle_inhibitor.IdleInhibitor._acquire_macos
```

````

````{py:method} _release_macos()
:canonical: space_flight.global_architecture.idle_inhibitor.IdleInhibitor._release_macos

```{autodoc2-docstring} space_flight.global_architecture.idle_inhibitor.IdleInhibitor._release_macos
```

````

`````

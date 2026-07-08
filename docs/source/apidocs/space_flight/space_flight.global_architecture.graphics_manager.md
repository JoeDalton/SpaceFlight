# {py:mod}`space_flight.global_architecture.graphics_manager`

```{py:module} space_flight.global_architecture.graphics_manager
```

```{autodoc2-docstring} space_flight.global_architecture.graphics_manager
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`GraphicsManager <space_flight.global_architecture.graphics_manager.GraphicsManager>`
  - ```{autodoc2-docstring} space_flight.global_architecture.graphics_manager.GraphicsManager
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`LOGGER <space_flight.global_architecture.graphics_manager.LOGGER>`
  - ```{autodoc2-docstring} space_flight.global_architecture.graphics_manager.LOGGER
    :summary:
    ```
* - {py:obj}`_COMPOSITE_VERT <space_flight.global_architecture.graphics_manager._COMPOSITE_VERT>`
  - ```{autodoc2-docstring} space_flight.global_architecture.graphics_manager._COMPOSITE_VERT
    :summary:
    ```
* - {py:obj}`_BLIT_FRAG <space_flight.global_architecture.graphics_manager._BLIT_FRAG>`
  - ```{autodoc2-docstring} space_flight.global_architecture.graphics_manager._BLIT_FRAG
    :summary:
    ```
* - {py:obj}`_FXAA_FRAG <space_flight.global_architecture.graphics_manager._FXAA_FRAG>`
  - ```{autodoc2-docstring} space_flight.global_architecture.graphics_manager._FXAA_FRAG
    :summary:
    ```
* - {py:obj}`_SCENE_BUFFER_SORT <space_flight.global_architecture.graphics_manager._SCENE_BUFFER_SORT>`
  - ```{autodoc2-docstring} space_flight.global_architecture.graphics_manager._SCENE_BUFFER_SORT
    :summary:
    ```
````

### API

````{py:data} LOGGER
:canonical: space_flight.global_architecture.graphics_manager.LOGGER
:value: >
   'getLogger(...)'

```{autodoc2-docstring} space_flight.global_architecture.graphics_manager.LOGGER
```

````

````{py:data} _COMPOSITE_VERT
:canonical: space_flight.global_architecture.graphics_manager._COMPOSITE_VERT
:value: >
   None

```{autodoc2-docstring} space_flight.global_architecture.graphics_manager._COMPOSITE_VERT
```

````

````{py:data} _BLIT_FRAG
:canonical: space_flight.global_architecture.graphics_manager._BLIT_FRAG
:value: >
   None

```{autodoc2-docstring} space_flight.global_architecture.graphics_manager._BLIT_FRAG
```

````

````{py:data} _FXAA_FRAG
:canonical: space_flight.global_architecture.graphics_manager._FXAA_FRAG
:value: >
   None

```{autodoc2-docstring} space_flight.global_architecture.graphics_manager._FXAA_FRAG
```

````

````{py:data} _SCENE_BUFFER_SORT
:canonical: space_flight.global_architecture.graphics_manager._SCENE_BUFFER_SORT
:value: >
   None

```{autodoc2-docstring} space_flight.global_architecture.graphics_manager._SCENE_BUFFER_SORT
```

````

`````{py:class} GraphicsManager(app)
:canonical: space_flight.global_architecture.graphics_manager.GraphicsManager

```{autodoc2-docstring} space_flight.global_architecture.graphics_manager.GraphicsManager
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.global_architecture.graphics_manager.GraphicsManager.__init__
```

````{py:property} settings
:canonical: space_flight.global_architecture.graphics_manager.GraphicsManager.settings
:type: dict

```{autodoc2-docstring} space_flight.global_architecture.graphics_manager.GraphicsManager.settings
```

````

````{py:method} open_game_window()
:canonical: space_flight.global_architecture.graphics_manager.GraphicsManager.open_game_window

```{autodoc2-docstring} space_flight.global_architecture.graphics_manager.GraphicsManager.open_game_window
```

````

````{py:method} apply_window_settings()
:canonical: space_flight.global_architecture.graphics_manager.GraphicsManager.apply_window_settings

```{autodoc2-docstring} space_flight.global_architecture.graphics_manager.GraphicsManager.apply_window_settings
```

````

````{py:method} _build_window_props() -> panda3d.core.WindowProperties
:canonical: space_flight.global_architecture.graphics_manager.GraphicsManager._build_window_props

```{autodoc2-docstring} space_flight.global_architecture.graphics_manager.GraphicsManager._build_window_props
```

````

````{py:method} get_render_size() -> tuple[int, int]
:canonical: space_flight.global_architecture.graphics_manager.GraphicsManager.get_render_size

```{autodoc2-docstring} space_flight.global_architecture.graphics_manager.GraphicsManager.get_render_size
```

````

````{py:method} begin_scene_render()
:canonical: space_flight.global_architecture.graphics_manager.GraphicsManager.begin_scene_render

```{autodoc2-docstring} space_flight.global_architecture.graphics_manager.GraphicsManager.begin_scene_render
```

````

````{py:method} _update_pipeline_uniforms(task)
:canonical: space_flight.global_architecture.graphics_manager.GraphicsManager._update_pipeline_uniforms

```{autodoc2-docstring} space_flight.global_architecture.graphics_manager.GraphicsManager._update_pipeline_uniforms
```

````

````{py:method} end_scene_render()
:canonical: space_flight.global_architecture.graphics_manager.GraphicsManager.end_scene_render

```{autodoc2-docstring} space_flight.global_architecture.graphics_manager.GraphicsManager.end_scene_render
```

````

`````

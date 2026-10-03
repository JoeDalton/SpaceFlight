# {py:mod}`space_flight.global_architecture.asset_manager`

```{py:module} space_flight.global_architecture.asset_manager
```

```{autodoc2-docstring} space_flight.global_architecture.asset_manager
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`AssetManager <space_flight.global_architecture.asset_manager.AssetManager>`
  - ```{autodoc2-docstring} space_flight.global_architecture.asset_manager.AssetManager
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`gltf_model_tilt_quaternion <space_flight.global_architecture.asset_manager.gltf_model_tilt_quaternion>`
  - ```{autodoc2-docstring} space_flight.global_architecture.asset_manager.gltf_model_tilt_quaternion
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`COMMON_ASSETS_TO_LOAD <space_flight.global_architecture.asset_manager.COMMON_ASSETS_TO_LOAD>`
  - ```{autodoc2-docstring} space_flight.global_architecture.asset_manager.COMMON_ASSETS_TO_LOAD
    :summary:
    ```
````

### API

````{py:data} COMMON_ASSETS_TO_LOAD
:canonical: space_flight.global_architecture.asset_manager.COMMON_ASSETS_TO_LOAD
:value: >
   [('model',), ('model',), ('model',), ('model',), ('model',), ('model',), ('model',), ('texture',), (...

```{autodoc2-docstring} space_flight.global_architecture.asset_manager.COMMON_ASSETS_TO_LOAD
```

````

`````{py:class} AssetManager(app: direct.showbase.ShowBase.ShowBase)
:canonical: space_flight.global_architecture.asset_manager.AssetManager

```{autodoc2-docstring} space_flight.global_architecture.asset_manager.AssetManager
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.global_architecture.asset_manager.AssetManager.__init__
```

````{py:method} get_asset(asset_type: str, path: pathlib.Path, pattern: str = '') -> typing.Any
:canonical: space_flight.global_architecture.asset_manager.AssetManager.get_asset

```{autodoc2-docstring} space_flight.global_architecture.asset_manager.AssetManager.get_asset
```

````

````{py:method} load_game_assets(app_state: space_flight.menus.splash_state.SplashState, assets_to_load: list[tuple[str, pathlib.Path, str]] | None = None)
:canonical: space_flight.global_architecture.asset_manager.AssetManager.load_game_assets

```{autodoc2-docstring} space_flight.global_architecture.asset_manager.AssetManager.load_game_assets
```

````

````{py:method} load_assets_task(app_state: space_flight.menus.splash_state.SplashState, task: direct.task.Task.Task) -> int
:canonical: space_flight.global_architecture.asset_manager.AssetManager.load_assets_task

```{autodoc2-docstring} space_flight.global_architecture.asset_manager.AssetManager.load_assets_task
```

````

````{py:method} load_single_asset(asset_type: str, path: pathlib.Path, pattern: str)
:canonical: space_flight.global_architecture.asset_manager.AssetManager.load_single_asset

```{autodoc2-docstring} space_flight.global_architecture.asset_manager.AssetManager.load_single_asset
```

````

````{py:method} instantiate_3d_model_to_node(path: pathlib.Path | str, parent_node: panda3d.core.NodePath)
:canonical: space_flight.global_architecture.asset_manager.AssetManager.instantiate_3d_model_to_node

```{autodoc2-docstring} space_flight.global_architecture.asset_manager.AssetManager.instantiate_3d_model_to_node
```

````

`````

````{py:function} gltf_model_tilt_quaternion(game: space_flight.game.flight_state.FlightState) -> numpy.quaternion
:canonical: space_flight.global_architecture.asset_manager.gltf_model_tilt_quaternion

```{autodoc2-docstring} space_flight.global_architecture.asset_manager.gltf_model_tilt_quaternion
```
````

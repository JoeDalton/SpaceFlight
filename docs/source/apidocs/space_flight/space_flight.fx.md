# {py:mod}`space_flight.fx`

```{py:module} space_flight.fx
```

```{autodoc2-docstring} space_flight.fx
:allowtitles:
```

## Submodules

```{toctree}
:titlesonly:
:maxdepth: 1

space_flight.fx.sfx
space_flight.fx.speed_dust_cloud
space_flight.fx.explosion_fx
```

## Package Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`ParticleBuffer <space_flight.fx.ParticleBuffer>`
  - ```{autodoc2-docstring} space_flight.fx.ParticleBuffer
    :summary:
    ```
````

### Functions

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`make_geom_vertex_format <space_flight.fx.make_geom_vertex_format>`
  - ```{autodoc2-docstring} space_flight.fx.make_geom_vertex_format
    :summary:
    ```
* - {py:obj}`load_atlas <space_flight.fx.load_atlas>`
  - ```{autodoc2-docstring} space_flight.fx.load_atlas
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`POOL_SIZE <space_flight.fx.POOL_SIZE>`
  - ```{autodoc2-docstring} space_flight.fx.POOL_SIZE
    :summary:
    ```
* - {py:obj}`CORNERS <space_flight.fx.CORNERS>`
  - ```{autodoc2-docstring} space_flight.fx.CORNERS
    :summary:
    ```
* - {py:obj}`TRIS <space_flight.fx.TRIS>`
  - ```{autodoc2-docstring} space_flight.fx.TRIS
    :summary:
    ```
* - {py:obj}`FMT <space_flight.fx.FMT>`
  - ```{autodoc2-docstring} space_flight.fx.FMT
    :summary:
    ```
````

### API

````{py:data} POOL_SIZE
:canonical: space_flight.fx.POOL_SIZE
:value: >
   512

```{autodoc2-docstring} space_flight.fx.POOL_SIZE
```

````

````{py:data} CORNERS
:canonical: space_flight.fx.CORNERS
:value: >
   [(), (1.0,), (1.0, 1.0), ()]

```{autodoc2-docstring} space_flight.fx.CORNERS
```

````

````{py:data} TRIS
:canonical: space_flight.fx.TRIS
:value: >
   [0, 1, 2, 0, 2, 3]

```{autodoc2-docstring} space_flight.fx.TRIS
```

````

````{py:function} make_geom_vertex_format() -> panda3d.core.GeomVertexFormat
:canonical: space_flight.fx.make_geom_vertex_format

```{autodoc2-docstring} space_flight.fx.make_geom_vertex_format
```
````

````{py:data} FMT
:canonical: space_flight.fx.FMT
:value: >
   'make_geom_vertex_format(...)'

```{autodoc2-docstring} space_flight.fx.FMT
```

````

`````{py:class} ParticleBuffer(game, vert_src: str, frag_src: str, texture: panda3d.core.Texture | None = None, additive: bool = False, bin_order: int = 20, task_name: str = 'particle_buffer_update')
:canonical: space_flight.fx.ParticleBuffer

```{autodoc2-docstring} space_flight.fx.ParticleBuffer
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.fx.ParticleBuffer.__init__
```

````{py:method} alloc_slot() -> int | None
:canonical: space_flight.fx.ParticleBuffer.alloc_slot

```{autodoc2-docstring} space_flight.fx.ParticleBuffer.alloc_slot
```

````

````{py:method} write_slot(slot_index: int, pos: panda3d.core.Point3, vel: panda3d.core.Vec3, color_w: float, texcoord_w: float, spawn_delay: float = 0.0, slot_duration: float | None = None)
:canonical: space_flight.fx.ParticleBuffer.write_slot

```{autodoc2-docstring} space_flight.fx.ParticleBuffer.write_slot
```

````

````{py:method} update()
:canonical: space_flight.fx.ParticleBuffer.update

```{autodoc2-docstring} space_flight.fx.ParticleBuffer.update
```

````

````{py:method} set_input(name: str, value)
:canonical: space_flight.fx.ParticleBuffer.set_input

```{autodoc2-docstring} space_flight.fx.ParticleBuffer.set_input
```

````

````{py:method} set_texture(texture: panda3d.core.Texture)
:canonical: space_flight.fx.ParticleBuffer.set_texture

```{autodoc2-docstring} space_flight.fx.ParticleBuffer.set_texture
```

````

````{py:method} clean()
:canonical: space_flight.fx.ParticleBuffer.clean

```{autodoc2-docstring} space_flight.fx.ParticleBuffer.clean
```

````

`````

````{py:function} load_atlas(game, texture_path: pathlib.Path, json_path: pathlib.Path) -> tuple[panda3d.core.Texture, list]
:canonical: space_flight.fx.load_atlas

```{autodoc2-docstring} space_flight.fx.load_atlas
```
````

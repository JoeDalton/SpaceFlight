# {py:mod}`space_flight.ai.interactions`

```{py:module} space_flight.ai.interactions
```

```{autodoc2-docstring} space_flight.ai.interactions
:allowtitles:
```

## Module Contents

### Classes

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`Interactions <space_flight.ai.interactions.Interactions>`
  - ```{autodoc2-docstring} space_flight.ai.interactions.Interactions
    :summary:
    ```
````

### Data

````{list-table}
:class: autosummary longtable
:align: left

* - {py:obj}`MAX_ACTORS <space_flight.ai.interactions.MAX_ACTORS>`
  - ```{autodoc2-docstring} space_flight.ai.interactions.MAX_ACTORS
    :summary:
    ```
````

### API

````{py:data} MAX_ACTORS
:canonical: space_flight.ai.interactions.MAX_ACTORS
:value: >
   64

```{autodoc2-docstring} space_flight.ai.interactions.MAX_ACTORS
```

````

`````{py:class} Interactions(max_actors: int = MAX_ACTORS)
:canonical: space_flight.ai.interactions.Interactions

```{autodoc2-docstring} space_flight.ai.interactions.Interactions
```

```{rubric} Initialization
```

```{autodoc2-docstring} space_flight.ai.interactions.Interactions.__init__
```

````{py:property} n_actors
:canonical: space_flight.ai.interactions.Interactions.n_actors
:type: int

```{autodoc2-docstring} space_flight.ai.interactions.Interactions.n_actors
```

````

````{py:property} live_actors
:canonical: space_flight.ai.interactions.Interactions.live_actors
:type: typing.List

```{autodoc2-docstring} space_flight.ai.interactions.Interactions.live_actors
```

````

````{py:method} add_actor(actor)
:canonical: space_flight.ai.interactions.Interactions.add_actor

```{autodoc2-docstring} space_flight.ai.interactions.Interactions.add_actor
```

````

````{py:method} remove_actor(actor)
:canonical: space_flight.ai.interactions.Interactions.remove_actor

```{autodoc2-docstring} space_flight.ai.interactions.Interactions.remove_actor
```

````

````{py:method} get_actor_index_from_id(actor_id: uuid.UUID) -> int
:canonical: space_flight.ai.interactions.Interactions.get_actor_index_from_id

```{autodoc2-docstring} space_flight.ai.interactions.Interactions.get_actor_index_from_id
```

````

````{py:method} update_interactions()
:canonical: space_flight.ai.interactions.Interactions.update_interactions

```{autodoc2-docstring} space_flight.ai.interactions.Interactions.update_interactions
```

````

````{py:method} clean()
:canonical: space_flight.ai.interactions.Interactions.clean

```{autodoc2-docstring} space_flight.ai.interactions.Interactions.clean
```

````

`````
